import os
from flask import Flask, request, jsonify, render_template
import openai
from zappa.asynchronous import task
import requests
import json
import re
from time import sleep
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import boto3
import toml 
from typing import Optional
from github import Github # pip install PyGithub
from jira import JIRA
import sys
import pytz
import requests
from io import BytesIO
import tokenize
from requests.structures import CaseInsensitiveDict
import shortuuid
import time 


def post_to_slack(message:str,response_url:str):
    """
    Sends a message to a Slack channel using the provided response URL.
    Args:
        message (str): The message to be sent to the Slack channel.
        response_url (str): The URL to which the message should be posted.
    Returns:
        bool: True if the message was sent successfully, False otherwise.
    Raises:
        None
    Example:
        post_to_slack("Hello, World!", "https://slack.com/response")
        This example sends the message "Hello, World!" to the Slack channel specified by the response URL "https://slack.com/response".
    """
            # Create the payload as a dictionary
    payload = {'text': message }

    # Convert the payload to JSON
    payload_json = json.dumps(payload)

    personal_response = requests.post(response_url, data=payload_json)
    # Check the response status
    if personal_response.status_code == 200:
        print("Personal Slack message sent successfully.")
        return True
    else:
        print("Failed to send Slack message.")
        return False
def find_between( s, first, last ):
    try:
        start = s.index( first ) + len( first )
        end = s.index( last, start )
        return s[start:end]
    except ValueError:
        return ""
def get_completion(prompt):
    '''
    Description: 
        Function to create code sections that are enclosed in triple backticks
        are formatted as HTML code blocks with a white background.

    ARGS: 
        prompt(str): input from user 
    
    Returns:
        str: the generated completion with code sections formatted as HTML
    '''

    max_token_length = 4050 - len(prompt)
    chatgpt_response = openai.ChatCompletion.create(
            model='gpt-3.5-turbo-16k',  # Use the desired engine for ChatGPT
            messages=[{"role": "user", "content":  prompt}],
            max_tokens=max_token_length,  # Define the maximum length of the generated response
            n=1,  # Specify the number of responses to generate
            stop=None,  # Optionally provide a stop sequence to limit the response
            temperature=0.7,  # Control the randomness of the generated response (0.0 to 1.0)
        )
    raw_output = chatgpt_response.choices[0].message.content.strip()

    # replace code sections with new HTML
    try:
        for code in re.findall(r'.*?```', raw_output, re.DOTALL):
            code_formatted_output = raw_output.replace(code, "<br><code style='background-color:white'>{}</code><br>".format(code))

        return code_formatted_output.replace("\n", "<br>")

    except:
        return raw_output


app = Flask(__name__)
@app.route('/', methods=['GET', 'POST'])


@app.route('/status')
def status():
    return "online"

@app.route("/devgpt", methods=["POST", 'GET'])
def devgpt():
    run_devgpt(prompt=request.form.get('text'), 
               response_url = request.form.get("response_url"))
    return f"Your input was: /devgpt {request.form.get('text')}\n"


@task
def run_devgpt(prompt:str , response_url:str):
    """
    Uses Jira code type ticket number to create a branch on a repository with new files and adds comment to the Jira ticket

    Args:
        Prompt (str): String value from user specifying Jira ticket in format "Project-number"
        response_url (str): String value retrurned with url location for slack

    Returns:
        True when run
    """

    try:


        #Set branch name to prompt and split into variables
        jira_ticket_id = prompt.strip()
        project, ticket_number = jira_ticket_id.split('-')


        #jira auth
        auth_jira = JIRA(
        server = 'https://vitalityrobotics.atlassian.net',
        basic_auth=('vina.raja@vitalityrobotics.com', jira_api_token))

        # Fetch all fields
        allfields = auth_jira.fields()

        # Make a map from field name -> field id
        nameMap = {field['name']:field['id'] for field in allfields}

        # Fetch an issue
        issue = auth_jira.issue(f'{jira_ticket_id}')

        # You can now look up custom fields by name using the map
        repo_name = str(getattr(issue.fields, nameMap['Github Repository']))
        description = str(getattr(issue.fields, nameMap['Description']))
        #split repo name to extract ticket number and repo owner
        r = repo_name.split('/')
        repo_owner = r[-2]
        repo_n = r[-1]

        #Check Github token exists
        if not github_token:
            raise ValueError("GitHub access token not provided. Please set the GITHUB_ACCESS_TOKEN variable.")

        # Authenticate with GitHub using access token
        g = Github(github_token)

        # Get the repository
        repo = g.get_repo(f'{repo_owner}/{repo_n}')
         
        # Check if the source branch exists
        try:
            source_branch = repo.get_branch('dev')
        #If source branch does not exist notify user
        except:
            message ='Your repo does not have a dev branch...Exiting devgpt'
            post_to_slack(message, response_url)
            return False


        # Check if the target branch (branch_name) exists
        target_branch =None
        for rep in repo.get_git_refs():
            if rep.ref == f'refs/heads/{jira_ticket_id}':
                target_branch = rep
                break

        #If branch exists set target_branch variable

        if target_branch:
            target_branch = repo.get_branch(jira_ticket_id)
        #Create new branch if branch does not exist
        else:
            repo.create_git_ref(ref=f"refs/heads/{jira_ticket_id}", sha=source_branch.commit.sha)
        
        #Wait 1 second if branch needs to be created
        time.sleep(1)

        #Set target branch variable
        target_branch = repo.get_branch(jira_ticket_id)

        #Get Description from branch and let user know to wait a few minutes
        post_to_slack(f'Your description has been read. Please allow 2-3 minutes for your code to be added to this repository branch:\n{repo_name}',
                      response_url)

        #split description by #TASK keyword
        tasks = [ x for x in description.rstrip().split('#TASK') if x != ""]

        #define the output file name as <jira_ticket> _ <task_id> _ date_time_stamp .py
        string_date = datetime.now(pytz.timezone('US/Eastern')).strftime("%b_%d_%Y_%I_%M_%S_%p")
        

        #Send each task to chatgpt to generate a list of functions necessary to fulfill the description
        bullet_list=[]

        #loop over each task in the ticket to make separate files
        for index, task_description in enumerate(tasks):

            file_name = jira_ticket_id + f"_TASK{index}_" + string_date + ".py"

            # define the prompt
            prompt =  f"""Generate a list of functions using this description:{task_description}
                            Functions should end with 3 pipes |||, 
                            followed by a short description for each function like this 
                            function_name_1: [Description]|||"""

            # define the max token length of the response based ont he input to not get errors from openAI
            max_token_length = 4050 - len(prompt)
            
            chatgpt_response = openai.ChatCompletion.create(
            model='gpt-3.5-turbo-16k',  # Use the desired engine for ChatGPT
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_token_length,  # Define the maximum length of the generated response
            n=1,  # Specify the number of responses to generate
            stop=None,  # Optionally provide a stop sequence to limit the response
            temperature=0.7,  # Control the randomness of the generated response (0.0 to 1.0)
            )
            
            bullet_list.append(chatgpt_response.choices[0].message.content.strip())
        

            #Send each function from the list to chatgpt to get a list of created functions 
            completed_funcs = []

            for gpt_functions_to_write in bullet_list:
                # split the function list by our custom delimiter
                split_funcs_to_write = gpt_functions_to_write.split('|||')

                functions = []

                ##Send each function to ChatGPT to add a try and except block and a google style docstring
                for function_prompt in split_funcs_to_write:
                    prompt =  f"""For the following input, write a python function including a try/except block. include a google style doc string with type hints.
                                    If Exception occurs, print it and return None. Otherwise return “Success”: '{function_prompt}' Return the function as a message only and no other messages or code."""
                    

                    # define the max token length of the response based ont he input to not get errors from openAI
                    chatgpt_response = openai.ChatCompletion.create(
                    model='gpt-3.5-turbo-16k',  # Use the desired engine for ChatGPT
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=len(prompt),  # Define the maximum length of the generated response
                    n=1,  # Specify the number of responses to generate
                    stop=None,  # Optionally provide a stop sequence to limit the response
                    temperature=0.7,  # Control the randomness of the generated response (0.0 to 1.0)
                    )

                    ##Write the completed function to a dictionary
                    functions.append(f'{chatgpt_response.choices[0].message.content.strip()}\n\n')

            # # Write the content of the Python file
            content = ''
            with open(os.path.join('/tmp',file_name), "w") as file:            
                for funcs in functions:
                    file.write(str(funcs))
                    content = content +funcs

        # Add the new file to the repository
        repo.create_file(path=f'devgpt/{file_name}', 
                        message=f"Add {file_name}", 
                        content=content, 
                        branch=jira_ticket_id)

        # define the branch URL
        branch_url = f"{repo_name}/tree/{jira_ticket_id}"

        #Create and post message to slack
        post_to_slack(f'Your code has been added to the given branch\n{branch_url}', 
                      response_url)

        #Add a comment to a Jira Ticket
        auth_jira.add_comment(issue, f'Your code has been added to the given branch\n{branch_url}')
        #Post message to slack when comment has beem made
        post_to_slack(f"Your comment has been added successfully to issue {project}-{ticket_number}.", 
                      response_url)
    
    #Return error if function did not run through
    except Exception as e:
        print("Error in run_devgpt on line number: ", sys.exc_info()[-1].tb_lineno, "\n", e)
        post_to_slack(f"""An error occured and your command was not completed.\n
                      The Error was on line number {sys.exc_info()[-1].tb_lineno}: {e}""",
                       response_url)



if __name__ == '__main__':
    app.run(port=9099)
