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
_error_callback = None

def init_db():
    global user_data
    conn = sqlite3.connect(DB_FILE)
    conn.execute('PRAGMA journal_mode=WAL;') # Увімкнення WAL режиму
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS weapons (
            id TEXT PRIMARY KEY,
            name TEXT,
            damage REAL,
            velocity REAL,
            fireRate REAL,
            reloadTime REAL,
            btk INTEGER DEFAULT 4
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS news_feed (
            id TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            date INTEGER,
            type TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reported_matches (
            matchId TEXT PRIMARY KEY,
            dateReported INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS economy (
            userId TEXT PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_stats (
            userId TEXT PRIMARY KEY,
            weeklyMessages INTEGER DEFAULT 0,
            totalMessages INTEGER DEFAULT 0,
            weeklyVoiceTime INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            userId TEXT,
            username TEXT,
            ideaText TEXT,
            timestamp INTEGER,
            status TEXT DEFAULT 'pending'
        )
    ''')
    try:
        cursor.execute("ALTER TABLE ideas ADD COLUMN status TEXT DEFAULT 'pending'")
    except sqlite3.OperationalError:
        pass # Колонка вже існує

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracked_players (
            nickname TEXT PRIMARY KEY COLLATE NOCASE,
            added_at INTEGER
        )
    ''')

    # Ініціалізація базової статистики зброї (за офіційними даними наближено для 2-го рівня броні)
    cursor.execute("SELECT count(*) FROM weapons")
    if cursor.fetchone()[0] == 0:
        base_weapons = [
            ("m416", "M416", 40.0, 880.0, 0.086, 2.1, 5),
            ("beryl", "Beryl M762", 44.0, 715.0, 0.086, 2.9, 4),
            ("akm", "AKM", 47.0, 715.0, 0.100, 2.9, 4),
            ("aug", "AUG", 41.0, 940.0, 0.086, 3.0, 5),
            ("kar98k", "Kar98k", 79.0, 760.0, 1.900, 4.0, 2),
            ("m24", "M24", 75.0, 790.0, 1.800, 4.2, 2),
            ("mini14", "Mini 14", 48.0, 990.0, 0.100, 3.6, 3),
            ("slr", "SLR", 56.0, 840.0, 0.100, 3.68, 3),
            ("sks", "SKS", 53.0, 800.0, 0.090, 2.9, 3)
        ]
        cursor.executemany('''
            INSERT INTO weapons (id, name, damage, velocity, fireRate, reloadTime, btk)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', base_weapons)
        print("[DataHandler] Initialized base weapons data.")
    
    
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

def save_data_sync(to_save):
    if not to_save: return
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
        if _error_callback:
            _error_callback("Збереження бази даних (SQLite)", e)

async def save_data():
    global _is_saving, _dirty_keys
    if _is_saving or not _dirty_keys:
        return
    _is_saving = True
    
    # Снепшот тільки змінених ключів (виконується в async loop)
    to_save = {k: user_data[k].copy() for k in list(_dirty_keys) if k in user_data}
    _dirty_keys.clear()
    
    if not to_save:
        _is_saving = False
        return
        
    try:
        await asyncio.to_thread(save_data_sync, to_save)
    finally:
        _is_saving = False

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

def delete_user_all_data_sync(user_id: str):
    """Видаляє всі дані КОНКРЕТНОГО користувача з усіх таблиць бази даних."""
    uid = str(user_id)

    # Видаляємо з in-memory кешу лише записи цього користувача.
    # Ключ має формат "userId-guildId" — перевіряємо обидва варіанти:
    # 1) key == uid (legacy-ключ без гільдії)
    # 2) key починається з "uid-" (стандартний ключ userId-guildId)
    keys_to_remove = [
        k for k in list(user_data.keys())
        if k == uid or (str(k).startswith(uid + '-') and str(k).split('-')[0] == uid)
    ]
    for k in keys_to_remove:
        del user_data[k]
        _dirty_keys.discard(k)

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Кожен DELETE прив'язаний до конкретного userId — видаляємо тільки його
        cursor.execute("DELETE FROM users WHERE userId = ?", (uid,))
        cursor.execute("DELETE FROM voice_stats WHERE userId = ?", (uid,))
        cursor.execute("DELETE FROM achievements WHERE userId = ?", (uid,))
        cursor.execute(
            "DELETE FROM playmates WHERE user1_id = ? OR user2_id = ?",
            (uid, uid)
        )
        cursor.execute("DELETE FROM economy WHERE userId = ?", (uid,))
        cursor.execute("DELETE FROM activity_stats WHERE userId = ?", (uid,))
        conn.commit()
        conn.close()
        print(f"[DataHandler] Видалено всі дані для userId={uid}")
    except Exception as e:
        print(f"[DataHandler] Помилка при видаленні даних userId={uid}: {e}")

async def delete_user_all_data(user_id: str):
    """Асинхронна обгортка для видалення всіх даних конкретного користувача."""
    await asyncio.to_thread(delete_user_all_data_sync, user_id)

def increment_playmate_relation_sync(u1, u2):
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

async def increment_playmate_relation(u1, u2):
    await asyncio.to_thread(increment_playmate_relation_sync, u1, u2)

def get_frequent_playmates_sync(user_id):
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

async def get_frequent_playmates(user_id):
    return await asyncio.to_thread(get_frequent_playmates_sync, user_id)

def is_match_reported_sync(match_id):
    """Перевіряє, чи було вже відправлено сповіщення про цей матч."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM reported_matches WHERE matchId = ?", (match_id,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    except Exception as e:
        print(f"[DataHandler] Error checking reported match: {e}")
        return False

async def is_match_reported(match_id):
    return await asyncio.to_thread(is_match_reported_sync, match_id)

def mark_match_reported_sync(match_id):
    """Позначає матч як такий, про який вже відправлено сповіщення."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO reported_matches (matchId, dateReported) VALUES (?, ?)", 
                       (match_id, int(time.time() * 1000)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error marking match as reported: {e}")

async def mark_match_reported(match_id):
    await asyncio.to_thread(mark_match_reported_sync, match_id)

def get_achievement_stats_sync():
    """Повертає статистику досягнень: список (userId, count)."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT userId, COUNT(*) as count 
            FROM achievements 
            GROUP BY userId 
            ORDER BY count DESC
        ''')
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"[DataHandler] Error getting achievement stats: {e}")
        return []

async def get_achievement_stats():
    return await asyncio.to_thread(get_achievement_stats_sync)

def clear_achievements_sync(ids_to_delete=None):
    """
    Видаляє записи з таблиці досягнень.
    Якщо ids_to_delete вказано, видаляє лише ці ID.
    Якщо не вказано — видаляє всі.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        if ids_to_delete:
            placeholders = ', '.join(['?'] * len(ids_to_delete))
            cursor.execute(f"DELETE FROM achievements WHERE achievementId IN ({placeholders})", ids_to_delete)
        else:
            cursor.execute("DELETE FROM achievements")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error clearing achievements: {e}")

async def clear_achievements(ids_to_delete=None):
    await asyncio.to_thread(clear_achievements_sync, ids_to_delete)

# --- Economy & Activity Stats ---
def get_balance_sync(user_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM economy WHERE userId = ?", (str(user_id),))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception as e:
        print(f"[DataHandler] Error getting balance: {e}")
        return 0

async def get_balance(user_id):
    return await asyncio.to_thread(get_balance_sync, user_id)

def add_balance_sync(user_id, amount):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO economy (userId, balance) 
            VALUES (?, ?) 
            ON CONFLICT(userId) DO UPDATE SET balance = balance + ?
        ''', (str(user_id), amount, amount))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error adding balance: {e}")

async def add_balance(user_id, amount):
    await asyncio.to_thread(add_balance_sync, user_id, amount)

def add_message_stat_sync(user_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO activity_stats (userId, weeklyMessages, totalMessages, weeklyVoiceTime) 
            VALUES (?, 1, 1, 0) 
            ON CONFLICT(userId) DO UPDATE SET 
                weeklyMessages = weeklyMessages + 1,
                totalMessages = totalMessages + 1
        ''', (str(user_id),))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error adding message stat: {e}")

async def add_message_stat(user_id):
    await asyncio.to_thread(add_message_stat_sync, user_id)

def add_weekly_voice_stat_sync(user_id, duration_ms):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO activity_stats (userId, weeklyMessages, totalMessages, weeklyVoiceTime) 
            VALUES (?, 0, 0, ?) 
            ON CONFLICT(userId) DO UPDATE SET 
                weeklyVoiceTime = weeklyVoiceTime + ?
        ''', (str(user_id), duration_ms, duration_ms))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error adding voice stat: {e}")

async def add_weekly_voice_stat(user_id, duration_ms):
    await asyncio.to_thread(add_weekly_voice_stat_sync, user_id, duration_ms)

def reset_weekly_activity_sync():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE activity_stats SET weeklyMessages = 0, weeklyVoiceTime = 0")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error resetting weekly activity: {e}")

async def reset_weekly_activity():
    await asyncio.to_thread(reset_weekly_activity_sync)

def get_top_activity_sync():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT userId, weeklyMessages, weeklyVoiceTime 
            FROM activity_stats 
            WHERE weeklyMessages > 0 OR weeklyVoiceTime > 0
        ''')
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"[DataHandler] Error getting top activity: {e}")
        return []

async def get_top_activity():
    return await asyncio.to_thread(get_top_activity_sync)

# --- Ideas System ---
def add_idea_sync(user_id, username, idea_text):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO ideas (userId, username, ideaText, timestamp) 
            VALUES (?, ?, ?, ?)
        ''', (str(user_id), str(username), str(idea_text), int(time.time() * 1000)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error adding idea: {e}")

async def add_idea(user_id, username, idea_text):
    await asyncio.to_thread(add_idea_sync, user_id, username, idea_text)

def get_all_ideas_sync():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, userId, username, ideaText, timestamp FROM ideas ORDER BY timestamp ASC")
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"[DataHandler] Error getting ideas: {e}")
        return []

async def get_all_ideas():
    return await asyncio.to_thread(get_all_ideas_sync)

def get_ideas_by_status_sync(status):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, userId, username, ideaText, timestamp, status FROM ideas WHERE status = ? ORDER BY timestamp ASC", (status,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"[DataHandler] Error getting ideas by status: {e}")
        return []

async def get_ideas_by_status(status):
    return await asyncio.to_thread(get_ideas_by_status_sync, status)

def update_idea_status_sync(idea_id, new_status):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE ideas SET status = ? WHERE id = ?", (new_status, idea_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error updating idea status: {e}")

async def update_idea_status(idea_id, new_status):
    await asyncio.to_thread(update_idea_status_sync, idea_id, new_status)

def delete_idea_sync(idea_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error deleting idea: {e}")

async def delete_idea(idea_id):
    await asyncio.to_thread(delete_idea_sync, idea_id)

def clear_all_ideas_sync():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ideas")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error clearing all ideas: {e}")

async def clear_all_ideas():
    await asyncio.to_thread(clear_all_ideas_sync)

# --- Activity Tracker ---
def add_tracked_player_sync(nickname: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO tracked_players (nickname, added_at) 
            VALUES (?, ?)
        ''', (nickname.strip(), int(time.time() * 1000)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error adding tracked player: {e}")

async def add_tracked_player(nickname: str):
    await asyncio.to_thread(add_tracked_player_sync, nickname)

def remove_tracked_player_sync(nickname: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tracked_players WHERE nickname = ? COLLATE NOCASE", (nickname.strip(),))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DataHandler] Error removing tracked player: {e}")

async def remove_tracked_player(nickname: str):
    await asyncio.to_thread(remove_tracked_player_sync, nickname)

def get_all_tracked_players_sync():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT nickname FROM tracked_players")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        print(f"[DataHandler] Error getting tracked players: {e}")
        return []

async def get_all_tracked_players():
    return await asyncio.to_thread(get_all_tracked_players_sync)

# Викликаємо ініціалізацію при імпорті модуля
import time
init_db()
load_settings()
