import sys
import os
import json
import discord
from discord import app_commands
from datetime import datetime

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

LOG_FILE = os.path.join(os.path.dirname(__file__), '../logs.txt')

def is_admin_check(interaction: discord.Interaction) -> bool:
    """Перевіряє чи є користувач адміністратором або модератором."""
    roles_admin = CONFIG.get("ROLES_ADMIN", [])
    has_role = any(r.name in roles_admin for r in interaction.user.roles)
    is_server_admin = interaction.user.guild_permissions.administrator
    return has_role or is_server_admin

def is_admin():
    """Декоратор для перевірки прав адміністратора."""
    return app_commands.check(is_admin_check)

def create_log(message: str):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {message}"
    try:
        print(log_line)
    except UnicodeEncodeError:
        print(log_line.encode('ascii', errors='replace').decode('ascii'))
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except Exception as e:
        print(f"Failed to write log: {e}")

def ms_to_readable(ms: int) -> str:
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    return f"{hours}год {minutes}хв"

def get_record_key(user_id: str, guild_id: str) -> str:
    return f"{user_id}-{guild_id}"

def find_record(user_data: dict, user_id: str, guild_id: str):
    key = get_record_key(user_id, guild_id)
    if key in user_data:
        return user_data[key]
    if user_id in user_data:  # Legacy support
        return user_data[user_id]
    return None
