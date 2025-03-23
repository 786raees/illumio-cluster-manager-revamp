#!/usr/bin/env python3
"""
Script to manage Illumio clusters and install Illumio Helm chart with parameterized values from Hashicorp Vault.
 
This script addresses the following requirements:
1. Create and manage Illumio clusters in PCE
2. Assign labels to clusters and profiles
3. Create pairing profiles and generate pairing keys
4. Retrieve secrets from Hashicorp Vault using get_pce_secrets() from ejvault.py
5. Install Helm chart with --set options for:
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
import re
import requests
import urllib3
import ruamel.yaml
from bin.illumio import ejvault
from bin.illumio import ejconfig
from bin.illumio import ejfile

class IllumioClusterManager:
    def __init__(self, cluster_name):
        self.cluster_name = cluster_name
        self.org = ejconfig.org_id
        self.container_cluster_id = ""
        self.container_workload_profile_id = ""
        self.container_cluster_token = ""
        self.pairing_profile_id = ""
        self.pairing_key = ""
        self.user, self.key = self.get_pce_secrets()
        self.base_url = f"https://us-scp14.illum.io/api/v2/orgs/{self.org}"

    def get_pce_secrets(self):
        success, user, key = ejvault.get_pce_secrets()
        if not success:
            raise Exception("Could not retrieve API credentials from Vault")
        return user, key

    def get_requests(self, url):
        headers = {'Content-Type': 'application/json'}
        proxies = {'http': None, 'https': None}
        auth = (self.user, self.key)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.get(url, timeout=15, verify=False, headers=headers, proxies=proxies, auth=auth)
        response.raise_for_status()
        return response.json()

    def post_requests(self, url, data):
        headers = {'Content-Type': 'application/json'}
        proxies = {'http': None, 'https': None}
        auth = (self.user, self.key)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.post(url, timeout=15, verify=False, headers=headers, proxies=proxies, auth=auth, data=data)
        response.raise_for_status()
        return response.json()

    def put_requests(self, url, data):
        headers = {'Content-Type': 'application/json'}
        proxies = {'http': None, 'https': None}
        auth = (self.user, self.key)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.put(url, timeout=15, verify=False, headers=headers, proxies=proxies, auth=auth, data=data)
        response.raise_for_status()
        return response.json()

    def check_cluster_exists(self):
        cluster_url = f"{self.base_url}/container_clusters"
        clusters = self.get_requests(cluster_url)
        for cluster in clusters:
            if cluster["name"] == self.cluster_name:
                self.container_cluster_id = cluster["href"].split('/', 4)[-1]
                return True
        return False

    def create_cluster_label(self):
        label_url = f"{self.base_url}/labels"
        new_label = json.dumps({"key": "cluster", "value": self.cluster_name})
        self.post_requests(label_url, new_label)
        print(f"Cluster label {self.cluster_name.upper()} created.")

    def create_container_cluster(self):
        container_cluster_url = f"{self.base_url}/container_clusters"
        new_cluster = json.dumps({"name": self.cluster_name})
        cluster_details = self.post_requests(container_cluster_url, new_cluster)
        self.container_cluster_id = cluster_details["href"].split('/', 4)[-1]
        self.container_cluster_token = cluster_details.get("container_cluster_token", "")
        print(f"Container Cluster {self.cluster_name.upper()} created.")
        return cluster_details

    def get_labels(self):
        """
        Get all labels for the cluster to be used in pairing profile
        This includes cluster label, environment, location, role, etc.
        """
        label_url = f"{self.base_url}/labels"
        labels = self.get_requests(label_url)
        label_hrefs = []
        
        # Get cluster label
        for label in labels:
            if label.get("key") == "cluster" and label.get("value") == self.cluster_name:
                label_hrefs.append({"href": label["href"]})
        
        # Get environment label based on cluster name convention
        target_env = self.cluster_name[2:5]
        env_value = None
        if target_env == "dev":
            env_value = "Development"
        elif target_env == "cln" or target_env == "uat":
            env_value = "Clone"
        elif target_env == "prd":
            env_value = "Production"
        else:
            target_env = self.cluster_name[5:6]
            if target_env == 'd':
                env_value = "Development"
            elif target_env == 'q' or target_env == 'a' or target_env == 'c':
                env_value = "Clone"
            elif target_env == 'p':
                env_value = "Production"
        
        # Get location label based on cluster name convention
        target_location = self.cluster_name[6:7]
        location_value = None
        if target_location == 's':
            location_value = "Azure South Central US"
        elif target_location == 'n':
            location_value = "Azure North Central US"
        else:
            location_value = "Azure Central US"
        
        # Get cluster type label
        cluster_type = "general"
        if "gtw" in self.cluster_name:
            cluster_type = "mulesoft"
        
        # Add environment, location and cluster type labels
        for label in labels:
            if env_value and label.get("key") == "env" and label.get("value") == env_value:
                label_hrefs.append({"href": label["href"]})
            elif location_value and label.get("key") == "loc" and label.get("value") == location_value:
                label_hrefs.append({"href": label["href"]})
            elif label.get("key") == "app" and label.get("value") == cluster_type:
                label_hrefs.append({"href": label["href"]})
            elif label.get("key") == "role" and label.get("value") in ["Container", "Cluster Node"]:
                label_hrefs.append({"href": label["href"]})
        
        return label_hrefs

    def assign_namespace_labels(self, item, label_answer_json):
        """Assign namespace labels to container workload profiles"""
        assigned_labels = item.get("assign_labels", [])
        profile_href = item["href"]
        self.container_workload_profile_id = profile_href.split('/', 6)[-1]
        profile_details_url = f"{self.base_url}/container_clusters/{self.container_cluster_id}/container_workload_profiles/{self.container_workload_profile_id}"
        assigned = False
        label_exists = False
        namespace = item["namespace"]

        for label in label_answer_json:
            if label["value"] == namespace:
                label_href = label["href"]
                label_exists = True
                print(f"Namespace label {namespace.upper()} exists.")
                for assigned_label in assigned_labels:
                    if label_href == assigned_label.get("href"):
                        assigned = True
                        print(f"Namespace label already assigned for {namespace.upper()} profile in cluster {self.cluster_name.upper()}")
                        break
                if not assigned:
                    namespace_label = json.dumps({"href": label_href})
                    assigned_labels.append(json.loads(namespace_label))
                    label_update = json.dumps({"assign_labels": assigned_labels})
                    self.put_requests(profile_details_url, label_update)
                    print(f"Namespace label assigned to {namespace.upper()} profile in cluster {self.cluster_name.upper()}")
        if not label_exists:
            self.create_assign_namespace_label(namespace, profile_details_url)

    def create_assign_namespace_label(self, namespace, profile_details_url):
        """Create and assign a namespace label to a container workload profile"""
        label_url = f"{self.base_url}/labels"
        new_label = json.dumps({"key": "namespace", "value": namespace})
        new_label_response = self.post_requests(label_url, new_label)
        new_label_href = new_label_response["href"]
        namespace_label = json.dumps({"href": new_label_href})
        assigned_labels = [json.loads(namespace_label)]
        label_update = json.dumps({"assign_labels": assigned_labels})
        self.put_requests(profile_details_url, label_update)
        print(f"Namespace label created and assigned to {namespace.upper()} profile in cluster {self.cluster_name.upper()}")

    def assign_default_labels(self, item):
        """Assign default labels to container workload profiles"""
        profile_href = item["href"]
        self.container_workload_profile_id = profile_href.split('/', 6)[-1]
        profile_details_url = f"{self.base_url}/container_clusters/{self.container_cluster_id}/container_workload_profiles/{self.container_workload_profile_id}"
        
        # Get current profile state
        profile = self.get_requests(profile_details_url)
        
        # Check if profile is managed, if not set it to managed
        if not profile.get("managed", False):
            new_state = json.dumps({"managed": True, "enforcement_mode": "visibility_only"})
            self.put_requests(profile_details_url, new_state)
            print(f"Set profile to MANAGED and enforcement mode to VISIBILITY ONLY")
        
        # Get all labels
        label_url = f"{self.base_url}/labels"
        label_answer = self.get_requests(label_url)
        
        # Prepare labels to assign
        labels = []
        label_list = ["data", "kubeapi", "metadataapi", "riskscore"]
        
        # Process each label type
        for list_label in label_list:
            if list_label == "data" or list_label == "riskscore":
                # These labels can have multiple values
                restrictions = []
                for pce_label in label_answer:
                    if pce_label.get("key") == list_label:
                        restrictions.append({"href": pce_label["href"]})
                
                if restrictions:
                    labels.append({"key": list_label, "restriction": restrictions})
            else:
                # These labels have a single value
                for pce_label in label_answer:
                    if pce_label.get("key") == list_label:
                        labels.append({
                            "key": list_label, 
                            "restriction": [{"href": pce_label["href"]}]
                        })
        
        # Update profile with new labels
        if labels:
            label_update = json.dumps({"labels": labels})
            self.put_requests(profile_details_url, label_update)
            print(f"Default labels assigned to Container Workload Profile in cluster {self.cluster_name.upper()}")

    def get_cluster_labels(self):
        """Get labels for the cluster to be used in pairing profile"""
        label_url = f"{self.base_url}/labels"
        labels = self.get_requests(label_url)
        cluster_label_href = ""
        for label in labels:
            if label.get("key") == "cluster" and label.get("value") == self.cluster_name:
                cluster_label_href = label["href"]
                break
        
        if not cluster_label_href:
            return ""
        
        return json.dumps({"href": cluster_label_href})

    def create_pairing_profile(self):
        """Create a pairing profile for the cluster"""
        pairing_profile_url = f"{self.base_url}/pairing_profiles"
        
        # Get all labels for the cluster
        labels = self.get_labels()
        
        # If no labels were found, use just the cluster label
        if not labels:
            cluster_label = self.get_cluster_labels()
            labels = [json.loads(cluster_label)] if cluster_label else []
        
        pairing_profile_data = {
            "name": self.cluster_name,
            "enforcement_mode": "visibility_only",
            "enabled": True,
            "key_lifespan": "unlimited",
            "allowed_uses_per_key": "unlimited",
            "log_traffic": False,
            "visibility_level": "flow_summary",
            "ven_type": "server",
            "env_label_lock": True,
            "loc_label_lock": True,
            "role_label_lock": True,
            "app_label_lock": True,
            "enforcement_mode_lock": True,
            "log_traffic_lock": True,
            "visibility_level_lock": True,
            "labels": labels
        }
        
        pairing_profile_details = self.post_requests(pairing_profile_url, json.dumps(pairing_profile_data))
        self.pairing_profile_id = pairing_profile_details["href"].split('/', 4)[-1]
        print(f"Pairing Profile {self.cluster_name.upper()} created.")
        return pairing_profile_details

    def create_pairing_key(self):
        """Create a pairing key for the pairing profile"""
        if not self.pairing_profile_id:
            raise Exception("Pairing profile ID is required to create a pairing key")
            
        key_gen_url = f"{self.base_url}/pairing_profiles/{self.pairing_profile_id}/pairing_key"
        data = '{}'
        pairing_key_details = self.post_requests(key_gen_url, data)
        self.pairing_key = pairing_key_details.get("activation_code", "")
        print(f"Pairing key for {self.cluster_name.upper()} created.")
        return pairing_key_details

    def store_illumio_install_secrets(self):
        """Store the container cluster token, ID, and pairing key in a file and vault"""
        # Create a JSON structure to hold the data
        secrets_data = {
            f"{self.cluster_name}_container_cluster_token": self.container_cluster_token,
            f"{self.cluster_name}_container_cluster_id": self.container_cluster_id,
            f"{self.cluster_name}_pairing_key": self.pairing_key
        }
        
        # Save to file
        secrets_file = f"/tmp/illumio_{self.cluster_name}_secrets.json"
        success, message = ejfile.write_generic_text(json.dumps(secrets_data, indent=4), secrets_file)
        if not success:
            raise Exception(f"Failed to write secrets to file: {message}")
            
        print(f"Saved cluster secrets to {secrets_file}")
        
        # Call ejvault to store secrets
        try:
            success = ejvault.store_illumio_install_secrets(
                self.container_cluster_token, 
                self.container_cluster_id, 
                self.pairing_key,
                self.cluster_name
            )
            if not success:
                raise Exception("Failed to store secrets in vault")
        except AttributeError:
            print("Warning: ejvault.store_illumio_install_secrets function not found. Secrets were only saved to file.")
            return True
            
        print(f"Successfully stored cluster secrets in vault for {self.cluster_name}")
        return True

    def run(self):
        """Run the Illumio cluster manager workflow"""
        if self.check_cluster_exists():
            print(f"Cluster {self.cluster_name} already exists.")
            # Get profiles for the existing cluster
            profile_url = f"{self.base_url}/container_clusters/{self.container_cluster_id}/container_workload_profiles"
            profile_answer = self.get_requests(profile_url)
            
            # Apply labels
            label_url = f"{self.base_url}/labels"
            label_answer = self.get_requests(label_url)
            
            # Assign namespace and default labels to profiles
            for item in profile_answer:
                namespace = item.get("namespace")
                if namespace:
                    self.assign_namespace_labels(item, label_answer)
                else:
                    self.assign_default_labels(item)
        else:
            # Create cluster label
            self.create_cluster_label()
            
            # Create container cluster
            cluster_details = self.create_container_cluster()
            
            # Create pairing profile with all appropriate labels
            pairing_profile_details = self.create_pairing_profile()
            
            # Create pairing key
            pairing_key_details = self.create_pairing_key()
            
            # Store the secrets
            self.store_illumio_install_secrets()
            
            # Get profiles for the cluster
            profile_url = f"{self.base_url}/container_clusters/{self.container_cluster_id}/container_workload_profiles"
            profile_answer = self.get_requests(profile_url)
            
            # Apply labels
            label_url = f"{self.base_url}/labels"
            label_answer = self.get_requests(label_url)
            
            # Assign namespace and default labels to profiles
            for item in profile_answer:
                namespace = item.get("namespace")
                if namespace:
                    self.assign_namespace_labels(item, label_answer)
                else:
                    self.assign_default_labels(item)
 
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
            universal_newlines=True  # Use this instead of text=True for Python 3.6
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
 
def docker_command(cmd):
    """Run a docker command and handle errors."""
    try:
        print(f"Executing: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
 
def process_images(values_file, new_registry):
    """Reads values.yaml, pulls images, retags them, and pushes to the new registry."""
    yaml = ruamel.yaml.YAML(typ="safe")  # Use safe mode to preserve structure
 
    # Read values.yaml
    with open(values_file, 'r') as file:
        values = yaml.load(file)
 
    if not values:
        print("Error: values.yaml is empty or invalid.")
        return
 
    # Recursive function to process images in nested structures
    def process_entries(obj):
        if isinstance(obj, dict):
            if all(key in obj for key in ["registry", "repo", "imageTag"]):
                old_image = f"{obj['registry']}/{obj['repo']}:{obj['imageTag']}"
                new_image = f"{new_registry}/{obj['repo']}:{obj['imageTag']}"
 
                print(f"\nProcessing Image: {old_image} → {new_image}")
 
                # Pull, Tag, and Push the image
                docker_command(["docker", "pull", old_image])
                docker_command(["docker", "tag", old_image, new_image])
                docker_command(["docker", "push", new_image])
 
            # Process nested dictionaries
            for key in obj:
                process_entries(obj[key])
        elif isinstance(obj, list):
            for item in obj:
                process_entries(item)
 
    process_entries(values)
 
def update_registry_names(file_path, new_registry):
    """
    Updates only the registry name in all occurrences within the values.yaml file.
 
    """
    yaml = ruamel.yaml.YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
 
    try:
        # Read the existing values.yaml file
        with open(file_path, 'r') as file:
            values = yaml.load(file)
 
        if values is None:
            raise ValueError("The values.yaml file is empty or invalid.")
 
        # Recursive function to update registry values
        def update_registry(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if isinstance(value, str) and "/" in value:
                        # Replace only the registry part before the first '/'
                        obj[key] = re.sub(r'^[^/]+', new_registry, value, count=1)
                    elif isinstance(value, (dict, list)):
                        update_registry(value)
            elif isinstance(obj, list):
                for i in range(len(obj)):
                    update_registry(obj[i])
 
        # Update registry values
        update_registry(values)
 
        # Write back to values.yaml without sorting, keeping comments & formatting
        with open(file_path, 'w') as file:
            yaml.dump(values, file)
 
        print(f"Updated registry in {file_path} successfully.")
    except Exception as e:
        print(f"Error updating values.yaml: {e}")
 
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
            universal_newlines=True  # Use this instead of text=True for Python 3.6
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
            universal_newlines=True  # Use this instead of text=True for Python 3.6
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
    """Parse arguments and run Illumio cluster manager and/or install Helm chart."""
    parser = argparse.ArgumentParser(description='Manage Illumio clusters and install Helm chart')
    parser.add_argument('--cluster-name', '--cluster', '-c', required=True, help='Name of the Kubernetes cluster')
    parser.add_argument('--chart-path', default='.', help='Path to the Helm chart directory')
    parser.add_argument('--namespace', default='illumio-system', help='Kubernetes namespace')
    parser.add_argument('--values-file', default='values.yaml', help='Path to values.yaml file')
    parser.add_argument('--release-name', default='illumio', help='Helm release name')
    parser.add_argument('--registry', default='registry.access.redhat.com/ubi9', help='Container registry')
    parser.add_argument('--create-namespace', action='store_true', help='Create namespace if it does not exist')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--install-only', action='store_true', help='Only install Helm chart without managing cluster')
    parser.add_argument('--manage-only', action='store_true', help='Only manage cluster without installing Helm chart')
   
    args = parser.parse_args()
    
    # Default behavior is to run both actions
    run_cluster_manager = not args.install_only
    run_helm_install = not args.manage_only
    
    # Handle the case where both flags are set
    if args.install_only and args.manage_only:
        print("Error: Cannot specify both --install-only and --manage-only")
        sys.exit(1)
   
    # Check if kubectl is installed when needed
    if run_helm_install:
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
   
    # Run Illumio cluster manager if needed
    if run_cluster_manager:
        print(f"=== Managing Illumio Cluster: {args.cluster_name} ===")
        manager = IllumioClusterManager(args.cluster_name)
        manager.run()
   
    # Process images and update registry names if installing
    if run_helm_install:
        print(f"=== Processing images for registry: {args.registry} ===")
        process_images(args.values_file, args.registry)
        update_registry_names(args.values_file, args.registry)
   
        # Install Illumio Helm chart
        print(f"=== Installing Illumio Helm Chart in Cluster: {args.cluster_name} ===")
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
    else:
        print("="*80)
        print(f"Illumio cluster {args.cluster_name} management completed")
        print("="*80)
        sys.exit(0)
 
if __name__ == "__main__":
    main()