import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import time
import random
import sqlite3
import asyncio

from datetime import datetime, timedelta
from utils.data_handler import get_data, get_settings
from utils.pubg_api import get_player, get_player_season_stats, get_matches, get_latest_match_date
from utils.helpers import find_record

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

DB_FILE = os.path.join(os.path.dirname(__file__), '../database.sqlite')

cooldowns = {}

class PubgCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="p_stats", description="Переглянути статистику гравця PUBG")
    @app_commands.describe(nickname="Нікнейм гравця в PUBG (опціонально)")
    async def p_stats(self, interaction: discord.Interaction, nickname: str = None):
        user_id = str(interaction.user.id)
        cd_time = CONFIG.get("COOLDOWN_P_STATS", 30000)
        
        if user_id in cooldowns:
            exp_time = cooldowns[user_id] + cd_time
            now = int(time.time() * 1000)
            if now < exp_time:
                rem = (exp_time - now) // 1000
                await interaction.response.send_message(f"⏳ Зачекайте ще **{rem}** сек.", ephemeral=True)
                return
                
        if not nickname:
            user_data = get_data()
            record = find_record(user_data, user_id, str(interaction.guild.id))
            if record and record.get("pubgNickname"):
                nickname = record.get("pubgNickname")
            else:
                await interaction.response.send_message("❌ Ви не вказали нікнейм і у вас немає прив'язаного профілю.", ephemeral=True)
                return
                
        await interaction.response.defer()
        
        try:
            player = await get_player(nickname)
            if not player:
                await interaction.followup.send(f"Гравця з нікнеймом **{nickname}** не знайдено.")
                return
                
            stats_data = await get_player_season_stats(player["id"], 'lifetime')
            # simplified embed instead of image card for rewrite
            
            if not stats_data or "gameModeStats" not in stats_data.get("attributes", {}):
                await interaction.followup.send(f"Не вдалося отримати статистику для гравця **{nickname}**.")
                return
                
            all_stats = stats_data["attributes"]["gameModeStats"]
            modes = ['squad-fpp', 'squad', 'duo-fpp', 'duo', 'solo-fpp', 'solo']
            
            best_mode = None
            best_stats = None
            max_rounds = -1
            
            for m in modes:
                s = all_stats.get(m)
                if s and s.get("roundsPlayed", 0) > max_rounds:
                    max_rounds = s.get("roundsPlayed", 0)
                    best_stats = s
                    best_mode = m
                    
            if not best_stats or max_rounds == 0:
                await interaction.followup.send(f"Статистика для гравця **{nickname}** недоступна (0 матчів).")
                return
                
            embed = discord.Embed(title=f"📊 Статистика PUBG: {nickname}", color=0xFF9900)
            embed.add_field(name="Режим", value=best_mode, inline=True)
            embed.add_field(name="Матчі", value=best_stats.get("roundsPlayed", 0), inline=True)
            embed.add_field(name="Перемоги", value=best_stats.get("wins", 0), inline=True)
            embed.add_field(name="Вбивства", value=best_stats.get("kills", 0), inline=True)
            
            deaths = best_stats.get("losses", 1)
            kills = best_stats.get("kills", 0)
            kd = kills / max(deaths, 1)
            embed.add_field(name="K/D", value=f"{kd:.2f}", inline=True)
            embed.add_field(name="Шкода (avg)", value=f"{(best_stats.get('damageDealt', 0) / max(max_rounds, 1)):.0f}", inline=True)
            
            # Fetch last match info
            last_match_date = await get_latest_match_date(player)
            if last_match_date:
                try:
                    # Parse PUBG ISO date (e.g. 2023-10-27T14:48:22Z)
                    dt = datetime.fromisoformat(last_match_date.replace('Z', '+00:00'))
                    ts = int(dt.timestamp())
                    embed.add_field(name="Останній матч", value=f"<t:{ts}:R>", inline=True)
                except Exception as e:
                    print(f"Error parsing date: {e}")

            cooldowns[user_id] = int(time.time() * 1000)
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Помилка p_stats: {e}")
            await interaction.followup.send("Сталася помилка при отриманні даних PUBG API.", ephemeral=True)

    @app_commands.command(name="clan_status", description="Перевірити активність клану (хто скільки не грав)")
    async def clan_status(self, interaction: discord.Interaction):
        bot_settings = get_settings()
        if bot_settings.get("disableClanTracking"):
            await interaction.response.send_message("⭕ Відстеження активності клану наразі ВИМКНЕНО.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        now = int(time.time() * 1000)
        user_data = get_data()
        guild = interaction.guild
        
        clan_role = discord.utils.get(guild.roles, name=CONFIG.get("ROLE_SUCCESS"))
        if not clan_role:
            await interaction.followup.send("Роль клану не знайдено.")
            return
            
        clan_members = [m for m in guild.members if clan_role in m.roles]
        stats = []
        
        for m in clan_members:
            record = find_record(user_data, str(m.id), str(guild.id))
            if record and record.get("untracked"):
                continue
                
            is_playing = any(a.name == CONFIG.get("GAME_NAME") for a in m.activities)
            last_seen = record.get("lastPubgSeen", 0) if record else 0
            
            if is_playing:
                last_seen = now
                if record:
                    record["lastPubgSeen"] = now
                    
            stats.append({
                "tag": str(m),
                "diff": now - last_seen,
                "lastSeen": last_seen,
                "isPlaying": is_playing,
                "isExternal": False
            })
            
        for key, ext in user_data.items():
            if ext.get("isExternal") and ext.get("guildId") == str(guild.id):
                last_seen = ext.get("lastPubgSeen", 0)
                stats.append({
                    "tag": ext.get("username"),
                    "diff": now - last_seen,
                    "lastSeen": last_seen,
                    "isPlaying": False,
                    "isExternal": True
                })
                
        stats.sort(key=lambda x: x["diff"], reverse=True)
        
        embed = discord.Embed(title='📊 Статус активності клану', color=0xF2A900)
        
        desc = ""
        for s in stats:
            name = f"{s['tag']} (Ext)" if s["isExternal"] else s["tag"]
            
            if s["isPlaying"]:
                line = f"🟢 **{name}**: Грає зараз\n"
            elif s["lastSeen"] == 0:
                line = f"⚪ **{name}**: Немає даних\n"
            else:
                diff_ms = s["diff"]
                days = diff_ms // 86400000
                hours = (diff_ms % 86400000) // 3600000
                emoji = '🟡' if days < 3 else '🔴'
                line = f"{emoji} **{name}**: {days}д {hours}год тому\n"
                
            if len(desc) + len(line) > 4000:
                break
            desc += line
            
        embed.description = desc or "Гравців не знайдено"
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="compare", description="Порівняти статистику з іншим гравцем (VS Mode)")
    @app_commands.describe(target="Гравець для порівняння", mode="Режим гри (Squad/Duo/Solo)")
    @app_commands.choices(mode=[
        app_commands.Choice(name='Squad FPP', value='squad-fpp'),
        app_commands.Choice(name='Squad TPP', value='squad'),
        app_commands.Choice(name='Duo FPP', value='duo-fpp'),
        app_commands.Choice(name='Duo TPP', value='duo'),
        app_commands.Choice(name='Solo FPP', value='solo-fpp'),
        app_commands.Choice(name='Solo TPP', value='solo')
    ])
    async def compare(self, interaction: discord.Interaction, target: discord.User, mode: app_commands.Choice[str] = None):
        mode_value = mode.value if mode else 'squad-fpp'
        user_data = get_data()
        
        author_record = find_record(user_data, str(interaction.user.id), str(interaction.guild.id))
        if not author_record or not author_record.get("pubgNickname"):
            await interaction.response.send_message("❌ Ви не прив'язали свій PUBG профіль.", ephemeral=True)
            return
            
        target_record = find_record(user_data, str(target.id), str(interaction.guild.id))
        if not target_record or not target_record.get("pubgNickname"):
            await interaction.response.send_message(f"❌ Гравець {target.mention} не прив'язав свій PUBG профіль.", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        try:
            p1, p2 = await asyncio.gather(
                get_player(author_record["pubgNickname"]),
                get_player(target_record["pubgNickname"])
            )
            
            if not p1 or not p2:
                await interaction.followup.send('Помилка пошуку профілів в PUBG API.')
                return
                
            s1, s2 = await asyncio.gather(
                get_player_season_stats(p1["id"], 'lifetime'),
                get_player_season_stats(p2["id"], 'lifetime')
            )
            
            stats1 = s1.get("attributes", {}).get("gameModeStats", {}).get(mode_value) if s1 else None
            stats2 = s2.get("attributes", {}).get("gameModeStats", {}).get(mode_value) if s2 else None
            
            if not stats1 or not stats2:
                await interaction.followup.send(f"Немає достатньо даних для режиму **{mode_value}** у одного з гравців.")
                return
                
            embed = discord.Embed(title=f"⚔️ {author_record['pubgNickname']} VS {target_record['pubgNickname']}", color=0xE74C3C)
            embed.description = f"**Режим:** {mode_value.upper()}"
            
            def safe_div(a, b): return a / b if b else 0
            
            kd1 = safe_div(stats1.get('kills', 0), stats1.get('losses', 1))
            kd2 = safe_div(stats2.get('kills', 0), stats2.get('losses', 1))
            
            embed.add_field(name="Матчі", value=f"{stats1.get('roundsPlayed', 0)} vs {stats2.get('roundsPlayed', 0)}", inline=False)
            embed.add_field(name="Перемоги", value=f"{stats1.get('wins', 0)} vs {stats2.get('wins', 0)}", inline=False)
            embed.add_field(name="Вбивства", value=f"{stats1.get('kills', 0)} vs {stats2.get('kills', 0)}", inline=False)
            embed.add_field(name="K/D Ratio", value=f"{kd1:.2f} vs {kd2:.2f}", inline=False)
            
            avg_dmg1 = safe_div(stats1.get('damageDealt', 0), stats1.get('roundsPlayed', 1))
            avg_dmg2 = safe_div(stats2.get('damageDealt', 0), stats2.get('roundsPlayed', 1))
            embed.add_field(name="Середня Шкода", value=f"{avg_dmg1:.0f} vs {avg_dmg2:.0f}", inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Помилка порівняння: {e}")
            await interaction.followup.send("Сталася помилка під час порівняння.")

    @app_commands.command(name="leaderboard", description="Переглянути глобальний рейтинг гравців")
    @app_commands.describe(metric="Критерій сортування")
    @app_commands.choices(metric=[
        app_commands.Choice(name='K/D Ratio', value='kd'),
        app_commands.Choice(name='Wins', value='wins'),
        app_commands.Choice(name='Average Damage', value='avgDamage'),
        app_commands.Choice(name='Total Kills', value='totalKills')
    ])
    async def leaderboard(self, interaction: discord.Interaction, metric: app_commands.Choice[str]):
        user_data = get_data()
        players = [p for p in user_data.values() if p.get("pubgNickname")]
        
        if not players:
            await interaction.response.send_message("Ще немає даних для рейтингу.", ephemeral=True)
            return
            
        metric_key = metric.value
        players.sort(key=lambda x: float(x.get(metric_key, 0) or 0), reverse=True)
        top10 = players[:10]
        
        titles = {
            'kd': '💀 K/D Ratio',
            'wins': '🏆 Wins',
            'avgDamage': '🔥 Average Damage',
            'totalKills': '🔫 Total Kills'
        }
        
        embed = discord.Embed(title=f"🏆 Глобальний Рейтинг: {titles[metric_key]}", description="Топ-10 гравців серверу за весь час (Lifetime Squad)\n", color=0xFFD700)
        
        desc = ""
        for i, p in enumerate(top10):
            val = p.get(metric_key, 0) or 0
            if metric_key == 'avgDamage': val = round(float(val))
            elif metric_key == 'kd': val = f"{float(val):.2f}"
                
            medal = '🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else f"**{i+1}.**"
            desc += f"{medal} **{p['pubgNickname']}** — {val}\n"
            
        embed.description += (desc or "Дані оновлюються...")
        embed.set_footer(text='Оновлюється щогодини')
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="matches", description="Показати історію останніх матчів")
    @app_commands.describe(nickname="Нікнейм гравця")
    async def matches(self, interaction: discord.Interaction, nickname: str = None):
        if not nickname:
            user_data = get_data()
            record = find_record(user_data, str(interaction.user.id), str(interaction.guild.id))
            if record and record.get("pubgNickname"):
                nickname = record.get("pubgNickname")
                
        if not nickname:
            await interaction.response.send_message("❌ Вкажіть нікнейм або прив'яжіть профіль.", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        try:
            player = await get_player(nickname)
            if not player:
                await interaction.followup.send(f"❌ Гравця **{nickname}** не знайдено.")
                return
                
            matches_rels = player.get("relationships", {}).get("matches", {}).get("data", [])
            if not matches_rels:
                matches_rels = player.get("relationships", {}).get("matches", [])
                if isinstance(matches_rels, dict) and "data" in matches_rels:
                    matches_rels = matches_rels["data"]
            
            match_ids = [m["id"] for m in matches_rels][:5]
            if not match_ids:
                await interaction.followup.send('Матчів не знайдено.')
                return
                
            matches_data = await get_matches(match_ids)
            
            embed = discord.Embed(title=f"📜 Історія матчів: {player.get('attributes', {}).get('name', nickname)}", color=0xF2A900)
            
            for i, match in enumerate(matches_data):
                if not match or "included" not in match: continue
                
                attr = match.get("data", {}).get("attributes", {})
                mode = attr.get("gameMode", "").upper()
                map_n = attr.get("mapName", "")
                duration = f"{int(attr.get('duration', 0) // 60)}m"
                
                participant = next((inc for inc in match["included"] if inc.get("type") == "participant" and inc.get("attributes", {}).get("stats", {}).get("playerId") == player["id"]), None)
                
                if participant:
                    s = participant["attributes"]["stats"]
                    place = s.get("winPlace", 0)
                    kills = s.get("kills", 0)
                    dmg = round(s.get("damageDealt", 0))
                    
                    emoji = '🏆' if place == 1 else ('🥈' if place <= 10 else '💀')
                    
                    embed.add_field(name=f"{emoji} Match {i+1} - {mode} ({map_n})", value=f"Top **{place}** | Kills: **{kills}** | Dmg: **{dmg}** \n Тривалість: {duration}", inline=False)
                    
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Помилка матчів: {e}")
            await interaction.followup.send("Помилка отримання матчів.")

    @app_commands.command(name="records", description="Переглянути Залу Слави клану (Рекорди)")
    async def records(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM records").fetchall()
            conn.close()
            
            embed = discord.Embed(
                title='🏆 Зала Слави (Hall of Fame)', 
                description='Абсолютні рекорди нашого клану за весь час!', 
                color=0xFFD700
            )
            embed.set_thumbnail(url='https://i.imgur.com/qg9b9dE.png')
            
            if not rows:
                embed.add_field(name='Пусто...', value='Поки що ніхто не встановив рекордів. Грайте матчі!')
            else:
                record_titles = {
                    'max_kills': '💀 Найбільше вбивств (матч)',
                    'max_damage': '💥 Найбільше шкоди (матч)',
                    'longest_kill': '🎯 Найдовший постріл',
                    'max_time': '⏱️ Найдовше виживання',
                    'max_heal': '💊 Найбільше лікування'
                }
                keys = ['max_kills', 'max_damage', 'longest_kill', 'max_heal']
                
                for key in keys:
                    record = next((r for r in rows if r['id'] == key), None)
                    title = record_titles.get(key, key)
                    if record:
                        val = record['value']
                        if key == 'longest_kill': val = f"{val:.1f} м"
                        elif key == 'max_damage': val = round(val)
                        
                        embed.add_field(name=title, value=f"**{val}** — {record['holderName']} (<t:{int(record['date'] / 1000)}:R>)", inline=False)
                    else:
                        embed.add_field(name=title, value='---', inline=False)
                        
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Помилка отримання рекордів: {e}")
            await interaction.followup.send("❌ Помилка отримання рекордів.")

    @app_commands.command(name="drop", description="Вибрати випадкову локацію для висадки")
    @app_commands.describe(map_name="Мапа")
    @app_commands.choices(map_name=[
        app_commands.Choice(name='Erangel', value='erangel'),
        app_commands.Choice(name='Miramar', value='miramar'),
        app_commands.Choice(name='Taego', value='taego'),
        app_commands.Choice(name='Vikendi', value='vikendi'),
        app_commands.Choice(name='Deston', value='deston'),
        app_commands.Choice(name='Rondo', value='rondo'),
        app_commands.Choice(name='Sanhok', value='sanhok'),
        app_commands.Choice(name='Karakin', value='karakin'),
        app_commands.Choice(name='Paramo', value='paramo')
    ])
    async def drop(self, interaction: discord.Interaction, map_name: app_commands.Choice[str]):
        locations = {
            "erangel": ["Pochinki", "School", "Military Base", "Rozhok", "Yasnaya Polyana", "Georgopol", "Novorepnoye", "Gatka", "Mylta", "Farm", "Quarry", "Shelter", "Prison", "Lipovka", "Severny", "Zharki", "Stalber", "Kameshki", "Ruins", "Hospital"],
            "miramar": ["Pecado", "Hacienda del Patron", "San Martin", "Los Leones", "El Pozo", "Chumacera", "Power Grid", "Monte Nuevo", "Valle del Mar", "Impala", "Puerto Paraiso", "Cruz del Valle", "El Azahar", "Torre Ahumada", "Campo Militar", "La Cobreria", "Minas Generales", "Junkyard"],
            "taego": ["Terminal", "Shipyard", "Ho San", "Palace", "Buk San Sa", "Kang Neung", "Hae Moo Sa", "Go Dok", "Yong Cheon", "School", "Hospital", "Airport"],
            "vikendi": ["Castle", "Cosmodrome", "Dino Park", "Villa", "Cement Factory", "Goroka", "Dobro Mesto", "Volnova", "Podvosto", "Peshkova", "Trevno", "Krichas", "Coal Mine", "Mount Kreznic", "Winery", "Port", "Sawmill"],
            "deston": ["Ripton", "Los Arcos", "Concert District", "Hydroelectric Dam", "Buxley", "Construction Site", "Turrita", "Barclift", "Lodging", "Arena", "Swamp", "Assembly"],
            "sanhok": ["Bootcamp", "Paradise Resort", "Ruins", "Pai Nan", "Camp Alpha", "Camp Bravo", "Camp Charlie", "Ha Tinh", "Tat Mok", "Khao", "Mongnai", "Ban Tai", "Docks", "Quarry", "Sahmee", "Tambang"],
            "karakin": ["Bashara", "Bahr Sahir", "Al Habar", "Hadiqa Nemo", "Cargo Ship"],
            "paramo": ["Atlatl Ridge", "Makalpa", "Capaco", "Hell's Crash"],
            "rondo": ["Jadena City", "Stadium", "NEOX Factory", "Test Track", "Rin Jiang", "Tin Long Garden", "Yu Lin", "Mey Ran", "Bei Li", "Hung Shan"]
        }
        
        map_key = map_name.value
        map_display = map_name.name
        locs = locations.get(map_key, ["Unknown"])
        target_loc = random.choice(locs)
        
        embed = discord.Embed(
            title=f"📍 Random Drop: {map_display}",
            description=f"Ваша ціль: **{target_loc}**",
            color=0x3498db
        )
        embed.set_thumbnail(url='https://i.imgur.com/2s42c0z.png')
        embed.set_footer(text='Стрибаємо на рахунок три!')
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="strat", description="Отримати випадковий челендж для матчу (Strat Roulette)")
    @app_commands.describe(difficulty="Складність")
    @app_commands.choices(difficulty=[
        app_commands.Choice(name='Easy (Легко)', value='easy'),
        app_commands.Choice(name='Hard (Важко)', value='hard'),
        app_commands.Choice(name='Troll (Весело)', value='troll'),
        app_commands.Choice(name='Random (Випадково)', value='random')
    ])
    async def strat(self, interaction: discord.Interaction, difficulty: app_commands.Choice[str] = None):
        challenges_easy = [
            "🔫 **Pistol Only:** Можна використовувати лише пістолети.",
            "🔇 **Silence:** Заборонено говорити в грі до першого вбивства сквадом.",
            "🚗 **Drive-by:** Вбивати можна тільки з машини.",
            "🎒 **No Backpack:** Заборонено піднімати рюкзаки (тільки жилет).",
            "💣 **Grenadier:** Кожен має носити мінімум 5 гранат.",
            "🏥 **Medic:** Один гравець тільки лікує і носить припаси, але не стріляє."
        ]
        challenges_hard = [
            "😈 **No Helmet:** Заборонено носити шоломи.",
            "🦶 **Shoes Off:** Граємо босоніж (персонажі).",
            "🏠 **Camper:** Весь матч сидіти в одній будівлі (після луту).",
            "🔭 **No Scope:** Заборонено використовувати приціли вище Red Dot / Holo.",
            "🔥 **Molotov Only:** Намагатися вбити останнього ворога коктейлем Молотова."
        ]
        challenges_troll = [
            "🤡 **Follow the Leader:** Всі ходять «змійкою» за лідером і повторюють його рухи.",
            "🚕 **Taxi Driver:** Знайти машину і пропонувати ворогам підвезти їх (в загальний чат).",
            "👊 **Fist Fight:** Фінального ворога вбити кулаками/сковорідкою.",
            "🗳️ **Democracy:** Перед кожним пострілом сквад має проголосувати «Стріляти чи ні?»."
        ]
        
        diff_val = difficulty.value if difficulty else 'random'
        
        if diff_val == 'random':
            pool = challenges_easy + challenges_hard + challenges_troll
        elif diff_val == 'easy':
            pool = challenges_easy
        elif diff_val == 'hard':
            pool = challenges_hard
        else:
            pool = challenges_troll
            
        challenge = random.choice(pool)
        
        embed = discord.Embed(
            title='🎰 Strat Roulette',
            description=challenge,
            color=0xe67e22
        )
        embed.set_footer(text='Удачі! Вона вам знадобиться...')
        
        await interaction.response.send_message(embed=embed)
        
    @app_commands.command(name="p_weekly", description="Переглянути тижневу статистику клану (Пн-Нд)")
    @app_commands.describe(sort_by="Критерій сортування")
    @app_commands.choices(sort_by=[
        app_commands.Choice(name='Перемоги (Wins)', value='wins'),
        app_commands.Choice(name='Вбивства (Kills)', value='kills')
    ])
    async def p_weekly(self, interaction: discord.Interaction, sort_by: app_commands.Choice[str] = None):
        user_data = get_data()
        # Фільтруємо гравців, які мають тижневіWins або тижневіKills > 0
        players = [p for p in user_data.values() if p.get("pubgNickname") and (p.get("weeklyWins", 0) > 0 or p.get("weeklyKills", 0) > 0)]
        
        if not players:
            await interaction.response.send_message("За цей тиждень ще немає зіграних матчів з результатом.", ephemeral=True)
            return
            
        sort_key = sort_by.value if sort_by else 'wins'
        if sort_key == 'wins':
            players.sort(key=lambda x: (x.get("weeklyWins", 0), x.get("weeklyKills", 0)), reverse=True)
        else:
            players.sort(key=lambda x: (x.get("weeklyKills", 0), x.get("weeklyWins", 0)), reverse=True)
            
        embed = discord.Embed(title="📅 Тижневі підсумки (Monday - Sunday)", color=0x2ECC71)
        today = datetime.now()
        # Розраховуємо початок і кінець тижня для відображення
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        embed.description = f"Період: `{start_of_week.strftime('%d.%m')}` — `{end_of_week.strftime('%d.%m')}`\n\n"
        
        # Будуємо таблицю
        desc = "```\n#  Гравець          🏆  💀\n"
        desc += "----------------------------\n"
        for i, p in enumerate(players[:15]): # Топ 15 гравців
            nick = p['pubgNickname'][:14].ljust(14)
            wins = str(p.get("weeklyWins", 0)).rjust(2)
            kills = str(p.get("weeklyKills", 0)).rjust(3)
            desc += f"{str(i+1).ljust(2)} {nick} {wins} {kills}\n"
        desc += "```"
        
        embed.description += desc
        embed.set_footer(text="Оновлюється після кожного матчу. Скидання щопонеділка.")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="p_monthly", description="Переглянути місячну статистику клану")
    @app_commands.describe(sort_by="Критерій сортування")
    @app_commands.choices(sort_by=[
        app_commands.Choice(name='Перемоги (Wins)', value='wins'),
        app_commands.Choice(name='Вбивства (Kills)', value='kills')
    ])
    async def p_monthly(self, interaction: discord.Interaction, sort_by: app_commands.Choice[str] = None):
        user_data = get_data()
        # Фільтруємо гравців, які мають місячніWins або місячніKills > 0
        players = [p for p in user_data.values() if p.get("pubgNickname") and (p.get("monthlyWins", 0) > 0 or p.get("monthlyKills", 0) > 0)]
        
        if not players:
            await interaction.response.send_message("За цей місяць ще немає зіграних матчів з результатом.", ephemeral=True)
            return
            
        sort_key = sort_by.value if sort_by else 'wins'
        if sort_key == 'wins':
            players.sort(key=lambda x: (x.get("monthlyWins", 0), x.get("monthlyKills", 0)), reverse=True)
        else:
            players.sort(key=lambda x: (x.get("monthlyKills", 0), x.get("monthlyWins", 0)), reverse=True)
            
        embed = discord.Embed(title="📅 Місячні підсумки", color=0x3498DB)
        today = datetime.now()
        
        embed.description = f"Період: `{today.strftime('%B %Y')}`\n\n"
        
        # Будуємо таблицю
        desc = "```\n#  Гравець          🏆  💀\n"
        desc += "----------------------------\n"
        for i, p in enumerate(players[:15]): # Топ 15 гравців
            nick = p['pubgNickname'][:14].ljust(14)
            wins = str(p.get("monthlyWins", 0)).rjust(2)
            kills = str(p.get("monthlyKills", 0)).rjust(3)
            desc += f"{str(i+1).ljust(2)} {nick} {wins} {kills}\n"
        desc += "```"
        
        embed.description += desc
        embed.set_footer(text="Оновлюється після кожного матчу. Скидання першого числа місяця.")
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(PubgCog(bot))
    print("Loaded extension: pubg")
