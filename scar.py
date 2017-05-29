#! /usr/bin/python

# SCAR - Serverless Container-aware ARchitectures
# Copyright (C) GRyCAP - I3M - UPV 
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import boto3
import zipfile
import os
import shutil
import json
import base64
from tabulate import tabulate
from botocore.exceptions import ClientError
import re

version = "v0.0.1"
dir_path = os.path.dirname(os.path.realpath(__file__))
lambda_name = "scar_function"
zif_file_path = dir_path + '/function.zip'

def check_memory(lambda_memory):
    """ Check if the memory introduced by the user is correct.
    If the memory is not specified in 64mb increments, 
    transforms the request to the next available increment."""
    if (lambda_memory < 128) or (lambda_memory > 1536):
        raise Exception('Incorrect memory size specified')       
    else:
        res = lambda_memory % 64
        if (res == 0):
            return lambda_memory
        else:
            return lambda_memory - res + 64
            
        
def check_time(lambda_time):
    if (lambda_time <= 0) or (lambda_time > 300):
        raise Exception('Incorrect time specified')
    return lambda_time

def create_zip_file(file_name=lambda_name):
    # Set generic lambda function name
    function_name = file_name + '.py'
    # Copy file to avoid messing with the repo files
    # We have to rename because the function name afects the handler name
    shutil.copy(dir_path + '/lambda/scarsupervisor.py', function_name)
    # Zip the function file
    with zipfile.ZipFile(zif_file_path, 'w') as zf:
        # Lambda function code
        zf.write(function_name)
        # Udocker script code
        zf.write(dir_path + '/lambda/udocker', 'udocker')
        # Udocker libs
        zf.write(dir_path + '/lambda/udocker-1.1.0-RC2.tar.gz', 'udocker-1.1.0-RC2.tar.gz')
        os.remove(function_name)
    # Return the zip as an array of bytes
    with open(zif_file_path, 'rb') as f:
        return f.read()
    
def load_payload(payload):
    with open(payload, 'rb') as f:
        return f.read()

def get_user_name():
    try:
        return boto3.client('iam').get_user()['User']['UserName']
    except ClientError as ce:
        # If the user doesn't have access rights to IAM
        return find_expression('(?<=user\/)(\S+)', str(ce))

def find_expression(rgx_pattern, string_to_search):
    '''Returns the first group that matches the rgx_pattern in the string_to_search'''
    pattern = re.compile(rgx_pattern)
    match = pattern.search(string_to_search)
    if  match :
        return match.group()
    
def escape_string(value):
    value = value.replace("\\", "\\/").replace('\n', '\\n')
    value = value.replace('"', '\\"').replace("\/", "\\/")
    value = value.replace("\b", "\\b").replace("\f", "\\f")
    return value.replace("\r", "\\r").replace("\t", "\\t")

def get_access_key():
    session = boto3.Session()
    credentials = session.get_credentials()
    return credentials.access_key

def parse_logs(logs, request_id):
    full_msg = ""
    logging = False
    #print (json.dumps(logs))
    
    print("request id: " + request_id)
    
    for event in logs['events']:
        if request_id in event['message']:
            if event['message'].startswith('START'):
                logging = True
            else:
                logging = False
            full_msg += event['message']
        if logging:
            full_msg += event['message']
    return full_msg

def  base64_to_utf8(value):
    return base64.b64decode(value).decode('utf8') 

class Scar(object):
    """Implements most of the command line interface.
    These methods correspond directly to the commands that can
    be invoked via the command line interface.
    """

    def __init__(self):
        self.create_boto3_client()
        self.create_command_parser()
    
    def init_lambda_fuction_parameters(self):
        self.lambda_name = lambda_name
        self.lambda_runtime = "python2.7"
        self.lambda_handler = self.lambda_name + ".lambda_handler"        
        self.lambda_role = "arn:aws:iam::974349055189:role/lambda-s3-execution-role"        
        self.lambda_env_variables = {"Variables" : {"UDOCKER_DIR":"/tmp/home/.udocker",
                                                    "UDOCKER_TARBALL":"/var/task/udocker-1.1.0-RC2.tar.gz"}}
        self.lambda_zip_file_base64 = {"ZipFile": create_zip_file()}
        self.lambda_memory = 128
        self.lambda_time = 3
        self.lambda_description = "Automatically generated lambda function"
        self.lambda_tags = { 'owner' : get_user_name(),
                            'createdby' : 'scar' }
        

    def create_boto3_client(self):
        self.boto3_client = boto3.client('lambda', region_name='us-east-1')

    def create_command_parser(self):
        self.parser = argparse.ArgumentParser(prog="scar",
                                              description="Deploy containers in serverless architectures",
                                              epilog="Run 'scar COMMAND --help' for more information on a command.")
        subparsers = self.parser.add_subparsers(title='Commands')
                
        # 'init' command
        parser_init = subparsers.add_parser('init', help="Create lambda function")
        # Set default function
        parser_init.set_defaults(func=self.init)
        # Set the positional arguments
        parser_init.add_argument("image_id", help="Container image id (i.e. centos:7)") 
        # Set the optional arguments
        parser_init.add_argument("-d", "--description", help="Lambda function description.")        
        parser_init.add_argument("-n", "--name", help="Lambda function name")
        parser_init.add_argument("-m", "--memory", type=int, help="Lambda function memory in megabytes. Range from 128 to 1536 in increments of 64")
        parser_init.add_argument("-t", "--time", type=int, help="Lambda function maximum execution time in seconds. Max 300.")
        parser_init.add_argument("-j", "--json", help="Return data in JSON format", action="store_true")
        parser_init.add_argument("-v", "--verbose", help="Show the complete aws output in json format", action="store_true")
    
        # 'ls' command
        parser_ls = subparsers.add_parser('ls', help="List lambda functions")
        parser_ls.set_defaults(func=self.ls)
        parser_ls.add_argument("-j", "--json", help="Return data in JSON format", action="store_true")
        parser_ls.add_argument("-v", "--verbose", help="Show the complete aws output in json format", action="store_true")
        
        # 'run' command
        parser_run = subparsers.add_parser('run', help="Deploy function")
        parser_run.set_defaults(func=self.run)
        parser_run.add_argument("name", help="Lambda function name")
        parser_run.add_argument("-m", "--memory", type=int, help="Lambda function memory in megabytes. Range from 128 to 1536 in increments of 64")
        parser_run.add_argument("-t", "--time", type=int, help="Lambda function maximum execution time in seconds. Max 300.")
        parser_run.add_argument("-e", "--env", action='append', help="Pass environment variable to the container (VAR=val). Can be defined multiple times.")
        parser_run.add_argument("--async", help="Tell Scar to wait or not for the lambda function return", action="store_true")
        parser_run.add_argument("-p", "--payload", nargs='?', type=argparse.FileType('r'), help="Path to the input file passed to the function")        
        parser_run.add_argument("-j", "--json", help="Return data in JSON format", action="store_true")
        parser_run.add_argument("-v", "--verbose", help="Show the complete aws output in json format", action="store_true")
        
        # Create the parser for the 'rm' command
        parser_rm = subparsers.add_parser('rm', help="Delete function")
        parser_rm.set_defaults(func=self.rm)
        parser_rm.add_argument("name", help="Lambda function name")
        parser_rm.add_argument("-j", "--json", help="Return data in JSON format", action="store_true")
        parser_rm.add_argument("-v", "--verbose", help="Show the complete aws output in json format", action="store_true")
        
        # 'log' command
        parser_log = subparsers.add_parser('log', help="Show the logs for the lambda function")
        parser_log.set_defaults(func=self.log)
        parser_log.add_argument("log_group_name", help="The name of the log group.")
        parser_log.add_argument("log_stream_name", help="The name of the log stream.")       

        # Create the parser for the 'version' command
        parser_version = subparsers.add_parser('version', help="Show the Scar version information")
        parser_version.set_defaults(func=self.version) 
    
    def execute(self):
        """Command parsing and selection"""
        args = self.parser.parse_args()
        args.func(args)

    def init(self, args):
        if self.check_function_name(args.name):
            print("ERROR: Cannot create function. Function name '" + args.name + "' already defined.")
            return
        self.init_lambda_fuction_parameters()
        if args.name:
            self.lambda_name = args.name
            self.lambda_handler = self.lambda_name + ".lambda_handler"
            self.lambda_zip_file_base64 = {"ZipFile": create_zip_file(args.name)}  
        if args.memory:
            self.lambda_memory = check_memory(args.memory)
        if args.time:
            self.lambda_time = check_time(args.time)
        if args.description:
            self.lambda_description = args.description  
        if args.image_id:
            self.lambda_env_variables['Variables']['IMAGE_ID'] = args.image_id
        # Call the AWS service
        response = self.boto3_client.create_function(FunctionName=self.lambda_name,
                                                     Runtime=self.lambda_runtime,
                                                     Role=self.lambda_role,
                                                     Handler=self.lambda_handler,
                                                     Code=self.lambda_zip_file_base64,
                                                     Environment=self.lambda_env_variables,
                                                     Description=self.lambda_description,
                                                     Timeout=self.lambda_time,
                                                     MemorySize=self.lambda_memory,
                                                     Tags=self.lambda_tags)
        # Remove the zip created in the operation
        os.remove(zif_file_path)
        result = {'AccessKey' : get_access_key(),
                  'FunctionArn' : response['FunctionArn'],
                  'Timeout' : response['Timeout'],
                  'MemorySize' : response['MemorySize'],
                  'FunctionName' : response['FunctionName']}
        # Parse output
        if args.verbose:
            print(json.dumps(response))
        elif args.json:        
            print (json.dumps(result))
        else:
            print ("Function '" + args.name + "' successfully initiated.")
    
    def check_function_name(self, function_name):
        paginator = self.boto3_client.get_paginator('list_functions')  
        for functions in paginator.paginate():         
            for lfunction in functions['Functions']:
                if function_name == lfunction['FunctionName']:
                    return True
        return False
       
    def ls(self, args):
        # Get the filtered resources from AWS
        client = boto3.client('resourcegroupstaggingapi', region_name='us-east-1')
        tag_filters = [ { 'Key': 'owner', 'Values': [ get_user_name() ] }, { 'Key': 'createdby', 'Values': ['scar'] } ]
        response = client.get_resources(TagFilters=tag_filters, TagsPerPage=100)
        filtered_functions = response['ResourceTagMappingList']
        # Create the data structure
        result = {'Functions': []}
        for function_arn in filtered_functions:
            function_info = self.boto3_client.get_function(FunctionName=function_arn['ResourceARN'])
            function = {'Name' : function_info['Configuration']['FunctionName'],
                        'Memory' : function_info['Configuration']['MemorySize'],
                        'Timeout' : function_info['Configuration']['Timeout']}
            result['Functions'].append(function)
        # Parse output
        if args.verbose:
            print(json.dumps(response))
        elif args.json:
            print(json.dumps(result))
        else:  
            headers = ['NAME', 'MEMORY', 'TIME']
            table = []
            for function in result['Functions']:
                table.append([function['Name'],
                              function['Memory'],
                              function['Timeout']])            
            print (tabulate(table, headers))
        
    def run(self, args):
        invocation_type = 'RequestResponse'
        log_type = 'Tail'
        if args.async:
            invocation_type = 'Event'
            log_type = 'None' 
        
        if args.memory:
            self.boto3_client.update_function_configuration(FunctionName=args.name,
                                                            MemorySize=check_memory(args.memory))   
        if args.time:
            self.boto3_client.update_function_configuration(FunctionName=args.name,
                                                            Timeout=check_time(args.time))   
        if args.env:
            # Retrieve the global variables already defined
            self.lambda_env_variables = self.boto3_client.get_function(FunctionName=args.name)['Configuration']['Environment']
            for var in args.env:
                var_parsed = var.split("=")
                # Add an specific prefix to be able to find the variables defined by the user
                self.lambda_env_variables['Variables']['CONT_VAR_' + var_parsed[0]] = var_parsed[1]
            self.boto3_client.update_function_configuration(FunctionName=args.name,
                                                            Environment=self.lambda_env_variables)   
        if args.payload:
            # Generate the script passed to the container
            script = "{ \"script\" : \"" + escape_string(args.payload.read()) + "\"}"
            response = self.boto3_client.invoke( FunctionName=args.name,
                                                 InvocationType=invocation_type,
                                                 LogType=log_type,
                                                 Payload=script)
        else:
            response = self.boto3_client.invoke( FunctionName=args.name,
                                                 InvocationType=invocation_type,
                                                 LogType=log_type)
        
        # Transform the base64 encoded results to something legible
        response['LogResult'] = base64_to_utf8(response['LogResult'])        
        response['ResponseMetadata']['HTTPHeaders']['x-amz-log-result'] = base64_to_utf8(response['ResponseMetadata']['HTTPHeaders']['x-amz-log-result'])

        # Extract log_group_name and log_stream_name from payload
        function_output = response['Payload'].read().decode("utf-8")[1:-1]
        response['Payload'] = function_output.replace('\\n','\n')
        result = response['Payload']
        
        parsed_output = result.split('\n')
        response['LogGroupName'] = parsed_output[0][22:]
        response['LogStreamName'] = parsed_output[1][23:]
        
        if args.verbose:
            print(json.dumps(response))
        elif args.json:
            result = {'StatusCode' : response['StatusCode'],
                      'Payload' : response['Payload'],
                      'LogGroupName' : response['LogGroupName'],
                      'LogStreamName' : response['LogStreamName']}
            print(json.dumps(result))            
        else:
            print(result)            
        
    def rm(self, args):
        # Call AWS delete
        response = self.boto3_client.delete_function(FunctionName=args.name)
        # Parse output
        if args.verbose:
            print(json.dumps(response))
        elif args.json:
            result = {'RequestId' : response['RequestId'],
                      'ResponseMetadata' : response['ResponseMetadata']['HTTPStatusCode']}
            print(json.dumps(result))
        else:
            if response['ResponseMetadata']['HTTPStatusCode'] == 204:
                print ("Function '" + args.name + "' deleted.")
            else:
                print("Error deleting function '" + args.name + "'.")

    def log(self, args):
        response = boto3.client('logs', region_name='us-east-1').get_log_events(
            logGroupName=args.log_group_name,
            logStreamName=args.log_stream_name,
            startFromHead=True
        )
        full_msg = ""
        for event in response['events']:
            full_msg += event['message']
        response['completeMessage'] = full_msg
        print (full_msg)
        '''
        request_id = response['ResponseMetadata']['RequestId']  
        log_group_name = parsed_output[0][22:]
        log_stream_name = parsed_output[1][23:]
        sleep(5)
        # Output the container logs
        log_response = boto3.client('logs', region_name='us-east-1').get_log_events(
            logGroupName=log_group_name,
            logStreamName=log_stream_name,
            startFromHead=True
        )
        '''
    
    def version(self, args):
        print ("scar " + version)



if __name__ == "__main__":
    Scar().execute()        
