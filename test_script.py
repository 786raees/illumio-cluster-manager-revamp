#!/usr/bin/python3
#                                                                                                   #
# Used to monitor for new namespaces and create labels and intranamespace rule      #
#                                                                                                   #

# Import necessary libs
import argparse
import json
import os
import re
import requests
import urllib3
from bin.illumio import ejconfig
from bin.illumio import ejvault


def parse_args():

    """
    CLI argument handling
    """
    desc = "Assign namespace labels to profiles in provided Container Cluster.\n"
    epilog = "The cluster to target is provided as an argument. "

    p = argparse.ArgumentParser(description=desc,epilog=epilog)
    p.adargparsent('-c','--cluster',metavar='clusterName',required=True,help='Name of cluster')
    args = p.parse_args()
    return args

 
def main():
    # Get environment
    env = os.environ.get("ENVIRONMENT")

    # Global vars that will be populated below
    args = parse_args()
    cluster_name = args.cluster
    container_role = "Container"
    node_role = "Cluster Node"
    container_cluster_id = ""
    container_workload_profile_id = ""
    org = ejconfig.org_id


    # Defining the URL for listing Container Clusters
    cluster_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/container_clusters"
    policy_version_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/sec_policy"

    temp_success, user, key = ejvault.get_pce_secrets()

    if temp_success:

        # Requesting profile info from PCE.  We will change the response to text and then load it into JSON format so we can iterate through it
        answer_json = get_requests(user, key, cluster_url)

        # As we iterate through each cluster profile, we will retrieve the namespaces or profiles inside the container cluster
        # We will also make a request to get the labels and href for each profile
        #
        # After we have the profile information, we will then request information for every label configured in the PCE
        #
        label_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/labels"
        answer_json = get_requests(user, key, label_url)
        cluster_exists = False
        for item in answer_json:
            name = item["name"]
            if name == cluster_name:
                cluster_exists = True
                base_vault_url = os.environ.get("BASE_VAULT_URL")
                cluster_id, cluster_token, cluster_code = ejvault.get_helm_secrets(cluster_name)
                os.environ["CLUSTER_ID"] = cluster_id
                os.environ["CLUSTER_TOKEN"] = cluster_token
                os.environ["CLUSTER_CODE"] = cluster_code
                #k8s_create()
                #helm_install()
                cluster_href = item["href"]
                container_cluster_id = cluster_href.split('/', 4)[-1]
                profile_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/container_clusters/{container_cluster_id}/container_workload_profiles"
                profile_answer = get_requests(user, key, profile_url)
                for item in profile_answer:
                    namespace = item["namespace"]
                    profile_href = item["href"]
                    container_workload_profile_id = profile_href.split('/', 6)[-1]
                    profile_details_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/container_clusters/{container_cluster_id}/container_workload_profiles/{container_workload_profile_id}"
                    label_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/labels"
                    label_answer = get_requests(user, key, label_url)
                    if namespace != None:
                        assign_namespace_labels(user, key, item, label_answer)

        if cluster_exists == False:

            ## Create a label for the cluster name
            create_cluster_label(user, key, cluster_name)

            ## Create a container cluster
            cluster_details = create_container_cluster(user, key, cluster_name)

            ## Get cluster token and ID
            for item in cluster_details:
                container_cluster_token = item["container_cluster_token"]
                container_cluster_href = item["href"]
                container_cluster_id = container_cluster_href.split('/', 4)[-1]
                profile_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/container_clusters/{container_cluster_id}/container_workload_profiles"
                profile_answer = get_requests(user, key, profile_url)

            ## Apply default labels
            label_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/labels"
            label_answer = get_requests(user, key, label_url)
            for item in profile_answer:
                namespace = item["namespace"]
                profile_href = item["href"]
                container_workload_profile_id = profile_href.split('/', 6)[-1]
                profile_details_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/container_clusters/{container_cluster_id}/container_workload_profiles/{container_workload_profile_id}"
                if namespace != None:
                    assign_namespace_labels(user, key, item, label_answer)
                else:
                    assign_default_labels(user, key, item)
                 
            ## Create pairing profile and key
            pairing_profile_details = create_pairing_profile(user, key, cluster_name)
            for item in pairing_profile_details:
                profile_href = item["href"]
                pairing_profile_id = profile_href.split('/', 4)[-1]
            pairing_key_details = create_pairing_key(user, key, pairing_profile_id)
            for item in pairing_key:
                pairing_key = item["activation_code"]

            ## Save id, token, and code to Vault
            success = ejvault.store_illumio_install_secrets(container_cluster_token, container_cluster_id, pairing_key)

            ## Create Illumio namespace
            #k8s_create()          

            ## Install Helm Chart
            #helm_install()

            ## Apply namespace labels
            label_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/labels"
            label_answer = get_requests(user, key, label_url)
            for item in profile_answer:
                namespace = item["namespace"]
                if namespace != None:
                    assign_namespace_labels(user, key, item, label_answer)

    else:
      print("Could not retrieve API credentials from Vault")

 


def assign_default_labels(user, key, item):
    label = ""
    label_list = ["data", "kubeapi", "metadataapi", "riskscore"]
    assigned_labels = item["assign_labels"]
    labels = item["labels"]
    state = item["managed"]
    if state == False:
        new_state = '{"managed": ' + "true" + ', "enforcement_mode": "visibility_only"}'
        answer_json = put_requests(user, key, profile_details_url, new_state)
        print("Set mode to MANAGED and enforcement mode to VISIBILITY ONLY")
    role_href = ""
    type_href = ""
    env_href = ""
    location_href = ""
    cluster_href = ""
    labels.clear()
    for list_label in label_list:
        if list_label == "data":
            data_label = ""
            for pce_label in label_answer_json:
                label_item_key = pce_label["key"]
                if list_label == label_item_key:
                    label_href = pce_label["href"]
                    label_value = pce_label["value"]
                    if data_label == "":
                        data_label = '{"href": "' + label_href + '"}'
                    else:
                        data_label = data_label + ', {"href": "' + label_href + '"}'
            data_label = '{"key": "' + list_label + '", "restriction": [' + data_label + ']}'
            data_dict = json.loads(data_label)
            labels.append(data_dict)
        elif list_label == "riskscore":
            riskscore_label = ""
            for pce_label in label_answer_json:
                label_item_key = pce_label["key"]
                if list_label == label_item_key:
                    label_href = pce_label["href"]
                    label_value = pce_label["value"]
                    if riskscore_label == "":
                        riskscore_label = '{"href": "' + label_href + '"}'
                    else:
                        riskscore_label = riskscore_label + ', {"href": "' + label_href + '"}'
            riskscore_label = '{"key": "' + list_label + '", "restriction": [' + riskscore_label + ']}'
            risk_dict = json.loads(riskscore_label)
            labels.append(risk_dict)
        else:
            for pce_label in label_answer_json:
                label_item_key = pce_label["key"]
                if list_label == label_item_key:
                  label_key = pce_label["key"]
                  label_href = pce_label["href"]
                  label_value = pce_label["value"]
                  #if label == "":
                  label = '{"key": "' + label_key + '", "restriction": [{"href": "' + label_href + '"}]}'
                  label_dict = json.loads(label)
                  labels.append(label_dict)
                  #else:
                  #         label = label + ', {"key": "' + label_key + '", "restriction": [{"href": "' + label_href + '"}]}'                  
    labels_str = json.dumps(labels)
    label_update = '{"labels": ' + labels_str + '}'
    answer_json = put_requests(user, key, profile_details_url, label_udpate)
    print("Container Annotation labels updated for DEFAULT profile in cluster " + cluster_name.upper())
    assigned_labels.clear()
    target_env = cluster_name[2:5]
    if target_env == "dev":
        env = "Development"
    elif target_env == "cln" or target_env == "uat":
        env = "Clone"
    elif target_env == "prd":
        env = "Production"
    else:
        target_env = cluster_name[5:6]
        if target_env == 'd':
            env = "Development"
        elif target_env == 'q' or target_env == 'a' or target_env == 'c':
            env = "Clone"
        elif target_env == 'p':
            env = "Production"
    target_location = cluster_name[6:7]
    if target_location == 's':
        location = "Azure South Central US"
    elif target_location == 'n':
        location = "Azure North Central US"
    else:
        location = "Azure Central US"
    if "gtw" in cluster_name:
        cluster_type = "mulesoft"
    else:
        cluster_type = "general"
    for item in label_answer_json:
        if role_href == "" or type_href == "" or env_href == "" or location_href == "" or cluster_href == "":
            label_name = item["value"]
            if label_name == container_role:
                role_href = item["href"]
            if label_name == cluster_type:
                type_href = item["href"]
            if label_name == env:
                env_href = item["href"]
            if label_name == location:
                location_href = item["href"]
            if label_name == cluster_name:
                cluster_href = item["href"]
        else:
            continue
    if cluster_href == "":
        new_label_list = []
        new_label = '{"key": "cluster", "value": "' + cluster_name + '"}'
        answer_json = (user, key, label_url, new_label)
        print("Cluster label " + cluster_name.upper() + " created.")
        new_label_list.append(answer_json)
        for item in new_label_list:
            cluster_href = item["href"]
    role_label = '{"href": "' + role_href + '"}'
    role_dict = json.loads(role_label)
    assigned_labels.append(role_dict)
    type_label = '{"href": "' + type_href + '"}'
    type_dict = json.loads(type_label)
    assigned_labels.append(type_dict)
    environment_label = '{"href": "' + env_href + '"}'
    environment_dict = json.loads(environment_label)
    assigned_labels.append(environment_dict)
    location_label = '{"href": "' + location_href + '"}'
    location_dict = json.loads(location_label)
    assigned_labels.append(location_dict)
    cluster_label = '{"href": "' + cluster_href + '"}'
    cluster_dict = json.loads(cluster_label)
    assigned_labels.append(cluster_dict)
    new_labels_str = json.dumps(assigned_labels)
    label_update = '{"assign_labels": ' + new_labels_str + '}'
    answer_json = put_requests(user, key, profile_details_url, label_update)
    print("Required labels assigned to DEFAULT profile in cluster " + cluster_name.upper())

 

   
def assign_namespace_labels(user, key, item, label_answer_json):

    assigned_labels = item["assign_labels"]
    profile_href = item["href"]
    container_workload_profile_id = profile_href.split('/', 6)[-1]
    profile_details_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/container_clusters/{container_cluster_id}/container_workload_profiles/{container_workload_profile_id}"
    assigned = False
    label_exists = False
    # For each label in the PCE, we will check to see if the value equals the name of the container profile we're working on
    # If so, we will get the href for the label
    # If the href is already in the list of labels assigned to the profile, we will note that it is already assigned
    for item in label_answer_json:
        label_name = item["value"]
        if label_name == namespace:
            label_href = item["href"]
            label_exists = True
            print("Namespace label " + namespace.upper() + " exists.")
            for label in assigned_labels:
                if label_href == label["href"]:
                    assigned = True
                    print("Namespace label already assigned for " + namespace.upper() + " profile in cluster " + cluster_name.upper())
                    print("------------------------------------------------------------------------------------")
            if assigned != True:
                #
                # If the namespace label is not assigned, we will add the href to a string and then to a dictionary, and then dump back to a string
                # This is done so that we get the right formatting for our request body
                # We will then make a PUT request to the console to assign this namespace label to the container profile we are working on
                #
                namespace_label = '{"href": "' + label_href + '"}'
                namespace_dict = json.loads(namespace_label)
                assigned_labels.append(namespace_dict)
                new_labels_str = json.dumps(assigned_labels)
                label_update = '{"assign_labels": ' + new_labels_str + '}'
                answer_json = put_requests(user, key, profile_details_url, label_update)
                print("Namespace label assigned to " + namespace.upper() + " profile in cluster " + cluster_name.upper())
                print("------------------------------------------------------------------------------------")
    #
    # If a label does not exist with a name that matches the namespace name, we will create a new label
    #
    if label_exists != True:

        create_assign_namespace_label(user, key, namespace, profile_details_url)

 
def create_assign_namespace_label(user, key, namespace, profile_details_url):

    new_label_list = []
    new_label = '{"key": "namespace", "value": "' + namespace + '"}'
    label_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/labels"
    answer_json = post_requests(user, key, label_url, new_label)
    print("Namespace label " + namespace.upper() + " created.")
    new_label_list.append(answer_json)
    for item in new_label_list:
        new_label_href = item["href"]
        #
        # After creating the new label, we will get its href from the POST response
        # We will add the href to a string and then to a dictionary, and then dump back to a string
        # This is done so that we get the right formatting for our request body
        # We will then make a PUT request to the console to assign this namespace label to the container profile we are working on
        #
        namespace_label = '{"href": "' + new_label_href + '"}'
        namespace_dict = json.loads(namespace_label)
        assigned_labels.append(namespace_dict)
        new_labels_str = json.dumps(assigned_labels)
        label_update = '{"assign_labels": ' + new_labels_str + '}'
        answer_json = put_requests(user, key, profile_details_url, label_update)
        print("Namespace label assigned to " + namespace.upper() + " profile in cluster " + cluster_name.upper())
        print("------------------------------------------------------------------------------------")

 

def create_cluster_label(user, key, cluster_name):

    new_label = '{"key": "cluster", "value": "' + cluster_name + '"}'
    label_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/labels"
    answer_json = post_requests(user, key, label_url, new_label)
    print("Cluster label " + cluster_name.upper() + " created.")
    return answer_json

       
def create_container_cluster(user, key, cluster_name):

    new_cluster = '{"name": "' + cluster_name + '"}'
    container_cluster_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/container_clusters"
    answer_json = post_requests(user, key, container_cluster_url, new_cluster)
    print("Container Cluster " + cluster_name.upper() + " created.")
    return answer_json

 
def create_pairing_profile(user, key, cluster_name):
    pairing_profile_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/pairing_profiles"
    enforcement_mode = '"enforcement_mode": "visibility_only"'
    enabled = '"enabled": true'
    key_lifespan = '"key_lifespan": "unlimited"'
    allowed_uses_per_key = '"allowed_uses_per_key": "unlimited"'
    log_traffic = '"log_traffic": false'
    visibility_level = '"visibility_level": "flow_summary"'
    ven_type = '"ven_type": "server"'
    env_label_lock = '"env_label_lock": true'
    loc_label_lock = '"loc_label_lock": true'
    role_label_lock = '"role_label_lock": true'
    app_label_lock = '"app_label_lock": true'
    enforcement_mode_lock = '"enforcement_mode_lock": true'
    log_traffic_lock = '"log_traffic_lock": true'
    visibility_level_lock = '"visibility_level_lock": true'
    labels = get_labels(cluster_name)
    new_profile = '{"name": "' + cluster_name + '", ' + enforcement_mode + ', ' + enabled + ', ' + key_lifespan + ', ' + allowed_uses_per_key + ', ' + log_traffic + ', ' + visibility_level + ', ' + ven_type + ', ' + env_label_lock + ', ' + loc_label_lock + ', ' + role_label_lock + ', ' + app_label_lock + ', ' + enforcement_mode_lock + ', ' + log_traffic_lock + ', ' + visibility_level_lock + ', ' + '"labels": [' + labels + ']}'
    answer_json = post_requests(user, key, pairing_profile_url, new_profile)
    print("Pairing Profile " + cluster_name.upper() + " created.")
    return answer_json

 
def create_pairing_key(user, key, pairing_profile_id):
    key_gen_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/pairing_profiles/{pairing_profile_id}/pairing_key"
    data = '{}'
    answer_json = post_requests(user, key, key_gen_url, data)
    print("Pairing key for " + cluster_name.upper() + " created.")
    return answer_json

 
def get_requests(user, key, url):
    headers = dict()
    headers['Content-Type'] = 'application/json'
    http_proxy = "http://zscaler.abc.com:8410"
    https_proxy = "http://zscaler.abc.com:8410"
    proxies = {'http':http_proxy, 'https':https_proxy}
    auth = (user, key)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    r = requests.get(url, timeout=15, verify=False, headers=headers, proxies=proxies, auth=auth)
    if r.status_code == 204 or r.status_code == 200 or r.status_code == 201:
        answer = r.text
        answer_json = json.loads(answer)
        return answer_json
    else:
        get_answer = r.text
        print(r.status_code)
        print(get_answer)
        exit(1)

 
def post_requests(user, key, url, data):
    headers = dict()
    headers['Content-Type'] = 'application/json'
    http_proxy = "http://zscaler.abc.com:8410"
    https_proxy = "http://zscaler.abc.com:8410"
    proxies = {'http':http_proxy, 'https':https_proxy}
    auth = (user, key)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    r = requests.post(url, timeout=15, verify=False, headers=headers, proxies=proxies, auth=auth, data=data)
    if r.status_code == 204 or r.status_code == 200 or r.status_code == 201:
        answer = r.text
        answer_json = json.loads(answer)
        return answer_json
    else:
        get_answer = r.text
        print(r.status_code)
        print(get_answer)
        exit(1)

   
def put_requests(user, key, url, data):
    headers = dict()
    headers['Content-Type'] = 'application/json'
    http_proxy = "http://zscaler.abc.com:8410"
    https_proxy = "http://zscaler.abc.com:8410"
    proxies = {'http':http_proxy, 'https':https_proxy}
    auth = (user, key)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    r = requests.put(url, timeout=15, verify=False, headers=headers, proxies=proxies, auth=auth, data=data)
    if r.status_code == 204 or r.status_code == 200 or r.status_code == 201:
        answer = r.text
        answer_json = json.loads(answer)
        return answer_json
    else:
        get_answer = r.text
        print(r.status_code)
        print(get_answer)
        exit(1)

def get_labels(cluster_name):
    labels = ''
    role_label = "Cluster Node"
    location_label = "Azure Greenfield"

    target_env = cluster_name[8:10]
    if target_env == "dv":
        env_label = "Development"
    elif target_env == "te" or target_env == "st":
        env_label = "Clone"
    elif target_env == "pr":
        env_label = "Production"

    label_url = f"https://us-scp14.illum.io/api/v2/orgs/{org}/labels"
    label_answer = get_requests(user, key, label_url)
    for item in label_answer:
        label_name = item["value"]
        if label_name == cluster_name:
            print(label_name)
            label_href = item["href"]
            labels = labels + '{"href": "' + label_href + '"}, '
        if label_name == role_label:
            label_href = item["href"]
            labels = labels + '{"href": "' + label_href + '"}, '
        if label_name == location_label:
            label_href = item["href"]
            labels = labels + '{"href": "' + label_href + '"}, '
        if label_name == env_label:
            label_href = item["href"]
            labels = labels + '{"href": "' + label_href + '"}, '
    labels = labels[:-2]
    return labels

   
# def helm_install():

#     helm_command = ("helm install --set cluster_id=$CLUSTER_ID --set cluster_token=$CLUSTER_TOKEN --set cluster_code=$CLUSTER_CODE illumio . -n illumio-system -f values.yaml")
#     subprocess.run(helm_command, shell=True, capture_output=True, text=True)
   
# def k8s_create():

#     kubectl_ns_command = ("kubectl create ns illumio-system")
#     subprocess.run(kubectl_ns_command, shell=True, capture_output=True, text=True)

if __name__ == "__main__":

    main()