
from flask import Flask, g, redirect, request, render_template, url_for, session, make_response, jsonify
import boto3
from os.path import basename, splitext
import json
from typing import Dict, Any
from base64 import encodebytes, b64encode, b64decode
from json import dumps
from io import BytesIO
import os
import time

#for local run ONLY comment switch
# from .src.project_s3_functions import * 
from src.project_s3_functions import * 

from typing import Tuple, List
from datetime import datetime 

#for local run ONLY comment switch
# from .dynamoDB_sessions import *
from dynamoDB_sessions import *

import toml
from flask_cognito_auth import CognitoAuthManager, login_handler, logout_handler, callback_handler
from zappa.asynchronous import task
import requests
import ast
from functools import wraps

app = Flask(__name__)
cognito = CognitoAuthManager(app)
cognito = CognitoAuthManager(app)
def login_required(f):
    """custom decorator to use dynamodb for authentication with JWT encrypted data"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # if API call --- TODO implement API authentication --- use API auth tokens + header
        # Get session ID from header
        session_id_header = request.args.get("session_id", None)
        
        if session_id_header == "" or session_id_header is None:
            print("no session ID...")
            return redirect(url_for("login", session_id=None))

        #if it is here, decrypt it to make sure no data was changed
        else:
            # request_arg exists
            try:
                print("found session ID")

                # TODO --- refactor this to be faster down the line to only query once every 45 minutes

                # Try to decrypt the user data from dynamodb
                # did_it_work, jwt_from_dynamo = get_auth_token(session_id_header)
                
                jwt_from_dynamo = query_data_from_table("labtools",
                                                        primary_key=f"auth#{session_id_header}",
                                                        sk_expression="jwt#",
                                                        match_type="begins_with",
                                                        )
                
                # if the token was tampered with, JWT decrypt throws an error
                # known as current_user
                # current_user = decrypt_jwt(jwt_from_dynamo['Item'])
                current_user = decrypt_jwt(jwt_from_dynamo["Items"][0]["SK"]["S"].split("#")[1])
                
                # returns the decorated function with current user as the first arg
                return f(current_user, *args, **kwargs)
                # evaluate the  expiration time from string
                
                # TODO - implement TTL in dynamo and check it
               
            except Exception as e:
                print(e)
                print("couldn't validate session id, something changed")
                return redirect(url_for("error_401"))

    return decorated_function

def get_current_datetime():
    """gets current date/time stamp in month/day/year|Hour:minute AM/PM"""
    return datetime.now(timezone('US/Eastern')).strftime('%b/%d/%Y|%I:%M %p')



@app.route('/view_projects', methods=['GET', "POST"])
@login_required
def view_projects(current_user):
    """main URL for view_projects"""
    if request.method == "GET":
        return render_template("view_projects.html", session_id=request.args.get("session_id"), current_user = current_user, page_title="View Projects")
    else:
        return "please dont post..."
