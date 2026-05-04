import sys
import os
import json
import discord
import logging
from logging.handlers import RotatingFileHandler
import time
import asyncio
import traceback
from discord import app_commands
from datetime import datetime, timedelta

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

LOG_FILE = os.path.join(os.path.dirname(__file__), '../logs.txt')

# Налаштування логера з ротацією (5 MB, 3 бекапи)
logger = logging.getLogger("PubgBot")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
logger.addHandler(handler)

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
    """Логує повідомлення у консоль та файл з ротацією."""
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
    except UnicodeEncodeError:
        pass # print(message.encode('ascii', errors='replace').decode('ascii'))
    
    try:
        logger.info(message)
    except Exception as e:
        print(f"Failed to write log: {e}")

def cleanup_old_assets(max_age_hours=24):
    """Видаляє старі тимчасові зображення з папки assets."""
    assets_dir = os.path.join(os.path.dirname(__file__), '../assets')
    if not os.path.exists(assets_dir):
        return
    
    count = 0
    now = time.time()
    for filename in os.listdir(assets_dir):
        if filename.startswith('victory_') and filename.endswith('.png'):
            file_path = os.path.join(assets_dir, filename)
            # Не чіпаємо шаблони victory_card_N.png
            if 'card_' in filename:
                continue
                
            try:
                if os.path.isfile(file_path):
                    file_age = now - os.path.getmtime(file_path)
                    if file_age > (max_age_hours * 3600):
                        os.remove(file_path)
                        count += 1
            except Exception as e:
                create_log(f"[CLEANUP ERROR] {filename}: {e}")
    
    if count > 0:
        create_log(f"[CLEANUP] Видалено {count} старих зображень перемог.")

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

def translate_map(map_id: str) -> str:
    """Перекладає ідентифікатор карти PUBG у зрозумілу назву."""
    if not map_id:
        return "PUBG"
    maps = CONFIG.get("MAP_NAMES", {})
    return maps.get(map_id, map_id)

_error_cooldowns = {}

async def notify_admin_error(bot, context: str, exception: Exception):
    """Надсилає повідомлення про помилку власнику бота (або вказаному адміну)."""
    now = time.time()
    error_str = str(exception)
    
    # Запобігаємо спаму (1 раз на 10 хвилин для однакових помилок)
    err_hash = f"{context}-{type(exception).__name__}"
    if err_hash in _error_cooldowns and now - _error_cooldowns[err_hash] < 600:
        return
    _error_cooldowns[err_hash] = now

    try:
        app_info = await bot.application_info()
        owner = app_info.owner
        
        # Аналіз помилки для підказок
        hint = ""
        color = 0xFF0000
        if "No space left on device" in error_str or "database or disk is full" in error_str:
            hint = "🚨 **Критична помилка:** На сервері закінчилося місце! Негайно звільніть пам'ять або збільште тариф."
            color = 0x8B0000
        elif "429 Too Many Requests" in error_str:
            hint = "🚨 **Блокування API:** Бот надсилає занадто багато запитів (спам). Discord заблокував IP. Зменште швидкість розсилок."
            color = 0xFF8C00
        elif "OperationalError" in str(type(exception)):
            hint = "⚠️ **Помилка бази даних:** Проблема зі збереженням чи читанням (можливо, блокування файлу)."
            
        tb = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
        # Обрізаємо занадто довгий traceback
        if len(tb) > 1000:
            tb = tb[-1000:]
            
        embed = discord.Embed(
            title=f"⚠️ Збій системи: {context}",
            description=f"**Помилка:** `{type(exception).__name__}: {exception}`\n\n{hint}",
            color=color
        )
        embed.add_field(name="Стек викликів", value=f"```python\n{tb}\n```", inline=False)
        embed.set_footer(text=f"Час збою: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        await owner.send(embed=embed)
    except Exception as e:
        create_log(f"[FATAL ERROR] Не вдалося надіслати сповіщення власнику: {e}")
