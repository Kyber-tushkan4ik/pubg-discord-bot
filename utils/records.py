import sqlite3
import os
import time

DB_FILE = os.path.join(os.path.dirname(__file__), '../database.sqlite')

async def check_records(player: dict, stats: dict):
    records_to_check = [
        {"key": 'max_kills', "val": stats.get('kills', 0)},
        {"key": 'max_damage', "val": stats.get('damageDealt', 0)},
        {"key": 'longest_kill', "val": stats.get('longestKill', 0)},
        {"key": 'max_heal', "val": stats.get('heals', 0)},
        {"key": 'max_time', "val": stats.get('timeSurvived', 0)}
    ]
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM records")
        rows = cursor.fetchall()
        
        current_records = {row[0]: row[2] for row in rows}
            
        for item in records_to_check:
            key = item["key"]
            val = item["val"]
            
            current_val = current_records.get(key)
            
            if current_val is None or val > current_val:
                if val <= 0:
                    continue
                if key == 'max_time' and val < 600:
                    continue
                    
                user_id = player.get("userId") or 'ext'
                pubg_nick = player.get("pubgNickname", 'Unknown')
                now = int(time.time() * 1000)
                
                cursor.execute(
                    "INSERT OR REPLACE INTO records (id, type, value, holderId, holderName, date) VALUES (?, ?, ?, ?, ?, ?)",
                    (key, key, val, user_id, pubg_nick, now)
                )
                print(f"[РЕКОРД] Новий рекорд {key}: {val} від {pubg_nick}")
                
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Помилка перевірки рекордів: {e}")
