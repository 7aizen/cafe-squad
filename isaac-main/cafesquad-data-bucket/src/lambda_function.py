import re
import os
import csv
import json
import boto3
import logging
import datetime
from io import StringIO
from datetime import datetime

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

def lambda_handler(event, context):
    LOGGER.info(f'Event structure: {event}')
    
    bucket = event['BucketName']
    #bucket = 'de-lon11-cafesquad-cafe-data'
    directory = '2023/11/23'
    
    # columns to be extracted: 'purchase_date_time', 'city', 'customer_name', 'products', 'total_cost', 'pay_method', 'card_numb'    

    # extract csv files into py list of dicts
    def extract_and_clean_sales_data(filename):
        
        source_file = csv.DictReader(StringIO(filename), fieldnames=['purchase_date_time', 'city', 'customer_name', 'products', 'total_cost', 'pay_method', 'card_numb'], delimiter=',')
        source_file = list(source_file)
        return source_file
    
    def extract_CSVs(directory, bucket):
         # extract CSVs to variables from folder
        sales_file = []
        sales_city = []
        # assign directory, iterate over files in that directory
        s3 = boto3.resource('s3')
        my_bucket = s3.Bucket(bucket)
        print('in extract_CSVs2')

        for object_summary in my_bucket.objects.filter(Prefix=directory): # or (Prefix=directory+'/') for only one day 23/11/2023 (Prefix=directory+'/') 
            filename = (object_summary.key) 
            print(filename)
            file = boto3.client('s3').get_object(Bucket=bucket, Key=str(filename))
            csv_file = file['Body'].read().decode('utf-8')
            print(type(csv_file))
            
            sales_city = extract_and_clean_sales_data(csv_file)
            print(type(sales_city))
            sales_file.extend(sales_city)
        return sales_file

    # func to split products on order 
    def split_customers_products(sales_file):
        # regular expression to select/split the drink-price pairs in orders
        pattern = r"([^\d]+ )([\d\.]+)" 
        cafe = [] 
        city_list = []  
        basket = []
        product_list = []
        new_list_of_dicts = []
        product_id = 1
        store_counter = 0 
        for dictionary in sales_file:   
            order_list = []
            for product_price in list(dictionary['products'].split(',')):
                quantity = 1
                # matching regex patern to order strings
                match = re.search(pattern, str(product_price))
                product = match[1].strip('-').strip().strip('-').strip()
                price = match[2].strip()
    
                # check if product already is listed in the product&transaction tables  
                if product in product_list:
    
                    # check for multiple products in the same order
                    if product in order_list:
                        tester = 0 
                        # even though product is in current iteration order, check if it is already\
                        # in product list of dicts 'basket'
                        for record in basket:
                            if record['product'] == product:
                                id = record['product_id']
                                new_dict = {}
                                new_dict['purchase_date_time'] = dictionary['purchase_date_time']
                                new_dict['product_id'] = id

                                # pick cafe table data
                                new_cafe = {} #
                                if dictionary['city'] not in city_list:
                                    city_list.append(dictionary['city'])
                                    new_cafe['city'] = dictionary['city']
                                    store_counter += 1
                                    store_id = store_counter
                                    new_cafe['store_id'] = 'cafe'+str(store_id)
                                    cafe.append(new_cafe)
                                else:
                                    idx = city_list.index(dictionary['city'])
                                    new_cafe['city'] = city_list[idx]
                                    store_id = int(idx + 1)
                                    new_cafe['store_id'] = 'cafe'+str(store_id)
    
                                new_dict['store_id'] = store_id
                                new_dict['quantity'] = quantity
                                new_dict['pay_method'] = dictionary['pay_method']
                                new_list_of_dicts.append(new_dict)
                                order_list.append(product)
                                tester += 1
                        # if product in current iteration order (tester > 0) and not in 'basket' products' list \
                        # add 1 to products quantiy in 'transactions' list of dicts
                        if tester != 0:
                            # count quantity of duplicate product within order
                            quantity += 1
                            already_item_index = order_list.index(product)
                            last_index = len(order_list)-1
                            diff = last_index - already_item_index
                            new_list_of_dicts[-1-diff]['quantity'] = quantity
               
                    # pick existing product_id which is not within current iteration order
                    else:
                        for record in basket:
                            if record['product'] == product:
                                prod_id = record['product_id']
                        new_dict = {}
                        new_dict['purchase_date_time'] = dictionary['purchase_date_time']

                        # pick cafe table data
                        new_cafe = {} #
                        if dictionary['city'] not in city_list:
                            city_list.append(dictionary['city'])
                            new_cafe['city'] = dictionary['city']
                            store_counter += 1
                            store_id = store_counter
                            new_cafe['store_id'] = 'cafe'+str(store_id)
                            cafe.append(new_cafe)
                        else:
                            idx = city_list.index(dictionary['city'])
                            new_cafe['city'] = city_list[idx]
                            store_id = int(idx + 1)
                            new_cafe['store_id'] = 'cafe'+str(store_id)
    
                        new_dict['store_id'] = store_id
                        new_dict['product_id'] = prod_id
                        new_dict['quantity'] = quantity
                        new_dict['pay_method'] = dictionary['pay_method']
                        new_list_of_dicts.append(new_dict)
                        order_list.append(product)
                        
                # add new product to product 'basket' & transaction tables
                else: 
                    product_list.append(product)
                    if order_list == []:
                        order_list.append(product)
                    basket_pair = {}
                    basket_pair['product_id'] = product_id
                    basket_pair['product'] = product
                    basket_pair['price'] = price
                    basket.append(basket_pair)
                    new_dict = {}
                    new_dict['purchase_date_time'] = dictionary['purchase_date_time']

                    # pick cafe table data
                    new_cafe = {} 
                    if dictionary['city'] not in city_list:
                        city_list.append(dictionary['city'])
                        new_cafe['city'] = dictionary['city']
                        store_counter += 1
                        store_id = store_counter
                        new_cafe['store_id'] = 'cafe'+str(store_id)
                        cafe.append(new_cafe)
                    else:
                        idx = city_list.index(dictionary['city'])
                        new_cafe['city'] = city_list[idx]
                        store_id = int(idx + 1)
                        new_cafe['store_id'] = 'cafe'+str(store_id)
                        
                    # update order with a current product
                    new_dict['store_id'] = store_id
                    new_dict['product_id'] = product_id
                    product_id += 1 
                    new_dict['quantity'] = quantity
                    new_dict['pay_method'] = dictionary['pay_method']
                    new_list_of_dicts.append(new_dict)
                    order_list.append(product)
                my_dict = {i:order_list.count(i) for i in order_list}
                max_value = max(my_dict, key=my_dict.get)
                print(my_dict[str(max_value)])
                
    #    # print product 'basket' & transaction tables
    #    print('                      Basket Table:\n')
    #    #print(basket)
    #    print(tabulate(basket, headers="keys")) 
    #    print('\n                        Transaction Table:\n')
    #    print(tabulate(new_list_of_dicts, headers="keys")) 
    #    print(len(basket))
        return new_list_of_dicts, basket, cafe
    
    # func to adapt datetime col to SQL format 
    def convert_all_dates(list_of_dicts, date_cols,
                          current_format='%d/%m/%Y %H:%M',
                          expected_format='%Y-%m-%d %H:%M:00'):
        # Uniformity
        for dict in list_of_dicts:
            for col in date_cols:
                try:
                    str_to_date = datetime.strptime(dict[col], current_format)
                    date_to_str = datetime.strptime(str(str_to_date), expected_format)
                    sql_datetime = date_to_str.strftime('%Y-%m-%d %H:%M')
                    dict[col] = sql_datetime
                except ValueError as e:
                    print(f"Error parsing value '{dict[col]}' in column '{col}': {e}")
                    dict[col] = None
    
        return list_of_dicts
    
    # func to error check for price floats
    def check_float_columns(list_of_dicts, float_cols):
        # Validity
        for dict in list_of_dicts:
            for col in float_cols:
                try:
                    dict[col] = float(dict[col])
                except ValueError as e:
                    print(f"Error parsing value '{dict[col]}' in column '{col}': {e}")
                    dict[col] = None
        return list_of_dicts
    
    # func to drop duplicate records
    def drop_duplicates(list_of_dicts):
        # Validity
        id_list = []
        list_with_unique_ids = []
        for dict in list_of_dicts:
            if dict['products'] not in id_list:
                id_list.append(dict['products'])
                list_with_unique_ids.append(dict)
        return list_with_unique_ids
    
    # func to remove records with null fields for relevant cols
    def drop_rows_with_null(list_of_dicts):
        # Validity / Completeness
        list_with_no_nulls = []
        for dict in list_of_dicts:
            #print(dict)
            dict1 = dict
            del dict['customer_name']
            #dict.pop('customer_name')
            dict2 = dict
            del dict['total_cost']
            #dict.pop('total_cost')
            #print(dict)
            del dict['card_numb']
            #print(dict)
            #dict.pop('card_numb')
            if None not in dict.values() and '' not in dict.values():
                list_with_no_nulls.append(dict)    
        return list_with_no_nulls
    
    # save transaction list of dicts to csv file
    def transactions_csv(sales_file_split):
        # define column names
        column_names = ['date_time', 'cafe_id', 'product_id', 'quantity', 'payment']
        
        csv_buffer = StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=sales_file_split[0].keys())
        writer.writeheader()
        writer.writerows(sales_file_split)
        transactions_csv = csv_buffer.getvalue()
        return transactions_csv

    # save basket list of dicts to csv file
    def basket_csv(basket):
        # define column names
        column_names = ['drink', 'price']
        csv_buffer = StringIO()
        writer = csv.DictWriter(csv_buffer , fieldnames=basket[0].keys())
        writer.writeheader()
        writer.writerows(basket)
        basket_csv = csv_buffer.getvalue()
        return basket_csv

    # save cafe list of dicts to csv file
    def cafe_csv(cafe):
        # define column names
        column_names = ['city', 'cafe_name']
        csv_buffer = StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=cafe[0].keys())
        writer.writeheader()
        writer.writerows(cafe)
        cafe_csv = csv_buffer.getvalue()
        return cafe_csv

    # execute funcs from ETL's extract_transform.py
    sales_file = extract_CSVs(directory, bucket)

    # remove records with relevant null fields
    sales_file = drop_rows_with_null(sales_file)

    # drop duplicate records
    sales_file = drop_duplicates(sales_file) 

    # func to adapt to SQL format with datetime
    sales_file = convert_all_dates(sales_file, ['purchase_date_time'])
    #if sales_file: print('finished')

    # get final database tables' vars
    sales_file_split, basket, cafe = split_customers_products(sales_file) 
    
    def drop_rows_with_null2(list_of_dicts):
        # Validity / Completeness
        list_with_no_nulls = []
        for dict in list_of_dicts:
            if None not in dict.values() and '' not in dict.values() and len(dict) == 5:
                list_with_no_nulls.append(dict)    
        return list_with_no_nulls
    sales_file_split = drop_rows_with_null2(sales_file_split)
  
    # create csv objects corresponding to tables' data
    transactions = transactions_csv(sales_file_split)
    basket = basket_csv(basket)
    cafe = cafe_csv(cafe)
    print(transactions) 

    # upload csv objects to s3/tmp_CSVs in Redshift-db-deployment bucket
    Bucket = 'cafesquad-deployment-bucket'
    s3 = boto3.client('s3')
    s3.put_object(Body=transactions, Bucket=Bucket, Key='tmp_CSVs/transactions.csv')
    s3.put_object(Body=basket, Bucket=Bucket, Key='tmp_CSVs/basket.csv') 
    s3.put_object(Body=cafe, Bucket=Bucket, Key='tmp_CSVs/cafe.csv')
    
    return {
        'statusCode': 200,
        'body': json.dumps('Saved transformed data to CSVs!')
    }

