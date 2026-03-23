import json
import os

MOD_LOGS_PATH = os.path.join(os.path.dirname(__file__), '../mod_logs.json')

def get_mod_logs():
    if not os.path.exists(MOD_LOGS_PATH):
        return {}
    with open(MOD_LOGS_PATH, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except:
            return {}

def save_mod_logs(data):
    with open(MOD_LOGS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

async def add_warning(bot, guild_id: str, user_id: str, reason: str):
    logs = get_mod_logs()
    if user_id not in logs:
        logs[user_id] = {"warns": 0, "history": []}
    
    logs[user_id]["warns"] += 1
    logs[user_id]["history"].append(reason)
    save_mod_logs(logs)
    return logs[user_id]["warns"]

async def clear_warnings(user_id: str):
    logs = get_mod_logs()
    if user_id in logs:
        logs[user_id]["warns"] = 0
        save_mod_logs(logs)
        return True
    return False
