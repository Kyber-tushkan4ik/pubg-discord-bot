import discord
import sqlite3
import os
import time
import json
import asyncio

DB_FILE = os.path.join(os.path.dirname(__file__), '../database.sqlite')
CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

ACHIEVEMENTS = [
    {
        "id": 'first_blood',
        "name": '🩸 Перша Кров',
        "description": 'Зробити 1+ вбивств.',
        "condition": lambda stats: stats.get('kills', 0) > 0
    },
    {
        "id": 'berserk',
        "name": '😡 Берсерк',
        "description": 'Зробити 10 або більше вбивств за один матч.',
        "condition": lambda stats: stats.get('kills', 0) >= 10
    },
    {
        "id": 'sniper',
        "name": '🎯 Снайпер',
        "description": 'Вбити ворога з відстані більше 300 метрів.',
        "condition": lambda stats: stats.get('longestKill', 0) >= 300
    },
    {
        "id": 'medic',
        "name": '🚑 Польовий Лікар',
        "description": 'Підняти (revive) 3 або більше союзників.',
        "condition": lambda stats: stats.get('revives', 0) >= 3
    },
    {
        "id": 'terminator',
        "name": '🤖 Термінатор',
        "description": 'Нанести більше 1000 урону за матч.',
        "condition": lambda stats: stats.get('damageDealt', 0) >= 1000
    }
]

async def check_achievements(client: discord.Client, user_id: str, pubg_nickname: str, stats: dict, channel_id: str = None):
    unlocked = [ach for ach in ACHIEVEMENTS if ach["condition"](stats)]
    if not unlocked:
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT achievementId FROM achievements WHERE userId = ?", (user_id,))
        owned_ids = [row[0] for row in cursor.fetchall()]
        
        new_achievements = [ach for ach in unlocked if ach["id"] not in owned_ids]
        
        if new_achievements:
            now = int(time.time() * 1000)
            target_channel_id = channel_id or CONFIG.get("WIN_NOTIF_CHANNEL_ID")
            channel = client.get_channel(int(target_channel_id)) if target_channel_id else None
            
            for ach in new_achievements:
                cursor.execute(
                    "INSERT INTO achievements (userId, achievementId, dateEarned) VALUES (?, ?, ?)",
                    (user_id, ach["id"], now)
                )
                
                if channel:
                    embed = discord.Embed(
                        title='🏆 Нове Досягнення!',
                        description=f'Гравець **{pubg_nickname}** отримав досягнення **{ach["name"]}**!',
                        color=0xFFD700
                    )
                    embed.add_field(name='Опис', value=ach["description"])
                    await channel.send(embed=embed)
                    await asyncio.sleep(2.0) # Затримка проти спаму
                    
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Помилка перевірки досягнень: {e}")
