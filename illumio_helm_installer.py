#!/usr/bin/env python3
"""
Script to install Illumio Helm chart with parameterized values from Hashicorp Vault.
"""
import os
import subprocess
import argparse
import sys
import json
from bin.illumio import ejvault

class IllumioHelmInstaller:
    def __init__(self, cluster_name):
        """
        Initialize the installer with the cluster name.
        
        Args:
            cluster_name (str): Name of the Kubernetes cluster
        """
        self.cluster_name = cluster_name
        self.container_cluster_id = None
        self.container_cluster_token = None
        self.pairing_key = None
        
        # Fetch secrets from Vault
        self.fetch_secrets_from_vault()
    
    def fetch_secrets_from_vault(self):
        """
        Retrieve container cluster secrets from Vault.
        
        This method sets the following instance variables:
        - container_cluster_id
        - container_cluster_token
        - pairing_key
        """
        try:
            # Get token for accessing Vault
            success, env, token = ejvault.get_token()
            if not success:
                raise Exception("Failed to authenticate with Vault")
            
            # Set headers and proxies for Vault API requests
            headers = {"X-Vault-Token": token}
            proxies = {"http": None, "https": None}
            
            # Get the vault URL from environment variables
            if "ILLUMIO_SECRETS_PATH" not in os.environ:
                raise Exception("ILLUMIO_SECRETS_PATH environment variable not set")
                
            url = os.environ.get("ILLUMIO_SECRETS_PATH")
            
            # Make request to Vault to retrieve secrets
            print(f"Retrieving Illumio secrets from Vault for cluster: {self.cluster_name}")
            try:
                response = ejvault.requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=10)
                response.raise_for_status()
                
                # Extract secrets from the response
                secrets_data = response.json().get('data', {})
                
                # Get the specific secrets for this cluster
                self.container_cluster_id = secrets_data.get(f"{self.cluster_name}_container_cluster_id")
                self.container_cluster_token = secrets_data.get(f"{self.cluster_name}_container_cluster_token")
                self.pairing_key = secrets_data.get(f"{self.cluster_name}_pairing_key")
                
                if not all([self.container_cluster_id, self.container_cluster_token, self.pairing_key]):
                    raise Exception("One or more required secrets not found in Vault")
                
                # Clean up the values
                self.container_cluster_id = ejvault.cleanup_creds(self.container_cluster_id)
                self.container_cluster_token = ejvault.cleanup_creds(self.container_cluster_token)
                self.pairing_key = ejvault.cleanup_creds(self.pairing_key)
                
                print("Successfully retrieved secrets from Vault")
                
            except Exception as ex:
                raise Exception(f"Failed to retrieve secrets from Vault: {str(ex)}")
                
        except Exception as e:
            print(f"Error retrieving Illumio secrets: {str(e)}")
            sys.exit(1)
    
    def install_helm_chart(self, chart_path='.', namespace='illumio-system', 
                           values_file='values.yaml', release_name='illumio', 
                           registry='registry.access.redhat.com/ubi9', debug=False):
        """
        Install the Illumio Helm chart with the retrieved secrets.
        
        Args:
            chart_path (str): Path to the Helm chart directory
            namespace (str): Kubernetes namespace to install into
            values_file (str): Path to values.yaml file
            release_name (str): Helm release name
            registry (str): Container registry to use
            debug (bool): Enable debug output
            
        Returns:
            bool: True if installation was successful, False otherwise
        """
        # Ensure we have the required secrets
        if not all([self.container_cluster_id, self.container_cluster_token, self.pairing_key]):
            print("Error: Required secrets not found in Vault")
            return False
        
        # Build helm install command
        cmd = [
            "helm", "install", release_name, 
            chart_path,
            "-n", namespace,
            "-f", values_file,
            "--set", f"cluster_id={self.container_cluster_id}",
            "--set", f"cluster_token={self.container_cluster_token}",
            "--set", f"cluster_code={self.pairing_key}",
            "--set", f"registry={registry}"
        ]
        
        # Add debug flag if requested
        if debug:
            cmd.append("--debug")
            print(f"Executing: {' '.join(cmd)}")
        
        try:
            # Execute helm install command
            print(f"Installing Illumio Helm chart to namespace '{namespace}'...")
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
            
        except subprocess.CalledProcessError as e:
            print(f"Error executing Helm install command: {e.stderr}")
            return False
        except Exception as e:
            print(f"Unexpected error during Helm install: {str(e)}")
            return False

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Install Illumio Helm chart with values from Vault')
    parser.add_argument('--cluster-name', required=True, help='Name of the Kubernetes cluster')
    parser.add_argument('--chart-path', default='.', help='Path to the Helm chart directory (default: current directory)')
    parser.add_argument('--namespace', default='illumio-system', help='Kubernetes namespace to install into (default: illumio-system)')
    parser.add_argument('--values-file', default='values.yaml', help='Path to values.yaml file (default: values.yaml)')
    parser.add_argument('--release-name', default='illumio', help='Helm release name (default: illumio)')
    parser.add_argument('--registry', default='registry.access.redhat.com/ubi9', 
                      help='Container registry to use (default: registry.access.redhat.com/ubi9)')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    
    return parser.parse_args()

def main():
    """Main entry point."""
    args = parse_args()
    
    # Check if Helm is installed
    try:
        subprocess.run(["helm", "version", "--short"], 
                      check=True, 
                      stdout=subprocess.PIPE, 
                      stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        print("Error: Helm is not installed or not available in PATH")
        sys.exit(1)
    except Exception as e:
        print(f"Error checking for Helm: {str(e)}")
        sys.exit(1)
    
    # Create installer and install Helm chart
    try:
        installer = IllumioHelmInstaller(args.cluster_name)
        
        # Install the Helm chart
        success = installer.install_helm_chart(
            chart_path=args.chart_path,
            namespace=args.namespace,
            values_file=args.values_file,
            release_name=args.release_name,
            registry=args.registry,
            debug=args.debug
        )
        
        if success:
            print("="*80)
            print(f"Illumio Helm chart successfully installed!")
            print(f"Cluster: {args.cluster_name}")
            print(f"Namespace: {args.namespace}")
            print("="*80)
            sys.exit(0)
        else:
            print("="*80)
            print("Illumio Helm chart installation failed")
            print("Check the error messages above for details")
            print("="*80)
            sys.exit(1)
            
    except Exception as e:
        print(f"Error during Illumio installation: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 