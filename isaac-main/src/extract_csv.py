# Script to extract csv files into py variables of ETL project's pipeline
# interfacing cleansing/transforming in transform.py with Isaac's extract-csv script below ###########

# import required modules
import os
import csv

# cols to be extracted: 'purchase_date_time', 'city', 'customer_name', 'products', 'total_cost', 'pay_method', 'card_numb'    

# extract csv files into py list of dicts
def extract_and_clean_sales_data(file_name):
    try:
        with open(file_name, 'r') as file:
            source_file = csv.DictReader(file, fieldnames=['purchase_date_time', 'city', 'customer_name', 'products', 'total_cost', 'pay_method', 'card_numb'], delimiter=',')
            source_file = list(source_file) 
            #next(source_file) #ignore the header row 
            #print((source_file))
    except Exception as ex:
        print("Failed to: " + str(ex))
    return source_file

# extract csv files from folder
def extract_CSVs():
     # extract CSVs to variables from folder
    sales_file = []
    sales_city = []
    # assign directory
    directory = '../csv_data'
    # iterate over files in
    # that directory
    for filename in os.listdir(directory):
        f = os.path.join(directory, filename)
        # checking if it is a file
        if os.path.isfile(f):
            sales_city = extract_and_clean_sales_data(f)
            sales_file.extend(sales_city)
    return sales_file
   
