# Database tables' loading module imported in transform.py of the project ETL

# import required modules
import psycopg2
import os
from dotenv import load_dotenv

# get login credentials to database
load_dotenv()
host_name =     os.environ.get("postgres_host")
user_name =     os.environ.get("postgres_user")
user_password = os.environ.get("postgres_pass")
database_name = os.environ.get("postgres_db")

# set up database connection object
def setup_db_connection(host=host_name,
                        user=user_name,
                        password=user_password,
                        db=database_name):

    connection = psycopg2.connect(
        host = host,
        database = db,
        user = user,
        password = password)
    return connection

# drop tables to run scripts repeatedly 
def drop_tables(connection): 
    cursor = connection.cursor()
    cursor.execute("""DROP TABLE cafe CASCADE""")
    cursor.execute("""DROP TABLE basket CASCADE""")
    cursor.execute("""DROP TABLE transactions""")
    connection.commit()
    cursor.close()

# Create Cafe table
def create_cafe_table(connection):
    table_cafe = """CREATE TABLE IF NOT EXISTS cafe
        (cafe_id SERIAL PRIMARY KEY,     
        city VARCHAR(255) NOT NULL,   
        cafe_name VARCHAR(255) NOT NULL
        ); 
    """
    cursor = connection.cursor()
    cursor.execute(table_cafe)
    connection.commit()
    cursor.close()
# populate Cafe table
#def insert_cafe(connection, list_of_dicts):     #  <- version form extracting many files
def insert_cafe(connection):
    sql = """
        INSERT INTO cafe (city, cafe_name)
        VALUES ('Chesterfield','Cafe A'),
        ('Leeds','Cafe B');
    """
    #for drink in list_of_dicts:
    #    row = (drink['product'], drink['price'])
    #    cursor.execute(sql, row)
    cursor = connection.cursor()
    cursor.execute(sql)
    connection.commit()
    cursor.close()
    print('Rows inserted.')

# Create Basket table
def create_basket_table(connection):
    table_basket = """CREATE TABLE IF NOT EXISTS basket
    (product_id SERIAL PRIMARY KEY,  
    drink VARCHAR(255) NOT NULL, 
    price NUMERIC(10,2) NOT NULL
    );
   """
    cursor = connection.cursor()
    cursor.execute(table_basket)
    connection.commit()
    cursor.close()

# populate Basket table
def insert_basket(connection, list_of_dicts):
    sql = """
        INSERT INTO basket (drink, price)
        VALUES (%s, %s);
    """
    for drink in list_of_dicts:
        print(drink)
        row = (drink['product'], drink['price'])
        cursor = connection.cursor()
        cursor.execute(sql, row)
    connection.commit()
    cursor.close()
    print('Rows inserted.')

# Create Transaction table 
def create_transaction_table(connection):
    table_transaction = """CREATE TABLE IF NOT EXISTS transactions
        (id SERIAL PRIMARY KEY,           
        date_time TIMESTAMP NOT NULL,  
        cafe_id SERIAL,
        product_id SERIAL,                                
        quantity NUMERIC NOT NULL,        
        payment VARCHAR(50) NOT NULL,  
        FOREIGN KEY (product_id) REFERENCES basket(product_id),  
        FOREIGN KEY (cafe_id) REFERENCES cafe(cafe_id)          
    );
    """
    cursor = connection.cursor()
    cursor.execute(table_transaction)
    connection.commit()
    cursor.close()

# populate Transacttion table
def insert_transactions(connection, list_of_dicts):
    sql = """
        INSERT INTO transactions (date_time, cafe_id, product_id, quantity, payment)
        VALUES (%s, %s, %s, %s, %s);
    """
    #sql_cafe = """SELECT * FROM cafe;"""
    #sql_basket = """SELECT * FROM basket;"""
    #cursor.execute(sql_cafe)
    #cursor.execute(sql_basket)
    cursor = connection.cursor()
    for drink in list_of_dicts:
        row = (drink['purchase_date_time'], drink['store_id'],
            drink['product_id'], drink['quantity'],
            drink['pay_method'])
        cursor.execute(sql, row)
    connection.commit()
    cursor.close()
    print('Rows inserted.')


