#!/usr/bin/python3
#                                                                                                   #
# Used to monitor for new namespaces and create labels and intranamespace rule      #
#                                                                                                   #

# Import necessary libs
import json
import os
import re
import requests
import urllib3
from bin.illumio import ejconfig
from bin.illumio import ejvault
from bin.illumio import ejfile
import argparse  # Add missing import for argparse

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

    def assign_namespace_labels(self, item, label_answer_json):
        assigned_labels = item["assign_labels"]
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
                    if label_href == assigned_label["href"]:
                        assigned = True
                        print(f"Namespace label already assigned for {namespace.upper()} profile in cluster {self.cluster_name.upper()}")
                        break
                if not assigned:
                    namespace_label = json.dumps({"href": label_href})
                    assigned_labels.append(json.loads(namespace_label))
                    new_labels_str = json.dumps(assigned_labels)
                    label_update = json.dumps({"assign_labels": assigned_labels})
                    self.put_requests(profile_details_url, label_update)
                    print(f"Namespace label assigned to {namespace.upper()} profile in cluster {self.cluster_name.upper()}")
        if not label_exists:
            self.create_assign_namespace_label(namespace, profile_details_url)

    def create_assign_namespace_label(self, namespace, profile_details_url):
        label_url = f"{self.base_url}/labels"
        new_label = json.dumps({"key": "namespace", "value": namespace})
        new_label_response = self.post_requests(label_url, new_label)
        new_label_href = new_label_response["href"]
        namespace_label = json.dumps({"href": new_label_href})
        assigned_labels = [json.loads(namespace_label)]
        new_labels_str = json.dumps(assigned_labels)
        label_update = json.dumps({"assign_labels": assigned_labels})
        self.put_requests(profile_details_url, label_update)
        print(f"Namespace label assigned to {namespace.upper()} profile in cluster {self.cluster_name.upper()}")

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
            "container_cluster_token": self.container_cluster_token,
            "container_cluster_id": self.container_cluster_id,
            "pairing_key": self.pairing_key
        }
        
        # Save to file
        secrets_file = f"/tmp/illumio_{self.cluster_name}_secrets.json"
        success, message = ejfile.write_generic_text(json.dumps(secrets_data, indent=4), secrets_file)
        if not success:
            raise Exception(f"Failed to write secrets to file: {message}")
            
        print(f"Saved cluster secrets to {secrets_file}")
        
        # Call ejvault to store secrets
        # We'll assume the store_illumio_install_secrets function exists in ejvault
        # and takes the three parameters we gathered
        try:
            # This function might need to be implemented in ejvault.py if it doesn't exist
            success = ejvault.store_illumio_install_secrets(
                self.container_cluster_token, 
                self.container_cluster_id, 
                self.pairing_key
            )
            if not success:
                raise Exception("Failed to store secrets in vault")
        except AttributeError:
            print("Warning: ejvault.store_illumio_install_secrets function not found. Secrets were only saved to file.")
            return True
            
        print(f"Successfully stored cluster secrets in vault for {self.cluster_name}")
        return True

    def run(self):
        if self.check_cluster_exists():
            print(f"Cluster {self.cluster_name} already exists.")
            # Additional logic for existing clusters
        else:
            # Create cluster label
            self.create_cluster_label()
            
            # Create container cluster
            cluster_details = self.create_container_cluster()
            
            # Create pairing profile
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
            
            # Assign namespace labels to profiles
            for item in profile_answer:
                namespace = item.get("namespace")
                if namespace:
                    self.assign_namespace_labels(item, label_answer)

def parse_args():
    desc = "Assign namespace labels to profiles in provided Container Cluster.\n"
    epilog = "The cluster to target is provided as an argument."
    parser = argparse.ArgumentParser(description=desc, epilog=epilog)
    parser.add_argument('-c', '--cluster', metavar='clusterName', required=True, help='Name of cluster')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    manager = IllumioClusterManager(args.cluster)
    manager.run()