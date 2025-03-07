#!/usr/bin/env python3
import os
import subprocess
import argparse
import sys
from illumio import IllumioClusterManager

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Install Illumio Helm chart with values from Vault')
    parser.add_argument('--cluster-name', required=True, help='Name of the Kubernetes cluster')
    parser.add_argument('--chart-path', default='.', help='Path to the Helm chart directory (default: current directory)')
    parser.add_argument('--namespace', default='illumio-system', help='Kubernetes namespace to install into (default: illumio-system)')
    parser.add_argument('--create-namespace', action='store_true', help='Create namespace if it does not exist')
    parser.add_argument('--registry', default='registry.access.redhat.com/ubi9', 
                      help='Container registry to use (default: registry.access.redhat.com/ubi9)')
    parser.add_argument('--values-file', default='values.yaml', help='Path to values.yaml file (default: values.yaml)')
    parser.add_argument('--release-name', default='illumio', help='Helm release name (default: illumio)')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    
    return parser.parse_args()

def run_command(cmd, debug=False):
    """Run a shell command and return the output."""
    if debug:
        print(f"Running command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if debug:
            print(f"Command output: {result.stdout}")
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {' '.join(cmd)}")
        print(f"Error message: {e.stderr}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        sys.exit(1)

def install_illumio_helm_chart(args):
    """Install Illumio Helm chart with values from Vault."""
    print(f"Starting Illumio Helm chart installation for cluster: {args.cluster_name}")
    
    # Initialize IllumioClusterManager to retrieve secrets from Vault
    try:
        manager = IllumioClusterManager(args.cluster_name)
        
        # Check if cluster exists in PCE and create it if necessary
        if not manager.check_cluster_exists():
            print(f"Cluster {args.cluster_name} does not exist in PCE. Creating...")
            manager.create_cluster_label()
            manager.create_container_cluster()
            
        # Get or create pairing key if needed
        if not manager.pairing_key:
            print("No pairing key found. Creating pairing profile and key...")
            manager.create_pairing_profile()
            manager.create_pairing_key()
        
        # Build the Helm install command
        cmd = [
            "helm", "install", args.release_name, 
            args.chart_path,
            "-n", args.namespace,
            "-f", args.values_file,
            "--set", f"cluster_id={manager.container_cluster_id}",
            "--set", f"cluster_token={manager.container_cluster_token}",
            "--set", f"cluster_code={manager.pairing_key}",
            "--set", f"registry={args.registry}"
        ]
        
        # Add --create-namespace flag if specified
        if args.create_namespace:
            cmd.extend(["--create-namespace"])
            
        # Add --debug flag if specified
        if args.debug:
            cmd.extend(["--debug"])
            
        # Run the Helm install command
        print(f"Installing Illumio Helm chart in namespace: {args.namespace}")
        result = run_command(cmd, args.debug)
        
        print("Illumio Helm chart installation completed successfully!")
        
        # Store the installation secrets in Vault for future reference
        manager.store_illumio_install_secrets()
        
        return True
        
    except Exception as e:
        print(f"Error during Illumio installation: {str(e)}")
        return False

def main():
    args = parse_args()
    
    # Ensure helm is installed
    try:
        run_command(["helm", "version", "--short"], args.debug)
    except:
        print("Error: Helm is not installed or not available in PATH")
        sys.exit(1)
    
    # Create namespace if --create-namespace is specified
    if args.create_namespace:
        print(f"Ensuring namespace {args.namespace} exists...")
        try:
            result = run_command(["kubectl", "get", "namespace", args.namespace], False)
            print(f"Namespace {args.namespace} already exists")
        except:
            print(f"Creating namespace {args.namespace}...")
            run_command(["kubectl", "create", "namespace", args.namespace], args.debug)
    
    # Install Illumio Helm chart
    success = install_illumio_helm_chart(args)
    
    if success:
        print("="*80)
        print(f"Illumio has been successfully installed in cluster: {args.cluster_name}")
        print(f"Namespace: {args.namespace}")
        print("="*80)
    else:
        print("Installation failed. Please check the error messages above.")
        sys.exit(1)

if __name__ == "__main__":
    main() 