#!/usr/bin/env python3
"""
Script to install Illumio Helm chart with parameterized values from Hashicorp Vault.

This script addresses the following requirements:
1. Retrieve secrets from Hashicorp Vault using get_pce_secrets() from ejvault.py
2. Install Helm chart with --set options for:
   - cluster_id: Cluster ID from PCE
   - cluster_token: Cluster Token from PCE
   - cluster_code: Pairing key for cluster
   - registry: Container registry to use
"""
import os
import subprocess
import argparse
import sys
import json
import tempfile
from bin.illumio import ejvault

def retrieve_cluster_secrets(cluster_name):
    """
    Retrieve cluster secrets from Vault for the specified cluster.
    
    Args:
        cluster_name (str): Name of the Kubernetes cluster
        
    Returns:
        tuple: (container_cluster_id, container_cluster_token, pairing_key)
              or (None, None, None) if retrieval fails
    """
    try:
        # First get PCE credentials using ejvault's get_pce_secrets function
        success, user, key = ejvault.get_pce_secrets()
        if not success:
            print("Failed to retrieve PCE credentials from Vault")
            return None, None, None
            
        # Get token for Vault authentication
        success, env, token = ejvault.get_token()
        if not success:
            print("Failed to authenticate with Vault")
            return None, None, None
            
        # Setup headers and proxies for Vault API requests
        headers = {"X-Vault-Token": token}
        proxies = {"http": None, "https": None}
        
        # Get the Vault URL for Illumio cluster secrets
        if "ILLUMIO_CLUSTER_SECRETS_PATH" not in os.environ:
            print("ILLUMIO_CLUSTER_SECRETS_PATH environment variable not set")
            print("Trying default path...")
            # Default path as fallback
            url = f"secrets/illumio/{cluster_name}"
        else:
            url = os.environ.get("ILLUMIO_CLUSTER_SECRETS_PATH")
            
        # Retrieve secrets from Vault
        print(f"Retrieving Illumio cluster secrets from Vault for cluster: {cluster_name}")
        try:
            response = ejvault.requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=10)
            if response.status_code != 200:
                print(f"Failed to retrieve cluster secrets from Vault: HTTP {response.status_code}")
                return None, None, None
                
            # Extract the secrets
            secrets_data = response.json().get('data', {})
            
            # Get the specific secrets for this cluster
            container_cluster_id = secrets_data.get(f"{cluster_name}_container_cluster_id")
            container_cluster_token = secrets_data.get(f"{cluster_name}_container_cluster_token")
            pairing_key = secrets_data.get(f"{cluster_name}_pairing_key")
            
            # Check if any secrets are missing
            missing_secrets = []
            if not container_cluster_id:
                missing_secrets.append("container_cluster_id")
            if not container_cluster_token:
                missing_secrets.append("container_cluster_token")
            if not pairing_key:
                missing_secrets.append("pairing_key")
                
            if missing_secrets:
                print(f"Missing required secrets in Vault: {', '.join(missing_secrets)}")
                return None, None, None
                
            # Clean up the secrets (remove quotes and whitespace)
            container_cluster_id = ejvault.cleanup_creds(container_cluster_id)
            container_cluster_token = ejvault.cleanup_creds(container_cluster_token)
            pairing_key = ejvault.cleanup_creds(pairing_key)
            
            print("Successfully retrieved cluster secrets from Vault")
            return container_cluster_id, container_cluster_token, pairing_key
            
        except Exception as ex:
            print(f"Failed to retrieve cluster secrets from Vault: {str(ex)}")
            return None, None, None
            
    except Exception as e:
        print(f"Error retrieving cluster secrets: {str(e)}")
        return None, None, None

def validate_helm_chart(chart_path):
    """
    Validate the Helm chart to ensure it can be installed.
    
    Args:
        chart_path (str): Path to the Helm chart
        
    Returns:
        bool: True if chart is valid, False otherwise
    """
    try:
        print("Validating Helm chart...")
        process = subprocess.run(
            ["helm", "lint", chart_path],
            check=False,  # Don't fail if linting has warnings
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Check if there are any errors (as opposed to warnings)
        if "Error:" in process.stdout or "Error:" in process.stderr:
            print("Helm chart validation failed:")
            print(process.stdout)
            print(process.stderr)
            return False
            
        print("Helm chart validation successful")
        return True
        
    except Exception as e:
        print(f"Error validating Helm chart: {str(e)}")
        return False

def install_illumio_helm_chart(cluster_name, chart_path='.', namespace='illumio-system', 
                              values_file='values.yaml', release_name='illumio', 
                              registry='registry.access.redhat.com/ubi9', 
                              create_namespace=False, debug=False):
    """
    Install Illumio Helm chart with values from Vault.
    
    Args:
        cluster_name (str): Name of the Kubernetes cluster
        chart_path (str): Path to the Helm chart
        namespace (str): Kubernetes namespace
        values_file (str): Path to values.yaml file
        release_name (str): Helm release name
        registry (str): Container registry to use
        create_namespace (bool): Create namespace if it doesn't exist
        debug (bool): Enable debug output
        
    Returns:
        bool: True if installation successful, False otherwise
    """
    # First, check if namespace exists and create it if needed
    if create_namespace:
        try:
            print(f"Checking if namespace {namespace} exists...")
            result = subprocess.run(
                ["kubectl", "get", "namespace", namespace],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
            
            if result.returncode != 0:
                print(f"Creating namespace {namespace}...")
                subprocess.run(
                    ["kubectl", "create", "namespace", namespace],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                print(f"Namespace {namespace} created")
            else:
                print(f"Namespace {namespace} already exists")
                
        except Exception as e:
            print(f"Error managing namespace: {str(e)}")
            return False
    
    # Validate Helm chart
    if not validate_helm_chart(chart_path):
        if not debug:
            print("Helm chart validation failed. Use --debug for more details.")
            print("Continuing with installation anyway...")
    
    # Retrieve secrets from Vault
    container_cluster_id, container_cluster_token, pairing_key = retrieve_cluster_secrets(cluster_name)
    
    if not all([container_cluster_id, container_cluster_token, pairing_key]):
        print("Failed to retrieve required secrets from Vault")
        return False
        
    try:
        # Build the Helm install command
        cmd = [
            "helm", "install", release_name,
            chart_path,
            "-n", namespace,
            "-f", values_file,
            "--set", f"cluster_id={container_cluster_id}",
            "--set", f"cluster_token={container_cluster_token}",
            "--set", f"cluster_code={pairing_key}",
            "--set", f"registry={registry}"
        ]
        
        # Add create-namespace flag if requested
        if create_namespace:
            cmd.append("--create-namespace")
            
        # Add debug flag if requested
        if debug:
            cmd.append("--debug")
            print(f"Executing command: {' '.join(cmd)}")
        
        # Execute Helm install command
        print(f"Installing Illumio Helm chart in namespace {namespace}...")
        process = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        print("Helm install command executed successfully")
        if debug:
            print(process.stdout)
            
        # Verify installation
        print("Verifying installation...")
        get_release = subprocess.run(
            ["helm", "status", release_name, "-n", namespace],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if "STATUS: deployed" in get_release.stdout:
            print("Illumio Helm chart deployed successfully!")
            return True
        else:
            print("Helm install command completed but release status is not 'deployed'")
            if debug:
                print(get_release.stdout)
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"Error executing Helm command: {str(e)}")
        print(f"Error details: {e.stderr}")
        return False
    except Exception as e:
        print(f"Unexpected error during Illumio installation: {str(e)}")
        return False

def main():
    """Parse arguments and install Illumio Helm chart."""
    parser = argparse.ArgumentParser(description='Install Illumio Helm chart with values from Vault')
    parser.add_argument('--cluster-name', required=True, help='Name of the Kubernetes cluster')
    parser.add_argument('--chart-path', default='.', help='Path to the Helm chart directory')
    parser.add_argument('--namespace', default='illumio-system', help='Kubernetes namespace')
    parser.add_argument('--values-file', default='values.yaml', help='Path to values.yaml file')
    parser.add_argument('--release-name', default='illumio', help='Helm release name')
    parser.add_argument('--registry', default='registry.access.redhat.com/ubi9', help='Container registry')
    parser.add_argument('--create-namespace', action='store_true', help='Create namespace if it does not exist')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    
    args = parser.parse_args()
    
    # Check if kubectl is installed
    try:
        subprocess.run(["kubectl", "version", "--client"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except:
        print("Error: kubectl is not installed or not in PATH")
        sys.exit(1)
    
    # Check if Helm is installed
    try:
        subprocess.run(["helm", "version", "--short"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except:
        print("Error: Helm is not installed or not in PATH")
        sys.exit(1)
    
    # Ensure values file exists
    if not os.path.isfile(os.path.join(args.chart_path, args.values_file)):
        print(f"Error: Values file '{args.values_file}' not found in chart path '{args.chart_path}'")
        sys.exit(1)
    
    # Install Illumio Helm chart
    result = install_illumio_helm_chart(
        args.cluster_name,
        args.chart_path,
        args.namespace,
        args.values_file,
        args.release_name,
        args.registry,
        args.create_namespace,
        args.debug
    )
    
    if result:
        print("="*80)
        print(f"Illumio Helm chart successfully installed!")
        print(f"Cluster: {args.cluster_name}")
        print(f"Namespace: {args.namespace}")
        print(f"Release: {args.release_name}")
        print("="*80)
        sys.exit(0)
    else:
        print("="*80)
        print("Illumio Helm chart installation failed")
        print("Check the error messages above for details")
        print("="*80)
        sys.exit(1)

if __name__ == "__main__":
    main() 