# Script to perform transfer task of ETL project's pipeline

# import required modules
import csv
from datetime import datetime
#from load_mysql import * 
from load_postgres import * # load_postgres' modules: setup_db_connection, truncate_tables, create_cafe_table, create_basket_table, create_transaction_table
from extract_csv import *   # modules: extract_and_clean_sales_data, extract_CSVs
import re
import os
import pprint
from tabulate import tabulate
pp = pprint.PrettyPrinter(indent=2)

# func to split products on order 
def split_customers_products(sales_file):
    # regular expression to select/split the drink-price pairs in orders
    pattern = r"([^\d]+ )([\d\.]+)"  
    basket = []
    product_list = []
    new_list_of_dicts = []
    product_id = 1
    for dictionary in sales_file:   
        order_list = []
        for product_price in list(dictionary['products'].split(',')):
            quantity = 1
            # matching regex patern to order strings
            match = re.search(pattern, str(product_price))
            product = match[1].strip('-').strip().strip('-').strip()
            price = match[2].strip()

            # check if product already is listed in the product & transaction tables  
            if product in product_list:

                # check for multiple products in the same order
                if product in order_list:
                    tester = 0 
                    # even though product is in current iteration order check if is already\
                    # in product list of dicts 'basket'
                    for record in basket:
                        if record['product'] == product:
                            id = record['product_id']
                            new_dict = {}
                            new_dict['product_id'] = id
                            new_dict['purchase_date_time'] = dictionary['purchase_date_time']
                            if dictionary['city'] == 'Leeds':
                                store_id = 2
                            else:
                                store_id = 1
                            new_dict['store_id'] = store_id
                            new_dict['quantity'] = quantity
                            new_dict['pay_method'] = dictionary['pay_method']
                            new_list_of_dicts.append(new_dict)
                            order_list.append(product)
                            tester += 1
                    # if product in current iteration order (tester >0) and not in 'basket' products' list \
                    # add 1 to products quantiy in 'transactions' list of dicts
                    if tester != 0:
                        # count quantity of duplicate product within order
                        quantity += 1
                        already_item_index = order_list.index(product)
                        last_index = len(order_list)-1
                        diff = last_index - already_item_index
                        new_list_of_dicts[-1-diff]['quantity'] = quantity
           
                # pick existing product_id which is not withiin current iteration order
                else:
                    for record in basket:
                        if record['product'] == product:
                            prod_id = record['product_id']
                    new_dict = {}
                    new_dict['purchase_date_time'] = dictionary['purchase_date_time']
                    if dictionary['city'] == 'Leeds':
                        store_id = 2
                    else:
                        store_id = 1
                    new_dict['store_id'] = store_id
                    new_dict['product_id'] = prod_id
                    new_dict['quantity'] = quantity
                    new_dict['pay_method'] = dictionary['pay_method']
                    #print('\nnew order:', new_dict)
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
                if dictionary['city'] == 'Leeds':
                    store_id = 2
                else:
                    store_id = 1
                new_dict['store_id'] = store_id
                new_dict['product_id'] = product_id
                product_id += 1 
                #print(product_id)
                new_dict['quantity'] = quantity
                new_dict['pay_method'] = dictionary['pay_method']
                #print('\nnew order:', new_dict)
                new_list_of_dicts.append(new_dict)

    # print product 'basket' & transaction tables
    print('                      Basket Table:\n')
    #print(basket)
    print(tabulate(basket, headers="keys")) 
    print('\n                        Transaction Table:\n')
    print(tabulate(new_list_of_dicts, headers="keys")) 
    print(len(basket))
    return new_list_of_dicts, basket 

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

# optional fields validity func if required
#def check_values_in_valid_list(list_of_dicts, valid_items, col_name):
#    # Validity
#    for dict in list_of_dicts:
#        if dict[col_name] in valid_items:
#            continue
#        else:
#            dict[col_name] = None
#    return list_of_dicts
    
# script execution part
if __name__ == '__main__':
    # setup connection
    connection = setup_db_connection() 

    # make sure tables are empty at and next runtimes
    drop_tables(connection)                               # <- ###### drop tables #######
        
    #construct empty tables
    create_cafe_table(connection)
    create_basket_table(connection)
    create_transaction_table(connection)

    # extract data from csv files (in imported module: extract_csv.py)
    sales_file = extract_CSVs()
   
    # error check for the price col
    sales_file = check_float_columns(sales_file, ['total_cost'])
    #print(len(sales_file))

    # remove records with relevant null fields
    sales_file = drop_rows_with_null(sales_file)

    # drop duplicate records
    sales_file = drop_duplicates(sales_file) 

    # func to adapt to SQL format with datetime
    sales_file = convert_all_dates(sales_file, ['purchase_date_time'])
    #if sales_file: print('finished')

    # get database tables' vars
    sales_file_split, basket = split_customers_products(sales_file) 

    ###### might need below snippet to test fields validity (called by optional function placed in pipeline - see above) ############
    #teacher_list = ['Mrs. X', 'Ms. Smith', 'Mr. G']
    #sales_file_split = check_values_in_valid_list(sales_file_split, teacher_list, 'teacher')
    
    # populate the tables with python vars
    insert_cafe(connection)  
    ##insert_cafe(connection,...)      # <- adapt to big data wit reading in from many CSVs ######
    insert_basket(connection, basket)  
    insert_transactions(connection, sales_file_split) 
    connection.close()                              
