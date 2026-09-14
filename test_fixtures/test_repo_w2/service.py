from db import connect_db

def process_data():
    conn = connect_db()
    return conn