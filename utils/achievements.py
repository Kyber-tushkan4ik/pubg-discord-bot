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
    # --- СТАНДАРТНІ ДОСЯГНЕННЯ ---
    {
        "id": 'first_blood',
        "name": '🩸 Перша Кров',
        "description": 'Зробити своє перше вбивство у матчі.',
        "condition": lambda stats: stats.get('kills', 0) > 0,
        "secret": False
    },
    {
        "id": 'berserk',
        "name": '😡 М\'ясник',
        "description": 'Зробити 10 або більше вбивств за один матч.',
        "condition": lambda stats: stats.get('kills', 0) >= 10,
        "secret": False
    },
    {
        "id": 'sniper',
        "name": '🎯 Снайпер',
        "description": 'Вбити ворога з відстані більше 300 метрів.',
        "condition": lambda stats: stats.get('longestKill', 0) >= 300,
        "secret": False
    },
    {
        "id": 'medic',
        "name": '🚑 Польовий Лікар',
        "description": 'Підняти (revive) 3 або більше союзників.',
        "condition": lambda stats: stats.get('revives', 0) >= 3,
        "secret": False
    },
    {
        "id": 'terminator',
        "name": '🤖 Термінатор',
        "description": 'Завдати більше 1000 шкоди за матч.',
        "condition": lambda stats: stats.get('damageDealt', 0) >= 1000,
        "secret": False
    },
    {
        "id": 'headhunter',
        "name": '💀 Мисливець за головами',
        "description": 'Зробити 5 або більше вбивств у голову за матч.',
        "condition": lambda stats: stats.get('headshotKills', 0) >= 5,
        "secret": False
    },
    {
        "id": 'team_player',
        "name": '🤝 Командний гравець',
        "description": 'Зробити 5 або більше асистів (допомог у вбивстві) за матч.',
        "condition": lambda stats: stats.get('assists', 0) >= 5,
        "secret": False
    },
    {
        "id": 'combat_medic',
        "name": '💊 Бойовий медик',
        "description": 'Використати 15 або більше предметів лікування за матч.',
        "condition": lambda stats: stats.get('heals', 0) >= 15,
        "secret": False
    },
    {
        "id": 'energizer',
        "name": '⚡ Енерджайзер',
        "description": 'Використати 10 або більше бустів (енергетиків/знеболювальних).',
        "condition": lambda stats: stats.get('boosts', 0) >= 10,
        "secret": False
    },
    {
        "id": 'vehicle_destroyer',
        "name": '💥 Гроза транспорту',
        "description": 'Знищити 2 або більше транспортних засобів за один матч.',
        "condition": lambda stats: stats.get('vehicleDestroys', 0) >= 2,
        "secret": False
    },
    {
        "id": 'lobby_king',
        "name": '👑 Володар лобі',
        "description": 'Посісти 1-е місце за кількістю вбивств у матчі (killPlace 1).',
        "condition": lambda stats: stats.get('killPlace', 100) == 1,
        "secret": False
    },
    
    # --- СЕКРЕТНІ ДОСЯГНЕННЯ ---
    {
        "id": 'pacifist',
        "name": '🕊️ Пацифіст',
        "description": 'Зайняти Топ-1, не зробивши ЖОДНОГО вбивства.',
        "condition": lambda stats: stats.get('winPlace', 100) == 1 and stats.get('kills', 0) == 0,
        "secret": True
    },
    {
        "id": 'road_rage',
        "name": '🚗 Дорожня лють',
        "description": 'Вбити ворога, задавивши його транспортом.',
        "condition": lambda stats: stats.get('roadKills', 0) >= 1,
        "secret": True
    },
    {
        "id": 'marathon',
        "name": '🏃 Марафонець',
        "description": 'Пройти пішки більше 10 кілометрів за один матч.',
        "condition": lambda stats: stats.get('walkDistance', 0) >= 10000,
        "secret": True
    },
    {
        "id": 'aquaman',
        "name": '🦈 Аквамен',
        "description": 'Пропливти більше 500 метрів за один матч.',
        "condition": lambda stats: stats.get('swimDistance', 0) >= 500,
        "secret": True
    },
    {
        "id": 'oops',
        "name": '🙈 Ой, вибач!',
        "description": 'Випадково (або ні) вбити свого тімейта.',
        "condition": lambda stats: stats.get('teamKills', 0) >= 1,
        "secret": True
    },
    {
        "id": 'fast_and_furious',
        "name": '🏎️ Жага швидкості',
        "description": 'Проїхати транспортом більше 20 кілометрів за один матч.',
        "condition": lambda stats: stats.get('rideDistance', 0) >= 20000,
        "secret": True
    },
    {
        "id": 'unlucky',
        "name": '⚰️ Перший млинець нанівець',
        "description": 'Померти одним із перших (Топ-90 або гірше) з 0 вбивств.',
        "condition": lambda stats: stats.get('winPlace', 0) >= 90 and stats.get('kills', 0) == 0,
        "secret": True
    },
    {
        "id": 'tourist',
        "name": '🎒 Турист',
        "description": 'Пройти 5+ км пішки, не зробивши жодного фрагменту та не завдавши шкоди.',
        "condition": lambda stats: stats.get('walkDistance', 0) >= 5000 and stats.get('kills', 0) == 0 and stats.get('damageDealt', 0) == 0,
        "secret": True
    },
    {
        "id": 'hoarder',
        "name": '🛒 Барахольник',
        "description": 'Підняти 15 або більше різних видів зброї за один матч.',
        "condition": lambda stats: stats.get('weaponsAcquired', 0) >= 15,
        "secret": True
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
            from .data_handler import get_settings
            target_channel_id = channel_id or get_settings().get("reportsChannelId") or CONFIG.get("WIN_NOTIF_CHANNEL_ID")
            channel = client.get_channel(int(target_channel_id)) if target_channel_id else None
            
            for ach in new_achievements:
                cursor.execute(
                    "INSERT INTO achievements (userId, achievementId, dateEarned) VALUES (?, ?, ?)",
                    (user_id, ach["id"], now)
                )
                
                if channel:
                    is_secret = ach.get("secret", False)
                    title = '🤫 Секретне Досягнення!' if is_secret else '🏆 Нове Досягнення!'
                    color = 0x9B59B6 if is_secret else 0xFFD700
                    prefix = "🎉" if not is_secret else "👀"
                    
                    embed = discord.Embed(
                        title=title,
                        description=f'{prefix} Гравець **{pubg_nickname}** розблокував досягнення **{ach["name"]}**!',
                        color=color
                    )
                    embed.add_field(name='Опис', value=ach["description"])
                    await channel.send(embed=embed)
                    await asyncio.sleep(2.0) # Затримка проти спаму
                    
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Помилка перевірки досягнень: {e}")
