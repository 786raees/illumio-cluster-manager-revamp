#!/usr/bin/env python3
 
import getpass
import grp
import json
import os
import pwd
import site
import stat
import collections
import json
import os
import requests
import urllib3
import sys
site.addsitedir('/app/bin')
import ejconfig
import ejvault
 
# for debugging
# import importlib
# from aporeto import file as ejfile
 
def set_exec_perms(entity):
    try:
        user = os.getlogin()
    except:
        user = getpass.getuser()
    if pwd.getpwuid(os.stat(entity).st_uid).pw_name == user:
        if os.path.isdir(entity):
            os.chmod(entity,stat.S_IRWXU+stat.S_IRWXG)
        else:
            os.chmod(entity,stat.S_IRWXU+stat.S_IRWXG)
        ginfo = grp.getgrnam(ejconfig.group)
        gid = ginfo.gr_gid
        os.chown(entity,-1,gid)
    return
 
def set_perms(entity):
    try:
        user = os.getlogin()
    except:
        user = getpass.getuser()
    if pwd.getpwuid(os.stat(entity).st_uid).pw_name == user:
        if os.path.isdir(entity):
            os.chmod(entity,stat.S_IRWXU+stat.S_IRWXG)
        else:
            os.chmod(entity,stat.S_IRUSR+stat.S_IWUSR+stat.S_IRGRP+stat.S_IWGRP+stat.S_IROTH)
        ginfo = grp.getgrnam(ejconfig.group)
        gid = ginfo.gr_gid
        os.chown(entity,-1,gid)
    return
 
# Generic function to list the contents of a specified directory
#   returns files (list)
def list_files(dirname):
    files = list()
    if os.path.isdir(dirname):
        files = os.listdir(dirname)
    return files
 
# Generic function to standardize testing if file exists
#   returns status (bool)
def generic_file_exist(filename):
    if os.path.isfile(filename):
        status = True
    else:
        status = False
    return status
 
# This generic function reads a specified filename
#   which may not exist (which is not an error)
#   and returns the data contained
#   returns success (bool), text (string), message (string)
def parse_text_file(filename):
    success = False
    text = ''
    message = ''
    if not generic_file_exist(filename):
        message = filename + ' does not exist'
    else:
        try:
            with open(filename) as text_data:
                text = text_data.read()
        except Exception as ex:
            message = 'Failed to read filename as text: ' + str(ex)
        else:
            success = True
    return success, text, message
 
# Function reads the userid
#    returns the output of parse_text_file (string)
def parse_userid_file():
    filename = ejconfig.userid_file
    return parse_text_file(filename)
 
# Function reads the userid
#    returns the output of parse_text_file (string)
def parse_password_file():
    filename = password_file
    return parse_text_file(filename)
 
# Function writes a temporary file with the provided contents
#   returns success (bool), tmp_file (string)
def write_temp_file(contents):
    success = False
    tmp_file = '/tmp/' + str(os.getpid())
    message = ''
    try:
        f = open(tmp_file,"w")
        f.write(contents)
        f.close()
    except Exception as ex:
        message = str(ex)
    else:
        success = True
    return success, tmp_file, message
 
# Takes the path to a json file, loads it, and returns the json object
#   returns success (bool), json_data (dict), message (string)
def file_to_json(input_fl):
    success = False
    json_data = dict()
    message = ''
    if generic_file_exist(input_fl):
        with open(input_fl,'r') as infile:
            try:
                json_data = json.load(infile,object_pairs_hook=collections.OrderedDict)
            except json.decoder.JSONDecodeError as ex:
                message = 'Problem importing json from specified file [' + input_fl + ']: ' + str(ex)
            else:
                success = True
    else:
        message = 'Specified file does not exist [' + input_fl + ']'
    return success, json_data, message
 
# Function removed the specified file
#   returns success(bool)
def remove_file(filename):
    success = False
    if generic_file_exist(filename):
        try:
            os.remove(filename)
        except:
            pass
        else:
            success = True
    return success
 
# Generic function to write specified text to a file
#  This function does not validate specified file will not overwrite OS files
#  because assumed permissions are in place to prevent
def write_generic_text(text,filename):
    success = False
    message = ''
    try:
        f = open(filename,'w')
        f.write(text)
        f.close()
        set_perms(filename)
        success = True
    except Exception as ex:
        success = False
        message = str(ex)
    return success, message
 
# Function to parse json from env file and map to dictionaries
#   returns success(bool), aporeto (dict), message (string)
def read_aporeto_env():
    success, aporeto, message = file_to_json(ejconfig.aporeto_env_json)
    return success, aporeto, message
 
# Function to parse json from env file and map to dictionaries
#   returns success (bool), defined_tagprefixes (dict), message (string)
def read_aporeto_tagprefixes():
    success, defined_tagprefixes, message = file_to_json(ejconfig.aporeto_tagprefixes_json)
    return success, defined_tagprefixes, message
 
 
# Function will write a "binary file", pptx, docx, exe from a specified location
#  returns success (bool), blob (file contents), message (string)
def write_binary_file(filename, contents):
    success = False
    message = ''
    try:
        with open(filename, mode='wb') as file:
                file.write(contents)
    except Exception as ex:
        message = str(ex)
    else:
        success = True
    return success, message
 
 
# Function makes the specified directory
#  returns success (bool), message (str)
def make_dir(path):
    success = False
    message = ''
    if not os.path.exists(path):
        try:
            os.mkdir(path)
        except Exception as ex:
            message = str(ex)
        else:
            message = ''
    elif os.path.isdir(path):
        # Assume we can use existing directory
        message = ''
    else:
        message = 'Specified location ' + path + ' already exists and is not a directory'
    #print(message)
    if message == '':
        success = True
    return success, message
 
 
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
def print_json(j):
    print(json.dumps(j, indent=4, sort_keys=True))