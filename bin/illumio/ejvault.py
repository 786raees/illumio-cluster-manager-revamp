#!/usr/bin/env python3
import json
import os
import time
import requests
import urllib3
import sys
import ejfile
from collections import defaultdict
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
 
def print_json(j):
    print(json.dumps(j, indent=4, sort_keys=True))

def parse_urls_file(file_path='urls.txt'):
    """
    Parse the urls.txt file to get configuration for different environments
    
    Args:
        file_path (str): Path to the urls.txt file
        
    Returns:
        defaultdict: Dictionary containing configuration for different sections and environments
    """
    urls = defaultdict(dict)
    current_section = None

    try:
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.endswith(':'):
                    current_section = line[:-1]
                elif '=' in line and current_section:
                    key, value = line.split('=', 1)
                    urls[current_section][key.strip()] = value.strip()
    except FileNotFoundError:
        print(f"Error: {file_path} file not found.")
        sys.exit(1)

    return urls

def try_vault_auth(location, url, token_request_data, proxies):
    success = False
    token = ''
    count = 0
    while count < 5:
        count += 1
        try:
            token_request = requests.post(url, data=token_request_data, proxies=proxies, verify=False, timeout=10)
            if token_request.status_code in [200, 204]:
                token = token_request.json()['auth']['client_token']
                success = True
                return success, token
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
        time.sleep(2)
    errmsg = f"Call to Vault for token failed 5 times with error: {token_request.status_code}, returned data: {token_request.json()}"
    return success, errmsg

def get_token(env=None):
    """
    Get authentication token from Vault
    
    Args:
        env (str): Environment to get token for (dev, test, stg, prod)
        
    Returns:
        tuple: (success, env, token)
    """
    # We must login to Vault and receive a token that will allow us to retrieve Secrets
    success = False
    token = ''

    # If env is not provided, try to get it from environment variables
    if env is None and "ENVIRONMENT" in os.environ:
        env = os.environ.get("ENVIRONMENT")
    
    # Check if env is valid
    valid_envs = {"dev", "test", "stg", "prod"}
    if env not in valid_envs:
        print(f"Error: Invalid environment '{env}'. Allowed values: {', '.join(valid_envs)}")
        return False, env, token

    # Get SA_TOKEN from environment or arguments
    if "SA_TOKEN" not in os.environ:
        print("Required environment variable SA_TOKEN is missing")
        return False, env, token

    sa_token = os.environ.get("SA_TOKEN")
    
    # Define data for token request
    token_request_data = {
        "jwt": sa_token,
        "role": "ips-illumio-pipeline-integration-mapping"
    }

    # Define proxies for token request...without this, request tries to go to Zscaler
    proxies = {"http": None, "https": None}

    # Get URLs from urls.txt
    urls = parse_urls_file()

    # Send request to Vault to get token for aporetosdp user
    if env == "prod":
        stl_url = urls["vault_login_url"].get("STL_VAULT_LOGIN")
        phx_url = urls["vault_login_url"].get("PHX_VAULT_LOGIN")

        temp_success, token = try_vault_auth(env, stl_url, token_request_data, proxies)
        if temp_success:
            success = True
        else:
            temp_success, token = try_vault_auth(env, phx_url, token_request_data, proxies)
            if temp_success:
                success = True
        if not success:
            print('Vault is inaccessible')
    else:
        url = urls["vault_login_url"].get(env)
        if not url:
            print(f"Vault login URL for environment '{env}' not found in urls.txt")
            return False, env, token

        temp_success, token = try_vault_auth(env, url, token_request_data, proxies)
        if temp_success:
            success = True
        else:
            print("Vault is inaccessible")

    return success, env, token

def get_pce_secrets(env=None):
    """
    Get PCE secrets from Vault
    
    Args:
        env (str): Environment to get secrets for (dev, test, stg, prod)
        
    Returns:
        tuple: (success, api_user, api_key)
    """
    # If env is not provided, try to get it from environment variables
    if env is None and "ENVIRONMENT" in os.environ:
        env = os.environ.get("ENVIRONMENT")
    
    # Check if env is valid
    valid_envs = {"dev", "test", "stg", "prod"}
    if env not in valid_envs:
        print(f"Error: Invalid environment '{env}'. Allowed values: {', '.join(valid_envs)}")
        return False, None, None

    # Get the URL from urls.txt
    urls = parse_urls_file()
    url = urls["pce_secrets_url"].get(env)
    if not url:
        print(f"Error: PCE secrets URL for environment '{env}' not found in urls.txt")
        return False, None, None

    # Now that we have our token, we can make requests for the Secrets
    success, env, token = get_token(env)
    if success:
        # Define header with token value to retrieve Secrets
        headers = {"X-Vault-Token": token}
        # Define proxies for token request...without this, request tries to go to Zscaler
        proxies = {"http": None, "https": None}

        try:
            pce_cred_request = requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=5)
            
            if not pce_cred_request.json()['data']['api_user']:
                print('PCE API key was not retrieved')
                if not pce_cred_request.json()['data']['api_key']:
                    print('Cannot retrieve Secrets from Prod or Clone')
                    return False, None, None
                else:
                    print('PCE API key value is missing but PCE API token value was retrieved')
                    return False, None, None
            else:
                api_user = pce_cred_request.json()['data']['api_user']
                api_user = cleanup_creds(api_user)
                
                if not pce_cred_request.json()['data']['api_key']:
                    print('PCE API key was retrieved but PCE API token value is missing')
                    return False, None, None
                else:
                    api_key = pce_cred_request.json()['data']['api_key']
                    api_key = cleanup_creds(api_key)
                    success = True
        except Exception as ex:
            print('Cannot retrieve Secrets from Vault')
            print(ex)
            return False, None, None
    else:
        print('Could not retrieve token from Vault')
        return False, None, None
        
    return success, api_user, api_key

def cleanup_creds(secret):
    """
    Cleanup Secret values by removing extra quotes and new line chars
    
    Args:
        secret (str): Secret to clean up
        
    Returns:
        str: Cleaned up secret
    """
    if secret is None:
        return None
        
    new_value = secret.replace('"','')
    new_value = new_value.strip()

    return new_value

def retrieve_cluster_secrets(cluster_name, env=None):
    """
    Retrieve cluster secrets from Vault for the specified cluster.
   
    Args:
        cluster_name (str): Name of the Kubernetes cluster
        env (str): Environment to get secrets for (dev, test, stg, prod)
       
    Returns:
        tuple: (container_cluster_id, container_cluster_token, pairing_key)
              or (None, None, None) if retrieval fails
    """
    try:
        # If env is not provided, try to get it from environment variables
        if env is None and "ENVIRONMENT" in os.environ:
            env = os.environ.get("ENVIRONMENT")
        
        # Check if env is valid
        valid_envs = {"dev", "test", "stg", "prod"}
        if env not in valid_envs:
            print(f"Error: Invalid environment '{env}'. Allowed values: {', '.join(valid_envs)}")
            return None, None, None
            
        # First get PCE credentials using get_pce_secrets function
        success, user, key = get_pce_secrets(env)
        if not success:
            print("Failed to retrieve PCE credentials from Vault")
            return None, None, None
           
        # Get token for Vault authentication
        success, env, token = get_token(env)
        if not success:
            print("Failed to authenticate with Vault")
            return None, None, None
           
        # Setup headers and proxies for Vault API requests
        headers = {"X-Vault-Token": token}
        proxies = {"http": None, "https": None}
       
        # Get URLs from urls.txt
        urls = parse_urls_file()
        url = urls["illumio_cluster_secret_url"].get(env)
        if not url:
            print(f"Error: Illumio cluster secret URL for environment '{env}' not found in urls.txt")
            return None, None, None
            
        # Add cluster name to URL
        url = f"{url.rstrip('/')}/{cluster_name}"
        print(f"Retrieving Illumio cluster secrets from Vault for cluster: {cluster_name}")
        print(f"Using Vault URL: {url}")  # Debug output
        
        try:
            response = requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=10)
            if response.status_code != 200:
                print(f"Failed to retrieve cluster secrets from Vault: HTTP {response.status_code}")
                print(f"Response: {response.text}")  # Add response text for debugging
                return None, None, None
               
            # Extract the secrets - handle both v1 and v2 KV store responses
            response_data = response.json()
            if "data" in response_data and "data" in response_data["data"]:
                # KV v2 format
                secrets_data = response_data["data"]["data"]
            else:
                # KV v1 format or direct data
                secrets_data = response_data.get("data", {})
           
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
            container_cluster_id = cleanup_creds(container_cluster_id)
            container_cluster_token = cleanup_creds(container_cluster_token)
            pairing_key = cleanup_creds(pairing_key)
           
            print("Successfully retrieved cluster secrets from Vault")
            return container_cluster_id, container_cluster_token, pairing_key
           
        except requests.exceptions.RequestException as ex:
            print(f"Failed to retrieve cluster secrets from Vault: {str(ex)}")
            return None, None, None
           
    except Exception as e:
        print(f"Error retrieving cluster secrets: {str(e)}")
        return None, None, None

def store_illumio_install_secrets(container_cluster_token, container_cluster_id, pairing_key, cluster_name, env=None):
    """
    Store Illumio installation secrets (token, ID, and pairing key) in Vault.
 
    Args:
        container_cluster_token (str): The container cluster token
        container_cluster_id (str): The container cluster ID
        pairing_key (str): The pairing key for the cluster
        cluster_name (str): The name of the cluster to prefix the keys with
        env (str): Environment (dev, test, stg, prod)
 
    Returns:
        bool: True if successful, False otherwise
    """
    # If env is not provided, try to get it from environment variables
    if env is None and "ENVIRONMENT" in os.environ:
        env = os.environ.get("ENVIRONMENT")
    
    # Check if env is valid
    valid_envs = {"dev", "test", "stg", "prod"}
    if env not in valid_envs:
        print(f"Error: Invalid environment '{env}'. Allowed values: {', '.join(valid_envs)}")
        return False

    # Get URLs from urls.txt
    urls = parse_urls_file()
    base_url = urls["illumio_cluster_secret_url"].get(env)
    if not base_url:
        print(f"Error: Illumio cluster secret URL for environment '{env}' not found in urls.txt")
        return False

    # Add cluster name to URL
    url = f"{base_url.rstrip('/')}/{cluster_name}"
    print(f"Storing Illumio cluster secrets in Vault for cluster: {cluster_name}")
    print(f"Using Vault URL: {url}")  # Debug output

    success = False
    success, env, token = get_token(env)
 
    if success:
        # Define header with token value to store secrets
        headers = {"X-Vault-Token": token}
        # Define proxies for token request...without this, request tries to go to Zscaler
        proxies = {"http": None, "https": None}
 
        # Create the data to be stored in Vault
        secrets_data = {
                f"{cluster_name}_container_cluster_token": container_cluster_token,
                f"{cluster_name}_container_cluster_id": container_cluster_id,
                f"{cluster_name}_pairing_key": pairing_key
        }
 
        try:
            # Store data in Vault using API
            vault_response = requests.post(
                url,
                headers=headers,
                proxies=proxies,
                verify=False,
                timeout=10,
                json=secrets_data
            )
 
            # Check if the request was successful
            if vault_response.status_code in [200, 201, 204]:
                success = True
                print("Successfully stored Illumio install secrets in vault")
            else:
                print(f"Failed to store secrets in vault. Status code: {vault_response.status_code}")
                print(f"Response: {vault_response.text}")
        except Exception as ex:
            print(f"Exception occurred while storing secrets in vault: {ex}")
    else:
        print("Could not retrieve token from Vault")
 
    return success

def get_ad_secrets():
    # Now that we have our token, we can make requests for the Secrets
    success, env, token = get_token()
    if success:
        # Define header with token value to retrieve Secrets
        headers = {"X-Vault-Token": token}
        # Define proxies for token request...without this, request tries to go to Zscaler
        proxies = {"http": None, "https": None}
        # Define list name that contains Prisma Cert/Key values
        # Retrieve secrets for dev, uat, and prod prisma consoles
        if "AD_CREDS" in os.environ:
            url = os.environ.get("AD_CREDS")
            try:
                ad_cred_request = requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=5)
                if not ad_cred_request.json()['data']['ad_username']:
                    print('Username was not retrieved')
                    if not ad_cred_request.json()['data']['ad_password']:
                        print('Cannot retrieve Secrets from Prod or Clone')
                        sys.exit(1)
                    else:
                        print('Username value is missing but password value was retrieved')
                        sys.exit(1)
                else:
                    ad_username = ad_cred_request.json()['data']['ad_username']
                    ad_username = cleanup_creds(ad_username)
                   
                    if not ad_cred_request.json()['data']['ad_password']:
                        print('Username was retrieved but password value is missing')
                        sys.exit(1)
                    else:
                        ad_password = ad_cred_request.json()['data']['ad_password']
                        ad_password = cleanup_creds(ad_password)
                        success = True          
            except Exception as ex:
                print('Cannot retrieve Secrets from Vault')
                print(ex)
                sys.exit(1)
        else:
            print('Could not identify the location of vault')
            sys.exit(1)
    else:
        print('Could not retreive token from Vault')
        if "GH_USERNAME" in os.environ and "GH_PASSWORD" in os.environ:
            ad_username = os.environ["GH_USERNAME"]
            ad_password = os.environ["GH_PASSWORD"]
            success = True
        else:
            sys.exit(1)
    return success, ad_username, ad_password

def get_auth_key():
    success = False
    message = ""
    key = ""
    success, env, token = get_token()
    if success:
        # Define header with token value to retrieve Secrets
        headers = {"X-Vault-Token": token}
        # Define proxies for token request...without this, request tries to go to Zscaler
        proxies = {"http": None, "https": None}
        # Define list name that contains Prisma Cert/Key values
        # Retrieve secrets for dev, uat, and prod prisma consoles
        if "SDP_KEY" in os.environ:
            url = os.environ.get("SDP_KEY")
            try:
                sdp_key_request = requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=10)
                if not sdp_key_request.json()['data']['key']:
                    message = 'SDP Auth key was not retrieved.  It may not exist in Vault.'
                else:
                    sdp_key = sdp_key_request.json()['data']['key']
                    key = cleanup_creds(sdp_key)
                    success = True          
            except Exception as ex:
                print('Cannot retrieve Secrets from Vault')
                print(ex)
                sys.exit(1)
        else:
            print('Secret location is unknown...check env variables')
            sys.exit(1)
    else:
        print('Could not retreive token from Vault')
        sys.exit(1)
    return success, message, key