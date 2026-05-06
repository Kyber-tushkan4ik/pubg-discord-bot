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
        "condition": lambda stats, *args: stats.get('kills', 0) > 0,
        "secret": False
    },
    {
        "id": 'berserk',
        "name": '😡 М\'ясник',
        "description": 'Зробити 10 або більше вбивств за один матч.',
        "condition": lambda stats, *args: stats.get('kills', 0) >= 10,
        "secret": False
    },
    {
        "id": 'sniper',
        "name": '🎯 Снайпер',
        "description": 'Вбити ворога з відстані більше 300 метрів.',
        "condition": lambda stats, *args: stats.get('longestKill', 0) >= 300,
        "secret": False
    },
    {
        "id": 'medic',
        "name": '🚑 Польовий Лікар',
        "description": 'Підняти (revive) 3 або більше союзників.',
        "condition": lambda stats, *args: stats.get('revives', 0) >= 3,
        "secret": False
    },
    {
        "id": 'terminator',
        "name": '🤖 Термінатор',
        "description": 'Завдати більше 1000 шкоди за матч.',
        "condition": lambda stats, *args: stats.get('damageDealt', 0) >= 1000,
        "secret": False
    },
    {
        "id": 'headhunter',
        "name": '💀 Мисливець за головами',
        "description": 'Зробити 5 або більше вбивств у голову за матч.',
        "condition": lambda stats, *args: stats.get('headshotKills', 0) >= 5,
        "secret": False
    },
    {
        "id": 'team_player',
        "name": '🤝 Командний гравець',
        "description": 'Зробити 5 або більше асистів (допомог у вбивстві) за матч.',
        "condition": lambda stats, *args: stats.get('assists', 0) >= 5,
        "secret": False
    },
    {
        "id": 'combat_medic',
        "name": '💊 Бойовий медик',
        "description": 'Використати 15 або більше предметів лікування за матч.',
        "condition": lambda stats, *args: stats.get('heals', 0) >= 15,
        "secret": False
    },
    {
        "id": 'energizer',
        "name": '⚡ Енерджайзер',
        "description": 'Використати 10 або більше бустів (енергетиків/знеболювальних).',
        "condition": lambda stats, *args: stats.get('boosts', 0) >= 10,
        "secret": False
    },
    {
        "id": 'vehicle_destroyer',
        "name": '💥 Гроза транспорту',
        "description": 'Знищити 2 або більше транспортних засобів за один матч.',
        "condition": lambda stats, *args: stats.get('vehicleDestroys', 0) >= 2,
        "secret": False
    },
    {
        "id": "top_fragger",
        "name": "🥇 Альфа",
        "description": "Посісти перше місце за кількістю вбивств у матчі.",
        "condition": lambda stats, *args: stats.get('killPlace', 100) == 1,
        "secret": False
    },
    {
        "id": 'dbno_master',
        "name": '🩸 Майстер нокаутів',
        "description": 'Покласти на коліна (нокаутувати) 5 або більше ворогів за один матч.',
        "condition": lambda stats, *args: stats.get('DBNOs', 0) >= 5,
        "secret": False
    },
    
    # --- СЕКРЕТНІ ДОСЯГНЕННЯ ---
    {
        "id": 'pacifist',
        "name": '🕊️ Пацифіст',
        "description": 'Зайняти Топ-1, не зробивши ЖОДНОГО вбивства.',
        "condition": lambda stats, *args: stats.get('winPlace', 100) == 1 and stats.get('kills', 0) == 0,
        "secret": True
    },
    {
        "id": 'road_rage',
        "name": '🚗 Дорожня лють',
        "description": 'Вбити ворога, задавивши його транспортом.',
        "condition": lambda stats, *args: stats.get('roadKills', 0) >= 1,
        "secret": True
    },
    {
        "id": 'marathon',
        "name": '🏃 Марафонець',
        "description": 'Пройти пішки більше 10 кілометрів за один матч.',
        "condition": lambda stats, *args: stats.get('walkDistance', 0) >= 10000,
        "secret": True
    },
    {
        "id": 'aquaman',
        "name": '🦈 Аквамен',
        "description": 'Пропливти більше 500 метрів за один матч.',
        "condition": lambda stats, *args: stats.get('swimDistance', 0) >= 500,
        "secret": True
    },
    {
        "id": 'oops',
        "name": '🙈 Ой, вибач!',
        "description": 'Випадково (або ні) вбити свого тімейта.',
        "condition": lambda stats, *args: stats.get('teamKills', 0) >= 1,
        "secret": True
    },
    {
        "id": 'fast_and_furious',
        "name": '🏎️ Жага швидкості',
        "description": 'Проїхати транспортом більше 20 кілометрів за один матч.',
        "condition": lambda stats, *args: stats.get('rideDistance', 0) >= 20000,
        "secret": True
    },
    {
        "id": 'unlucky',
        "name": '⚰️ Перший млинець нанівець',
        "description": 'Померти одним із перших (Топ-90 або гірше) з 0 вбивств.',
        "condition": lambda stats, *args: stats.get('winPlace', 0) >= 90 and stats.get('kills', 0) == 0,
        "secret": True
    },
    {
        "id": 'tourist',
        "name": '🎒 Турист',
        "description": 'Пройти 5+ км пішки, не зробивши жодного фрагменту та не завдавши шкоди.',
        "condition": lambda stats, *args: stats.get('walkDistance', 0) >= 5000 and stats.get('kills', 0) == 0 and stats.get('damageDealt', 0) == 0,
        "secret": True
    },
    {
        "id": 'hoarder',
        "name": '🛒 Барахольник',
        "description": 'Підняти 15 або більше різних видів зброї за один матч.',
        "condition": lambda stats, *args: stats.get('weaponsAcquired', 0) >= 15,
        "secret": True
    },
    {
        "id": "tushkanchik",
        "super_secret": True, # Не показувати опис та умову взагалі
        "role_reward": "Тушканчік"
    },
    {
        "id": 'ninja',
        "name": '🥷 Ніндзя',
        "description": 'Посісти Топ-10, не завдавши ЖОДНОЇ одиниці шкоди за весь матч.',
        "condition": lambda stats, *args: stats.get('winPlace', 100) <= 10 and stats.get('damageDealt', 0) == 0,
        "secret": True
    }
]

async def check_achievements(client: discord.Client, user_id: str, pubg_nickname: str, stats: dict, channel_id: str = None, game_mode: str = None):
    unlocked = [ach for ach in ACHIEVEMENTS if "condition" in ach and ach["condition"](stats, game_mode)]
    if not unlocked:
        return

    try:
        def fetch_and_save_db():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT achievementId FROM achievements WHERE userId = ?", (user_id,))
            owned_ids = [row[0] for row in cursor.fetchall()]
            
            new_achs = [ach for ach in unlocked if ach["id"] not in owned_ids]
            
            if new_achs:
                now_ms = int(time.time() * 1000)
                for ach in new_achs:
                    cursor.execute(
                        "INSERT INTO achievements (userId, achievementId, dateEarned) VALUES (?, ?, ?)",
                        (user_id, ach["id"], now_ms)
                    )
                conn.commit()
            conn.close()
            return new_achs

        new_achievements = await asyncio.to_thread(fetch_and_save_db)
        
        if new_achievements:
            from .data_handler import get_settings
            target_channel_id = channel_id or get_settings().get("reportsChannelId") or CONFIG.get("WIN_NOTIF_CHANNEL_ID")
            channel = client.get_channel(int(target_channel_id)) if target_channel_id else None
            
            embeds_to_send = []
            
            for ach in new_achievements:
                # Обробка ролі за виграш (нагорода)
                if ach.get("role_reward"):
                    try:
                        from .data_handler import get_data
                        user_data = get_data()
                        
                        # Більш надійний пошук гільдії (без client.guilds[0])
                        guild_id = None
                        for key, val in user_data.items():
                            if val.get("userId") == str(user_id) and val.get("guildId"):
                                guild_id = val["guildId"]
                                break
                                
                        if guild_id:
                            guild = client.get_guild(int(guild_id))
                            if guild:
                                member = guild.get_member(int(user_id))
                                if not member:
                                    try: member = await guild.fetch_member(int(user_id))
                                    except: pass
                                
                                if member:
                                    role_name = ach["role_reward"]
                                    role = discord.utils.get(guild.roles, name=role_name)
                                    if not role:
                                        # Резервне створення, якщо немає прав, викличе помилку, потрібен try/except, але бот повинен мати права.
                                        role = await guild.create_role(name=role_name, color=discord.Color.orange())
                                    
                                    if role not in member.roles:
                                        await member.add_roles(role)
                                        # Відправка DM
                                        try:
                                            await member.send("Вітаємо! Ти зміг перевершити себе і продовжуй в тому ж дусі 🎉")
                                        except:
                                            pass # Приватні повідомлення закриті
                    except Exception as re:
                        print(f"Error granting achievement role: {re}")

                if channel:
                    is_secret = ach.get("secret", False)
                    is_super_secret = ach.get("super_secret", False)
                    
                    if is_super_secret:
                        title = '🤫 Секретний статус розблоковано!'
                        description = f'👀 Гравець **{pubg_nickname}** розблокував щось надзвичайно рідкісне!'
                        color = 0x2C3E50 # Дуже темний колір
                    else:
                        title = '🤫 Секретне Досягнення!' if is_secret else '🏆 Нове Досягнення!'
                        description = f'🎉 Гравець **{pubg_nickname}** розблокував досягнення **{ach["name"]}**!'
                        color = 0x9B59B6 if is_secret else 0xFFD700
                    
                    embed = discord.Embed(
                        title=title,
                        description=description,
                        color=color
                    )
                    
                    if not is_super_secret:
                        embed.add_field(name='Опис', value=ach["description"])
                    else:
                        embed.set_footer(text="Умова отримання залишається в таємниці...")
                        
                    embeds_to_send.append(embed)
            
            if channel and embeds_to_send:
                for i in range(0, len(embeds_to_send), 10):
                    await channel.send(embeds=embeds_to_send[i:i+10])
                    
    except Exception as e:
        print(f"Помилка перевірки досягнень: {e}")
