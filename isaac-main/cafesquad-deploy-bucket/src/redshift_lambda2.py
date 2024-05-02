import json
import boto3 # library used to access AWS API
import os
import csv
import logging
import load_postgres

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

def lambda_handler(event, context):
    LOGGER.info(f'Event structure: {event}')

    # bucket = event['BucketName']
    bucket = 'cafesquad-deployment-bucket'

    ssm_client = boto3.client('ssm')  
    param_name = 'cafesquad_redshift_settings' 
    param_pass = 'redshift-cluster-master-pass'
    def get_ssm_param(param_name):
        parameter_details = ssm_client.get_parameter(Name=param_name)
        redshift_details = json.loads(parameter_details['Parameter']['Value'])
        #print(f'get_ssm_param loaded for db={db}, user={user}, host={host}')
        return redshift_details
    host_name = get_ssm_param(param_name)['host']
    user_name = get_ssm_param(param_name)['user']
    password = get_ssm_param(param_pass)['password']
    db =   get_ssm_param(param_name)['database-name']
    connection = setup_db_connection(host_name, user_name, password, db)
    
    s3 = boto3.resource('s3')

    mykey = '/tmp/transactions.csv'
    s3.meta.client.download_file(bucket, 'transactions.csv', mykey)
    # create the table
    create_transaction_table(connection)
    # load transactions list of dicts from csv file
    with open("transactions.csv", 'r') as file:
        tran_dictionary = csv.DictReader(file)
        sales_file_split = list(tran_dictionary)
    # populate the table
    insert_transactions(connection, sales_file_split)

    mykey = '/tmp/cafe.csv'
    s3.meta.client.download_file(bucket, 'cafe.csv', mykey)
    # create the table
    create_cafe_table(connection)
    # load cafe list of dicts from csv file
    with open("cafe.csv", 'r') as file:
        cafe = csv.DictReader(file)
        cafe = list(cafe)
    # populate the table
    insert_cafe(connection, cafe)

    mykey = '/tmp/basket.csv'
    s3.meta.client.download_file(bucket, 'basket.csv', mykey)
    # create the table
    create_basket_table(connection)
    # load basket list of dicts from csv file
    with open("basket.csv", 'r') as file:
        basket = csv.DictReader(file)
        basket = list(basket)
    # populate the table
    insert_basket(connection, basket)