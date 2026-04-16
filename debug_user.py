import sqlite3
import json
import os

DB_FILE = 'database.sqlite'

def check_user(user_id):
    if not os.path.exists(DB_FILE):
        print(f"Database file {DB_FILE} not found.")
        return
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Пошук за userId або за ключем (де інколи зберігається ID)
    cursor.execute("SELECT * FROM users WHERE userId = ? OR key LIKE ?", (user_id, f"%{user_id}%"))
    rows = cursor.fetchall()
    
    if not rows:
        print(f"User {user_id} not found in database.")
    else:
        for row in rows:
            key, u_id, g_id, pubg_nick, total_time, is_active, json_data = row
            print(f"Key: {key}, uId: {u_id}, gId: {g_id}, PubgNick: {pubg_nick}, Active: {is_active}")
            if json_data:
                print(f"JSON Data: {json_data}")
    conn.close()

if __name__ == '__main__':
    check_user('776154533742641174')
