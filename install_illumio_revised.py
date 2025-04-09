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
import time

class IllumioClusterManager:
    def __init__(self, cluster_name, env=None):
        self.cluster_name = cluster_name
        self.env = env
        self.org = ejconfig.org_id
        self.container_cluster_id = ""
        self.container_workload_profile_id = ""
        self.container_cluster_token = ""
        self.pairing_profile_id = ""
        self.pairing_key = ""
        self.user, self.key = self.get_pce_secrets()
        self.base_url = f"https://us-scp14.illum.io/api/v2/orgs/{self.org}"

    def get_pce_secrets(self):
        success, user, key = ejvault.get_pce_secrets(self.env)
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
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        proxies = {'http': None, 'https': None}
        auth = (self.user, self.key)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.post(url, timeout=15, verify=False, headers=headers, proxies=proxies, auth=auth, data=data)
        if response.status_code == 406:
            print(f"Error creating resource. Response: {response.text}")
            raise Exception(f"Failed to create resource: {response.text}")
        response.raise_for_status()
        return response.json()

    def put_requests(self, url, data):
        headers = {'Content-Type': 'application/json'}
        proxies = {'http': None, 'https': None}
        auth = (self.user, self.key)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.put(url, timeout=15, verify=False, headers=headers, proxies=proxies, auth=auth, data=data)
        response.raise_for_status()
        # Return None for empty responses (204 No Content)
        if response.status_code == 204:
            return None
        return response.json()

    def check_cluster_exists(self):
        """
        Check if cluster exists in PCE, or if pairing profile or vault secrets exist.
        Sets appropriate IDs if found and returns True if any exist.
        """
        # Check if cluster exists in container_clusters
        cluster_exists = False
        cluster_url = f"{self.base_url}/container_clusters"
        print(f"Checking if cluster {self.cluster_name} exists in PCE...")
        try:
            clusters = self.get_requests(cluster_url)
            for cluster in clusters:
                if cluster.get("name") == self.cluster_name:
                    self.container_cluster_id = cluster["href"].split('/', 4)[-1]
                    cluster_exists = True
                    print(f"Found existing cluster {self.cluster_name} in PCE container clusters")
                    print(f"Container cluster ID: {self.container_cluster_id}")
                    
                    # Also get the token if available
                    self.container_cluster_token = cluster.get("container_cluster_token", "")
                    if self.container_cluster_token:
                        print("Retrieved container cluster token from PCE")
                    break
        except Exception as e:
            print(f"Error checking if cluster exists in PCE: {str(e)}")
        
        # Check if pairing profile exists
        pairing_exists = False
        pairing_url = f"{self.base_url}/pairing_profiles"
        try:
            pairing_profiles = self.get_requests(pairing_url)
            for profile in pairing_profiles:
                if profile.get("name") == self.cluster_name:
                    self.pairing_profile_id = profile["href"].split('/', 4)[-1]
                    pairing_exists = True
                    print(f"Found existing pairing profile for {self.cluster_name}")
                    
                    # Try to get a pairing key for this profile if we don't have one
                    if not self.pairing_key and self.pairing_profile_id:
                        try:
                            self.create_pairing_key()
                        except Exception as e:
                            print(f"Could not create pairing key: {str(e)}")
                    break
        except Exception as e:
            print(f"Error checking for pairing profile: {str(e)}")
        
        # Check if vault secrets exist - prioritize these values if found
        secrets_exist = False
        try:
            # Use the retrieve_cluster_secrets function from ejvault
            container_cluster_id, container_cluster_token, pairing_key = ejvault.retrieve_cluster_secrets(self.cluster_name, self.env)
            if container_cluster_id:
                self.container_cluster_id = container_cluster_id
                secrets_exist = True
                print(f"Found existing container_cluster_id in vault for {self.cluster_name}: {container_cluster_id}")
            
            if container_cluster_token:
                self.container_cluster_token = container_cluster_token
                secrets_exist = True
                print(f"Found existing container_cluster_token in vault for {self.cluster_name}")
            
            if pairing_key:
                self.pairing_key = pairing_key
                secrets_exist = True
                print(f"Found existing pairing_key in vault for {self.cluster_name}")
        except Exception as e:
            print(f"Error checking for vault secrets: {str(e)}")
        
        # Return True if any of these exist
        exists = cluster_exists or pairing_exists or secrets_exist
        
        # Ensure integrity of data if cluster exists
        if exists and not self.container_cluster_id:
            print("WARNING: Cluster exists but container_cluster_id is not set. Will attempt to create a new cluster.")
            exists = False
            
        return exists

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
        profile_href = item["href"]
        self.container_workload_profile_id = profile_href.split('/', 6)[-1]
        profile_details_url = f"{self.base_url}/container_clusters/{self.container_cluster_id}/container_workload_profiles/{self.container_workload_profile_id}"
        namespace = item["namespace"]

        print(f"Processing namespace label for namespace: {namespace}")
        
        # First get the current state of the container workload profile
        try:
            current_profile = self.get_requests(profile_details_url)
            print(f"Current profile: {json.dumps(current_profile, indent=2)}")
            
            # Find the namespace label in available labels
            namespace_label_href = None
            for label in label_answer_json:
                if label.get("key") == "namespace" and label.get("value") == namespace:
                    namespace_label_href = label["href"]
                    print(f"Found namespace label {namespace} with href {namespace_label_href}")
                    break
            
            if not namespace_label_href:
                # Create the namespace label if it doesn't exist
                print(f"Creating namespace label for {namespace}")
                namespace_label = self.create_namespace_label(namespace)
                namespace_label_href = namespace_label["href"]
            
            # Construct the update
            # Use a minimal update approach - only set enforcement_mode and managed status first
            update_data = {
                "managed": True,
                "enforcement_mode": "visibility_only"
            }
            
            # Apply the update in stages - first set managed status
            print(f"Setting profile to managed with: {json.dumps(update_data)}")
            self.put_requests(profile_details_url, json.dumps(update_data))
            
            # Now get the profile again after the first update
            current_profile = self.get_requests(profile_details_url)
            
            # Create a new update with assign_labels
            assign_labels = []
            
            # Keep any existing labels that don't conflict
            if "assign_labels" in current_profile and isinstance(current_profile["assign_labels"], list):
                # Check if the namespace label is already assigned
                namespace_already_assigned = False
                for label in current_profile["assign_labels"]:
                    if label.get("href") == namespace_label_href:
                        namespace_already_assigned = True
                        print(f"Namespace label already assigned for {namespace}")
                        break
                
                # If not already assigned, add it to existing labels
                if not namespace_already_assigned:
                    assign_labels = current_profile["assign_labels"].copy()
                    assign_labels.append({"href": namespace_label_href})
                else:
                    # Already assigned, nothing to do
                    print(f"Namespace label for {namespace} already assigned, no update needed")
                    return
            else:
                # No existing labels, just add the namespace label
                assign_labels = [{"href": namespace_label_href}]
            
            # Create a new update with just assign_labels
            update_data = {"assign_labels": assign_labels}
            
            # Apply the second update with assign_labels
            print(f"Assigning namespace label with: {json.dumps(update_data)}")
            result = self.put_requests(profile_details_url, json.dumps(update_data))
            print(f"Label assignment result: {result}")
            print(f"Successfully assigned namespace label {namespace} to profile")
            
        except Exception as e:
            print(f"Error assigning namespace label: {str(e)}")
            print(f"Profile URL: {profile_details_url}")
            print(f"Will continue processing other profiles")
    
    def create_namespace_label(self, namespace):
        """Create a namespace label"""
        label_url = f"{self.base_url}/labels"
        new_label = json.dumps({"key": "namespace", "value": namespace})
        print(f"Creating new namespace label with data: {new_label}")
        try:
            new_label_response = self.post_requests(label_url, new_label)
            print(f"Created new namespace label: {json.dumps(new_label_response, indent=2)}")
            return new_label_response
        except Exception as e:
            print(f"Error creating namespace label: {str(e)}")
            raise

    def create_assign_namespace_label(self, namespace, profile_details_url):
        """Create and assign a namespace label to a container workload profile"""
        try:
            # Create the namespace label
            new_label_response = self.create_namespace_label(namespace)
            new_label_href = new_label_response["href"]
            
            # First get the current profile to ensure we have the latest state
            current_profile = self.get_requests(profile_details_url)
            
            # Set the profile to managed first
            update_data = {
                "managed": True,
                "enforcement_mode": "visibility_only"
            }
            print(f"Setting profile to managed with: {json.dumps(update_data)}")
            self.put_requests(profile_details_url, json.dumps(update_data))
            
            # Now get the profile again
            current_profile = self.get_requests(profile_details_url)
            assigned_labels = current_profile.get("assign_labels", [])
            
            # Add the new label to any existing assigned labels
            new_assigned_labels = assigned_labels.copy()
            new_assigned_labels.append({"href": new_label_href})
            
            # Format the request properly - just assign_labels
            label_update = json.dumps({"assign_labels": new_assigned_labels})
            print(f"Updating profile with assign_labels: {label_update}")
            
            # Make the PUT request
            result = self.put_requests(profile_details_url, label_update)
            print(f"Label assignment result: {result}")
            print(f"Namespace label created and assigned to {namespace.upper()} profile in cluster {self.cluster_name.upper()}")
        except Exception as e:
            print(f"Error creating and assigning namespace label: {str(e)}")
            print(f"Profile URL: {profile_details_url}")
            print(f"Namespace: {namespace}")

    def assign_default_labels(self, item):
        """Assign default labels to container workload profiles"""
        profile_href = item["href"]
        self.container_workload_profile_id = profile_href.split('/', 6)[-1]
        profile_details_url = f"{self.base_url}/container_clusters/{self.container_cluster_id}/container_workload_profiles/{self.container_workload_profile_id}"
        
        print(f"Processing default labels for profile: {self.container_workload_profile_id}")
        
        try:
            # Get current profile state
            profile = self.get_requests(profile_details_url)
            print(f"Current profile state: {json.dumps(profile, indent=2)}")
            
            # First step: Set the profile to managed with visibility_only enforcement
            if not profile.get("managed", False) or profile.get("enforcement_mode") != "visibility_only":
                update_data = {
                    "managed": True,
                    "enforcement_mode": "visibility_only"
                }
                print(f"Setting profile to MANAGED and enforcement mode to VISIBILITY ONLY")
                self.put_requests(profile_details_url, json.dumps(update_data))
                print("Profile set to managed state successfully")
                
                # Get updated profile
                profile = self.get_requests(profile_details_url)
            else:
                print("Profile already in managed state with visibility_only enforcement")
            
            # Second step: Get all available labels
            label_url = f"{self.base_url}/labels"
            label_answer = self.get_requests(label_url)
            
            # Prepare default labels to assign
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
            
            # Update profile with the label restrictions
            if labels:
                label_update = json.dumps({"labels": labels})
                print(f"Updating profile with default label restrictions: {label_update}")
                result = self.put_requests(profile_details_url, json.dumps({"labels": labels}))
                print(f"Default labels assigned to Container Workload Profile in cluster {self.cluster_name.upper()}")
                print(f"Label assignment result: {result}")
            else:
                print("No default labels found to assign")
                
        except Exception as e:
            print(f"Warning: Could not assign default labels: {str(e)}")
            print(f"Profile URL: {profile_details_url}")

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
        
        # Ensure labels are properly formatted
        formatted_labels = []
        for label in labels:
            if isinstance(label, str):
                formatted_labels.append({"href": label})
            elif isinstance(label, dict):
                formatted_labels.append(label)
        
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
            "labels": formatted_labels
        }
        
        try:
            pairing_profile_details = self.post_requests(pairing_profile_url, json.dumps(pairing_profile_data))
            self.pairing_profile_id = pairing_profile_details["href"].split('/', 4)[-1]
            print(f"Pairing Profile {self.cluster_name.upper()} created.")
            return pairing_profile_details
        except Exception as e:
            print(f"Error creating pairing profile: {str(e)}")
            raise

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
        """Store the cluster secrets in vault"""
        try:
            success = ejvault.store_illumio_install_secrets(
                self.container_cluster_token, 
                self.container_cluster_id, 
                self.pairing_key, 
                self.cluster_name,
                self.env
            )
            if not success:
                raise Exception("Failed to store secrets in vault")
            print(f"Successfully stored secrets in vault for {self.cluster_name}")
            return True
        except Exception as e:
            print(f"Error storing secrets: {str(e)}")
            return False

    def run(self):
        """
        Main method to run the cluster management process.
        This will check if the cluster exists, create it if not,
        and create pairing profile and pairing key.
        """
        exists = self.check_cluster_exists()
        if exists:
            print(f"Cluster {self.cluster_name} or its related resources already exist")
            if not self.container_cluster_id:
                print("Container cluster ID not found, creating new cluster")
                self.create_container_cluster()
        else:
            print(f"Creating new cluster resources for {self.cluster_name}")
            self.create_cluster_label()
            self.create_container_cluster()
            self.create_pairing_profile()
            
        # Create pairing key if needed
        if not self.pairing_key:
            self.create_pairing_key()
            
        # Store secrets in vault
        self.store_illumio_install_secrets()
        
        # Print the cluster details
        print(f"\nCluster {self.cluster_name} details:")
        print(f"Container Cluster ID: {self.container_cluster_id}")
        print(f"Container Cluster Token: {self.container_cluster_token}")
        print(f"Pairing Key: {self.pairing_key}")
        
        return True

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
 
def cleanup_failed_installation(release_name, namespace):
    """
    Clean up a failed Helm installation.
    
    Args:
        release_name (str): Name of the Helm release to clean up
        namespace (str): Kubernetes namespace of the release
        
    Returns:
        bool: True if cleanup was successful, False otherwise
    """
    try:
        print(f"Cleaning up failed installation of release '{release_name}' in namespace '{namespace}'...")
        
        # Check if release exists and is in failed state
        status_check = subprocess.run(
            ["helm", "status", release_name, "-n", namespace],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            universal_newlines=True
        )
        
        # If status command succeeds, we need to uninstall
        if status_check.returncode == 0:
            print(f"Found release '{release_name}' in failed state, uninstalling...")
            uninstall_cmd = [
                "helm", "uninstall", release_name,
                "-n", namespace,
                "--wait"  # Wait for resources to be deleted
            ]
            
            uninstall_process = subprocess.run(
                uninstall_cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            print(f"Successfully cleaned up failed release '{release_name}'")
        else:
            # Release might be in a state where helm status doesn't work
            # Try uninstall with --no-hooks to force removal
            try:
                uninstall_cmd = [
                    "helm", "uninstall", release_name,
                    "-n", namespace,
                    "--no-hooks"  # Skip running hooks to avoid errors
                ]
                
                uninstall_process = subprocess.run(
                    uninstall_cmd,
                    check=False,  # Don't fail if uninstall fails
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True
                )
                print(f"Attempted force cleanup of release '{release_name}'")
            except Exception as e:
                print(f"Warning: Force cleanup attempt failed: {str(e)}")
        
        # Give Kubernetes some time to clean up resources
        print("Waiting for Kubernetes to clean up resources...")
        time.sleep(10)
        return True
        
    except Exception as e:
        print(f"Error during cleanup: {str(e)}")
        return False

def install_illumio_helm_chart(cluster_name, chart_path='.', namespace='illumio-system',
                              values_file='values.yaml', release_name='illumio',
                              registry='registry.access.redhat.com/ubi9',
                              create_namespace=False, debug=False, max_retries=3, env=None):
    """
    Install Illumio Helm chart with the specified parameters.
    
    Args:
        cluster_name (str): Name of the Kubernetes cluster
        chart_path (str): Path to the Helm chart
        namespace (str): Kubernetes namespace
        values_file (str): Path to values.yaml file
        release_name (str): Helm release name
        registry (str): Container registry
        create_namespace (bool): Create namespace if it doesn't exist
        debug (bool): Enable debug output
        max_retries (int): Maximum number of installation retries
        env (str): Environment (dev, test, stg, prod)
        
    Returns:
        bool: True if installation was successful, False otherwise
    """
    # First, retrieve secrets from Vault using ejvault
    container_cluster_id, container_cluster_token, pairing_key = ejvault.retrieve_cluster_secrets(cluster_name, env)
    
    if not all([container_cluster_id, container_cluster_token, pairing_key]):
        print(f"Failed to retrieve required secrets for cluster {cluster_name}")
        return False
    
    print(f"Retrieved cluster secrets for {cluster_name} from Vault")
    
    # Set up namespace if needed
    if create_namespace:
        print(f"Creating namespace {namespace} if it doesn't exist")
        try:
            subprocess.run(
                ["kubectl", "create", "namespace", namespace, "--dry-run=client", "-o", "yaml"], 
                check=True, 
                stdout=subprocess.PIPE
            ).stdout.decode('utf-8')
            
            result = subprocess.run(
                ["kubectl", "apply", "-f", "-"],
                input=subprocess.run(
                    ["kubectl", "create", "namespace", namespace, "--dry-run=client", "-o", "yaml"], 
                    check=True, 
                    stdout=subprocess.PIPE
                ).stdout,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            print(f"Namespace {namespace} ready")
        except subprocess.CalledProcessError as e:
            print(f"Error creating namespace: {str(e)}")
            print(f"Stderr: {e.stderr.decode('utf-8') if e.stderr else 'None'}")
            print(f"Stdout: {e.stdout.decode('utf-8') if e.stdout else 'None'}")
            return False
    
    # Check that we have access to the namespace
    try:
        subprocess.run(
            ["kubectl", "auth", "can-i", "create", "pods", "-n", namespace],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print(f"Confirmed access to namespace {namespace}")
    except subprocess.CalledProcessError as e:
        print(f"Error checking namespace access: {str(e)}")
        print(f"Stderr: {e.stderr.decode('utf-8') if e.stderr else 'None'}")
        print(f"Stdout: {e.stdout.decode('utf-8') if e.stdout else 'None'}")
        return False
    
    # Build the helm install command
    helm_cmd = [
        "helm", "install", release_name, chart_path,
        "--namespace", namespace,
        "--set", f"cluster_id={container_cluster_id}",
        "--set", f"cluster_token={container_cluster_token}",
        "--set", f"cluster_code={pairing_key}",
        "--set", f"registry={registry}",
        "-f", values_file
    ]
    
    if debug:
        helm_cmd.append("--debug")
    
    # Try to install the chart
    retries = 0
    success = False
    while retries < max_retries and not success:
        try:
            if retries > 0:
                print(f"Retry {retries}/{max_retries}...")
                # Clean up from previous attempt
                cleanup_failed_installation(release_name, namespace)
                time.sleep(5)  # Wait a bit before retrying
            
            print(f"Installing Illumio Helm chart with command: {' '.join(helm_cmd)}")
            result = subprocess.run(
                helm_cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            print("Helm install command executed successfully")
            
            # Wait for pods to start
            print("Waiting for pods to start...")
            time.sleep(30)
            
            # Check pod status
            pod_status = subprocess.run(
                ["kubectl", "get", "pods", "-n", namespace, "-l", f"app.kubernetes.io/instance={release_name}", "-o", "json"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            pod_json = json.loads(pod_status.stdout)
            pods_ready = True
            for pod in pod_json.get("items", []):
                pod_name = pod.get("metadata", {}).get("name", "unknown")
                pod_phase = pod.get("status", {}).get("phase", "Unknown")
                print(f"Pod {pod_name} is in phase {pod_phase}")
                if pod_phase not in ["Running", "Succeeded"]:
                    pods_ready = False
            
            if pods_ready:
                print("All pods are running or completed successfully")
                success = True
                
                # Following the requirement: Assign namespace and default labels to profiles after successful helm installation
                # Get the cluster manager instance to perform label assignment
                manager = IllumioClusterManager(cluster_name, env)
                
                # Ensure the cluster manager has the correct container_cluster_id
                # This fixes the issue when the cluster already exists
                if not manager.container_cluster_id and container_cluster_id:
                    print(f"Setting container_cluster_id to {container_cluster_id}")
                    manager.container_cluster_id = container_cluster_id
                
                # Verify we have a valid container_cluster_id before proceeding
                if not manager.container_cluster_id:
                    print("Error: container_cluster_id is empty. Cannot assign labels.")
                    print("The cluster exists but couldn't be properly identified.")
                    return True  # Return True since the installation itself was successful

                print(f"Using container_cluster_id: {manager.container_cluster_id}")
                
                # Get profile and label answers
                try:
                    profile_url = f"{manager.base_url}/container_clusters/{manager.container_cluster_id}/container_workload_profiles"
                    print(f"Retrieving container workload profiles using URL: {profile_url}")
                    profile_answer = manager.get_requests(profile_url)
                    label_answer = manager.get_requests(f"{manager.base_url}/labels")
                    
                    # Assign namespace and default labels to profiles
                    for item in profile_answer:
                        namespace = item.get("namespace")
                        if namespace:
                            manager.assign_namespace_labels(item, label_answer)
                        manager.assign_default_labels(item)
                    
                    print("Assigned namespace and default labels to profiles after successful installation")
                except Exception as e:
                    print(f"Warning: Failed to assign labels: {str(e)}")
                    print("Continuing with installation as successful, but labels were not assigned")
                
                return True
            else:
                print("Not all pods are ready yet, will retry...")
                retries += 1
                
        except subprocess.CalledProcessError as e:
            print(f"Error installing Helm chart: {str(e)}")
            print(f"Stderr: {e.stderr if e.stderr else 'None'}")
            print(f"Stdout: {e.stdout if e.stdout else 'None'}")
            retries += 1
    
    if not success:
        print(f"Failed to install Illumio Helm chart after {max_retries} attempts")
        return False
    
    return success

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
    parser.add_argument('--env', choices=['dev', 'test', 'stg', 'prod'], help='Environment to use (dev, test, stg, prod)')
    
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
   
        # Ensure values file exists - check both absolute and relative paths
        values_path = args.values_file
        if not os.path.isabs(values_path):
            # Try current directory first
            if os.path.isfile(values_path):
                values_path = os.path.abspath(values_path)
            # Then try relative to chart path
            elif os.path.isfile(os.path.join(args.chart_path, values_path)):
                values_path = os.path.abspath(os.path.join(args.chart_path, values_path))
            else:
                print(f"Error: Values file '{args.values_file}' not found in current directory or chart path '{args.chart_path}'")
                print(f"Please ensure values.yaml exists in one of these locations:")
                print(f"1. Current directory: {os.getcwd()}")
                print(f"2. Chart directory: {os.path.abspath(args.chart_path)}")
                sys.exit(1)
        elif not os.path.isfile(values_path):
            print(f"Error: Values file not found at absolute path: {values_path}")
            sys.exit(1)
        
        # Update args.values_file with the verified path
        args.values_file = values_path
   
    # Run Illumio cluster manager if needed
    if run_cluster_manager:
        print(f"=== Managing Illumio Cluster: {args.cluster_name} ===")
        manager = IllumioClusterManager(args.cluster_name, args.env)
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
            args.debug,
            env=args.env
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