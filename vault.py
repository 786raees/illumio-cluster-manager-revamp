#!/usr/bin/env python3
import json
import os
import time
import requests
import urllib3
import sys
import ejfile
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
 
def print_json(j):
    print(json.dumps(j, indent=4, sort_keys=True))
 
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
 
 
def get_token():
    #We must login to Vault and receive a token that will allow us to retrieve Secrets
    #Assign value of SA_TOKEN env var to local var
    success = False
    token = ''
    env = ''
    if "SA_TOKEN" in os.environ and "ENVIRONMENT" in os.environ:
        sa_token = os.environ.get("SA_TOKEN")
        env = os.environ.get("ENVIRONMENT")
        #Define data for token request
        token_request_data = {"jwt": sa_token, "role": "ips-illumio-pipeline-integration-mapping"}
        #Define proxies for token request...without this, request tries to go to Zscaler
        proxies = {"http": None,"https": None}
        #Send request to Vault to get token for aporetosdp user
        if env == "prod":
            stl_url = os.environ.get("STL_VAULT_LOGIN")
            phx_url = os.environ.get("PHX_VAULT_LOGIN")
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
            url = os.environ.get("VAULT_LOGIN")
            temp_success, token = try_vault_auth(env, url, token_request_data, proxies)
            if temp_success:
                success = True
            if not success:
                print('Vault is inaccessible')
    else:
        print('Required environment variables are missing')
    return success, env, token
 
 
def get_pce_secrets():
    #Now that we have our token, we can make requests for the Secrets
    success, env, token = get_token()
    if success:
        #Define header with token value to retrieve Secrets
        headers = {"X-Vault-Token": token}
        #Define proxies for token request...without this, request tries to go to Zscaler
        proxies = {"http": None,"https": None}
        #Define list name that contains Prisma Cert/Key values
        #Retrieve secrets for dev, uat, and prod prisma consoles
        if "PCE_CREDS" in os.environ:
            url = os.environ.get("PCE_CREDS")
            try:
                pce_cred_request = requests.get(url, headers=headers, proxies=proxies, verify=False, timeout=5)
                if not pce_cred_request.json()['data']['api_user']:
                    print('PCE API key was not retrieved')
                    if not pce_cred_request.json()['data']['api_key']:
                        print('Cannot retrieve Secrets from Prod or Clone')
                        sys.exit(1)
                    else:
                        print('PCE API key value is missing but PCE API token value was retrieved')
                        sys.exit(1)
                else:
                    api_user = pce_cred_request.json()['data']['api_user']
                    api_user = cleanup_creds(api_user)
                   
                    if not pce_cred_request.json()['data']['api_key']:
                        print('PCE API key was retrieved but PCE API token value is missing')
                        sys.exit(1)
                    else:
                        api_key = pce_cred_request.json()['data']['api_key']
                        api_key = cleanup_creds(api_key)
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
    return success, api_user, api_key
 
def get_auth_key():
    success = False
    message = ""
    key = ""
    success, env, token = get_token()
    if success:
        #Define header with token value to retrieve Secrets
        headers = {"X-Vault-Token": token}
        #Define proxies for token request...without this, request tries to go to Zscaler
        proxies = {"http": None,"https": None}
        #Define list name that contains Prisma Cert/Key values
        #Retrieve secrets for dev, uat, and prod prisma consoles
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
 
 
def cleanup_creds(secret):
#Cleanup Secret values by removing extra quotes and new line chars
 
    new_value = secret.replace('"','')
    new_value = new_value.strip()
 
    return new_value