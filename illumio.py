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
import argparse  # Add missing import for argparse

class IllumioClusterManager:
    def __init__(self, cluster_name):
        self.cluster_name = cluster_name
        self.org = ejconfig.org_id
        self.container_cluster_id = ""
        self.container_workload_profile_id = ""
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
        print(f"Container Cluster {self.cluster_name.upper()} created.")

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

    def run(self):
        if self.check_cluster_exists():
            print(f"Cluster {self.cluster_name} already exists.")
            # Additional logic for existing clusters
        else:
            self.create_cluster_label()
            self.create_container_cluster()
            # Additional logic for new clusters

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