import sqlite3
import json
import os
import asyncio

# Шляхи до бази даних та налаштувань (в кореневій папці)
DB_FILE = os.path.join(os.path.dirname(__file__), '../database.sqlite')
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), '../settings.json')

user_data = {}
bot_settings = {"ytmSource": None}
_is_saving = False
_dirty_keys = set()

def init_db():
    global user_data
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            key TEXT PRIMARY KEY,
            userId TEXT,
            guildId TEXT,
            pubgNickname TEXT,
            totalPlayTime INTEGER DEFAULT 0,
            isActive INTEGER DEFAULT 0,
            jsonData TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS voice_stats (
            userId TEXT PRIMARY KEY,
            totalTime INTEGER DEFAULT 0,
            lastJoin INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS achievements (
            userId TEXT,
            achievementId TEXT,
            dateEarned INTEGER,
            PRIMARY KEY (userId, achievementId)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id TEXT PRIMARY KEY,
            type TEXT,
            value REAL,
            holderId TEXT,
            holderName TEXT,
            date INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS playmates (
            user1_id TEXT,
            user2_id TEXT,
            count INTEGER DEFAULT 1,
            PRIMARY KEY (user1_id, user2_id)
        )
    ''')
    
    print("[DataHandler] Loading data from SQLite...")
    cursor.execute("SELECT * FROM users")
    rows = cursor.fetchall()
    
    new_user_data = {}
    count = 0
    for row in rows:
        key, user_id, guild_id, pubg_nick, total_time, is_active, json_data = row
        try:
            if json_data:
                new_user_data[key] = json.loads(json_data)
                count += 1
        except Exception as e:
            print(f"[DataHandler] Failed to parse JSON for key {key}: {e}")
            
    user_data = new_user_data
    _dirty_keys.clear()
    print(f"[DataHandler] Loaded {count} users.")
    
    conn.commit()
    conn.close()

def mark_dirty(key):
    """Помічає дані користувача як змінені."""
    global _dirty_keys
    _dirty_keys.add(key)

def load_settings():
    global bot_settings
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                bot_settings = json.load(f)
    except Exception as e:
        bot_settings = {"ytmSource": None}

def get_data():
    return user_data

def get_settings():
    return bot_settings

def save_data_sync():
    global _is_saving, _dirty_keys
    if _is_saving or not _dirty_keys:
        return
    _is_saving = True
    
    # Снепшот тільки змінених ключів
    to_save = {k: user_data[k] for k in list(_dirty_keys) if k in user_data}
    _dirty_keys.clear()
    
    if not to_save:
        _is_saving = False
        return
        
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("BEGIN TRANSACTION")
        
        for key, user in to_save.items():
            u_id = user.get("userId")
            g_id = user.get("guildId")
            
            if not u_id and '-' in str(key):
                u_id = str(key).split('-')[0]
            elif not u_id:
                u_id = key
                
            if not g_id and '-' in str(key):
                g_id = str(key).split('-')[1]
                
            pubg_nickname = user.get("pubgNickname")
            total_play_time = user.get("totalPlayTime", 0)
            is_active = 1 if user.get("isActive") else 0
            json_str = json.dumps(user)
            
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (key, userId, guildId, pubgNickname, totalPlayTime, isActive, jsonData) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (key, u_id, g_id, pubg_nickname, total_play_time, is_active, json_str))
            
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Save Failed: {e}")
    finally:
        _is_saving = False

async def save_data():
    # Асинхронна абстракція над синхронним збереженням
    await asyncio.to_thread(save_data_sync)

def save_settings_sync():
    try:
        temp = f"{SETTINGS_FILE}.tmp"
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(bot_settings, f, indent=2)
        os.replace(temp, SETTINGS_FILE)
    except Exception as e:
        print(f"Settings Save Failed: {e}")

async def save_settings():
    await asyncio.to_thread(save_settings_sync)

def delete_data_sync(key):
    if key in user_data:
        del user_data[key]
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE key = ?", (key,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[deleteData] Failed to delete: {e}")

async def delete_data(key):
    await asyncio.to_thread(delete_data_sync, key)

def increment_playmate_relation(u1, u2):
    """Збільшує лічильник спільних ігор для двох користувачів."""
    try:
        ids = sorted([str(u1), str(u2)])
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO playmates (user1_id, user2_id, count)
            VALUES (?, ?, 1)
            ON CONFLICT(user1_id, user2_id) DO UPDATE SET count = count + 1
        ''', (ids[0], ids[1]))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error incrementing playmate relation: {e}")

def get_frequent_playmates(user_id):
    """Повертає список ID користувачів, з якими даний юзер грав найчастіше."""
    try:
        u_id = str(user_id)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user1_id, user2_id, count FROM playmates
            WHERE user1_id = ? OR user2_id = ?
            ORDER BY count DESC
        ''', (u_id, u_id))
        rows = cursor.fetchall()
        conn.close()
        
        result = []
        for r in rows:
            other = r[1] if r[0] == u_id else r[0]
            result.append(other)
        return result
    except Exception as e:
        print(f"[DataHandler] Error getting frequent playmates: {e}")
        return []

# Викликаємо ініціалізацію при імпорті модуля
init_db()
load_settings()
