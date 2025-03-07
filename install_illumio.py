#!/usr/bin/env python3
"""
Script to install Illumio Helm chart with parameterized values from Hashicorp Vault.

Requirements:
1. Retrieve secrets from Hashicorp Vault using get_pce_secrets() from ejvault.py
2. Install Helm chart with --set options for cluster_id, cluster_token, cluster_code, and registry
"""
import os
import subprocess
import argparse
import sys
from bin.illumio import ejvault

def install_illumio_helm_chart(cluster_name, chart_path='.', namespace='illumio-system', 
                              values_file='values.yaml', release_name='illumio', 
                              registry='registry.access.redhat.com/ubi9', debug=False):
    """
    Install Illumio Helm chart with values from Vault.
    
    Args:
        cluster_name (str): Name of the Kubernetes cluster
        chart_path (str): Path to the Helm chart
        namespace (str): Kubernetes namespace
        values_file (str): Path to values.yaml file
        release_name (str): Helm release name
        registry (str): Container registry to use
        debug (bool): Enable debug output
        
    Returns:
        bool: True if installation successful, False otherwise
    """
    # First, retrieve secrets from Vault
    try:
        # The existing ejvault.py doesn't have a function that returns the specific secrets we need
        # So we need to retrieve them using similar patterns from ejvault.py
        
        # Get token for Vault authentication
        success, env, token = ejvault.get_token()
        if not success:
            print("Failed to authenticate with Vault")
            return False
            
        # Setup headers and proxies for Vault API requests
        headers = {"X-Vault-Token": token}
        proxies = {"http": None, "https": None}
        
        # Get the Vault URL for Illumio secrets
        if "ILLUMIO_SECRETS_PATH" not in os.environ:
            print("ILLUMIO_SECRETS_PATH environment variable not set")
            return False
            
        url = os.environ.get("ILLUMIO_SECRETS_PATH")
        
        # Retrieve secrets from Vault
        print(f"Retrieving Illumio secrets from Vault for cluster: {cluster_name}")
        response = ejvault.requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=10)
        if response.status_code != 200:
            print(f"Failed to retrieve secrets from Vault: {response.status_code}")
            return False
            
        # Extract the secrets
        secrets_data = response.json().get('data', {})
        
        # Get the specific secrets for this cluster
        container_cluster_id = secrets_data.get(f"{cluster_name}_container_cluster_id")
        container_cluster_token = secrets_data.get(f"{cluster_name}_container_cluster_token")
        pairing_key = secrets_data.get(f"{cluster_name}_pairing_key")
        
        # Clean up the secrets (remove quotes and whitespace)
        container_cluster_id = ejvault.cleanup_creds(container_cluster_id) if container_cluster_id else None
        container_cluster_token = ejvault.cleanup_creds(container_cluster_token) if container_cluster_token else None
        pairing_key = ejvault.cleanup_creds(pairing_key) if pairing_key else None
        
        # Ensure all required secrets were retrieved
        if not all([container_cluster_id, container_cluster_token, pairing_key]):
            print("One or more required secrets not found in Vault")
            return False
            
        print("Successfully retrieved secrets from Vault")
        
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
            
        return True
        
    except Exception as e:
        print(f"Error during Illumio installation: {str(e)}")
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
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    
    args = parser.parse_args()
    
    # Check if Helm is installed
    try:
        subprocess.run(["helm", "version", "--short"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except:
        print("Error: Helm is not installed or not in PATH")
        sys.exit(1)
    
    # Install Illumio Helm chart
    result = install_illumio_helm_chart(
        args.cluster_name,
        args.chart_path,
        args.namespace,
        args.values_file,
        args.release_name,
        args.registry,
        args.debug
    )
    
    if result:
        print(f"Illumio Helm chart successfully installed for cluster {args.cluster_name}!")
        sys.exit(0)
    else:
        print("Illumio Helm chart installation failed")
        sys.exit(1)

if __name__ == "__main__":
    main() 