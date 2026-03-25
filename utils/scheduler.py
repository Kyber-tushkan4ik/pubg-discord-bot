import discord
from discord.ext import tasks
import asyncio
import os
import json
import time

from .data_handler import get_data, save_data
from .pubg_api import get_player, get_player_season_stats, get_latest_match_date, get_match
from .helpers import create_log, ms_to_readable
from .achievements import check_achievements
from .records import check_records

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

queue = asyncio.Queue()

async def process_queue():
    while True:
        task = await queue.get()
        try:
            await asyncio.wait_for(task(), timeout=30.0)
        except Exception as e:
            create_log(f"[QUEUE ERROR] {e}")
        finally:
            queue.task_done()
            await asyncio.sleep(CONFIG.get("API_DELAY_MS", 7000) / 1000.0)

def add_to_queue(task):
    queue.put_nowait(task)

def init_scheduler(client: discord.Client):
    client.loop.create_task(process_queue())
    
    # 24 hour loops roughly simulating chron behavior
    @tasks.loop(hours=24)
    async def daily_tasks():
        await check_inactivity(client)
        await check_recent_matches(client)
        
        # Перевірка щотижневого звіту (неділя - 6)
        from .data_handler import get_settings, save_settings
        settings = get_settings()
        last_report = settings.get("lastWeeklyReportDate")
        today_str = time.strftime("%Y-%m-%d")
        
        if time.localtime().tm_wday == 6 and last_report != today_str:
            await send_weekly_report(client)
            settings["lastWeeklyReportDate"] = today_str
            await save_settings()
            
        # Скидання тижневої статистики (понеділок - 0)
        last_reset = settings.get("lastWeeklyResetDate")
        if time.localtime().tm_wday == 0 and last_reset != today_str:
            user_data = get_data()
            for p in user_data.values():
                p["weeklyWins"] = 0
                p["weeklyKills"] = 0
            await save_data()
            from .data_handler import save_settings
            settings["lastWeeklyResetDate"] = today_str
            await save_settings()
            create_log("[SCHEDULER] Щопонеділкове скидання тижневої статистики виконано.")
            
        # Скидання місячної статистики (1-ше число)
        last_m_reset = settings.get("lastMonthlyResetDate")
        if time.localtime().tm_mday == 1 and last_m_reset != today_str:
            user_data = get_data()
            for p in user_data.values():
                p["monthlyWins"] = 0
                p["monthlyKills"] = 0
            await save_data()
            settings["lastMonthlyResetDate"] = today_str
            await save_settings()
            create_log("[SCHEDULER] Щомісячне скидання статистики виконано.")
            
    @tasks.loop(minutes=60)
    async def hourly_tasks():
        await update_stats_and_ranks(client)

    @tasks.loop(minutes=5)
    async def heartbeat_tasks():
        user_data = get_data()
        now = int(time.time() * 1000)
        count = 0
        for key, p in user_data.items():
            if p.get("isActive") and p.get("lastSessionStart") and not p.get("isPaused"):
                duration = now - p["lastSessionStart"]
                if 0 < duration < 3600000: # Захист від аномальних стрибків
                    p["totalPlayTime"] = p.get("totalPlayTime", 0) + duration
                    p["lastSessionStart"] = now
                    count += 1
        if count > 0:
            await save_data()
            create_log(f"[HEARTBEAT] Оновлено час для {count} гравців.")

    daily_tasks.start()
    hourly_tasks.start()
    heartbeat_tasks.start()
    create_log('[SCHEDULER] Завдання ініціалізовано.')

async def send_weekly_report(client: discord.Client):
    create_log('[SCHEDULER] Генерування щотижневого звіту...')
    # Logic implementation simplified for rewrite
    user_data = get_data()
    players = [p for p in user_data.values() if p.get("pubgNickname") and p.get("isActive")]
    if not players: return
    
    report_ch = client.get_channel(int(CONFIG.get("WEEKLY_REPORT_CHANNEL_ID", 0)))
    if not report_ch: return
    
    active = sorted(players, key=lambda p: p.get("totalPlayTime", 0), reverse=True)[:5]
    embed = discord.Embed(title='📊 Щотижневий звіт активності', description='Топ-5 гравців на етапі адаптації:', color=0x0099ff)
    for i, p in enumerate(active):
        embed.add_field(name=f"{i+1}. {p.get('pubgNickname')}", value=f"Час: {ms_to_readable(p.get('totalPlayTime', 0))}", inline=False)
    await report_ch.send(embed=embed)

async def check_inactivity(client):
    create_log('[SCHEDULER] Перевірка неактивності...')
    user_data = get_data()
    for p in [x for x in user_data.values() if x.get("pubgNickname")]:
        async def task(player=p):
            pubg_data = await get_player(player["pubgNickname"])
            if not pubg_data: return
            
            last_date = await get_latest_match_date(pubg_data)
            if not last_date: return
            
            import datetime
            try:
                last_dt = datetime.datetime.strptime(last_date, "%Y-%m-%dT%H:%M:%SZ")
                inactive_days = (datetime.datetime.utcnow() - last_dt).days
                if inactive_days >= CONFIG.get("INACTIVITY_DAYS_LIMIT", 14):
                    create_log(f"[INACTIVE] {player['pubgNickname']} неактивний {inactive_days} дн.")
            except: pass
        add_to_queue(task)

async def update_stats_and_ranks(client: discord.Client):
    create_log('[SCHEDULER] Оновлення рангів...')
    user_data = get_data()
    
    for key, player in [(k, v) for k, v in user_data.items() if v.get("pubgNickname")]:
        async def task(p=player, k=key):
            try:
                pubg_data = await get_player(p["pubgNickname"])
                if not pubg_data: return
                
                player_id = pubg_data["id"]
                stats = await get_player_season_stats(player_id, 'lifetime')
                if not stats or "attributes" not in stats or "gameModeStats" not in stats["attributes"]:
                    return
                
                gm_stats = stats["attributes"]["gameModeStats"]
                # Шукаємо стат Squad (FPP або TPP)
                squad_stats = gm_stats.get('squad-fpp') or gm_stats.get('squad') or gm_stats.get('squadFPP')
                if not squad_stats: return
                
                kills = squad_stats.get('kills', 0)
                deaths = squad_stats.get('losses', 1) or 1
                wins = squad_stats.get('wins', 0)
                rounds = squad_stats.get('roundsPlayed', 1) or 1
                damage = squad_stats.get('damageDealt', 0)
                
                kd = round(kills / deaths, 2)
                p["kd"] = kd
                p["wins"] = wins
                p["rounds"] = rounds
                p["totalKills"] = kills
                p["avgDamage"] = round(damage / rounds, 0)
                
                await save_data()
                
                # Оновлення ролей в Discord
                user_id = p.get("userId")
                guild_id = p.get("guildId")
                if not user_id or p.get("isExternal"): return
                guild = client.get_guild(int(guild_id)) if guild_id else None
                
                # Якщо сервер не вказано або не знайдено, шукаємо в усіх (окрім Котяри)
                if not guild:
                    for g in client.guilds:
                        if "Котяри" in g.name: continue
                        member = g.get_member(int(user_id))
                        if member:
                            guild = g
                            break

                if not guild: return
                
                try:
                    member = await guild.fetch_member(int(user_id))
                    if not member: return
                    
                    # Визначаємо цільовий ранг
                    target_role_name = "Новачок"
                    rank_roles = CONFIG.get("RANK_ROLES", {})
                    # Сортуємо ролі від найвищого KD до найнижчого
                    sorted_ranks = sorted(rank_roles.items(), key=lambda x: x[1], reverse=True)
                    
                    for role_name, min_kd in sorted_ranks:
                        if kd >= min_kd:
                            target_role_name = role_name
                            break
                    
                    current_rank_role_names = list(rank_roles.keys())
                    
                    # Перевірка чи є роль у користувача
                    has_role = any(r.name == target_role_name for r in member.roles)
                    
                    if not has_role:
                        # Знаходимо або створюємо роль
                        role_obj = discord.utils.get(guild.roles, name=target_role_name)
                        if not role_obj:
                            role_obj = await guild.create_role(name=target_role_name, reason="Авто-створено PUBG Ботом")
                        
                        # Видаляємо старі ранги
                        to_remove = [r for r in member.roles if r.name in current_rank_role_names and r.name != target_role_name]
                        if to_remove:
                            await member.remove_roles(*to_remove)
                        
                        # Додаємо новий
                        await member.add_roles(role_obj)
                        create_log(f"[RANK] Оновлено {p['pubgNickname']} до {target_role_name} (KD: {kd})")
                    
                    # Спеціальні ролі
                    await check_special_roles(guild, member, squad_stats, p['pubgNickname'])
                    
                except Exception as e:
                    print(f"Failed to update member roles: {e}")
                    
            except Exception as ex:
                create_log(f"[ERROR] Помилка оновлення гравця {p.get('pubgNickname')}: {ex}")
        
        add_to_queue(task)

async def check_special_roles(guild: discord.Guild, member: discord.Member, stats: dict, nickname: str):
    special_roles = CONFIG.get("SPECIAL_ROLES")
    if not special_roles: return
    
    for role_name, criteria in special_roles.items():
        passed = False
        if role_name == 'Санітар':
            if stats.get('revives', 0) >= criteria.get('revives', 15) or stats.get('heals', 0) >= criteria.get('heals', 80):
                passed = True
        elif role_name == 'Ліквідатор':
            ratio = stats.get('headshotKills', 0) / stats.get('kills', 1) if stats.get('kills', 0) > 0 else 0
            if stats.get('kills', 0) >= criteria.get('minKills', 10) and ratio >= criteria.get('headshotRatio', 0.25):
                passed = True
        elif role_name == 'Берсерк':
            avg_dmg = stats.get('damageDealt', 0) / stats.get('roundsPlayed', 1) if stats.get('roundsPlayed', 0) > 0 else 0
            if avg_dmg >= criteria.get('avgDamage', 250):
                passed = True
        elif role_name == 'Бойовий товариш':
            if stats.get('assists', 0) >= criteria.get('assists', 5):
                passed = True
        elif role_name == 'Перевізник':
            if stats.get('rideDistance', 0) >= criteria.get('rideDistance', 50000):
                passed = True
        elif role_name == 'Скажений Макс (Стат)':
            if stats.get('roadKills', 0) >= criteria.get('roadKills', 5):
                passed = True
        elif role_name == 'Скаут':
            if stats.get('walkDistance', 0) >= criteria.get('walkDistance', 25000):
                passed = True
        elif role_name == 'Вцілілий':
            ratio = stats.get('top10s', 0) / stats.get('roundsPlayed', 1) if stats.get('roundsPlayed', 0) > 0 else 0
            if stats.get('roundsPlayed', 0) >= criteria.get('minRounds', 10) and ratio >= criteria.get('top10Ratio', 0.25):
                passed = True
        elif role_name == 'Затятий гравець':
            if stats.get('roundsPlayed', 0) >= criteria.get('roundsPlayed', 250):
                passed = True
        
        if passed:
            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                role = await guild.create_role(name=role_name, reason="Авто-створено спеціальну роль")
            
            if role and role not in member.roles:
                await member.add_roles(role)
                create_log(f"[SPECIAL] Призначено {role_name} для {nickname}")

async def check_recent_matches(client: discord.Client):
    create_log('[SCHEDULER] Перевірка нещодавних матчів та досягнень...')
    user_data = get_data()
    
    win_channel_id = CONFIG.get("WIN_NOTIF_CHANNEL_ID")
    win_channel = client.get_channel(int(win_channel_id)) if win_channel_id else None
    
    for key, player in [(k, v) for k, v in user_data.items() if v.get("pubgNickname")]:
        async def task(p=player, k=key):
            try:
                pubg_data = await get_player(p["pubgNickname"])
                if not pubg_data: return
                
                relationships = pubg_data.get("relationships", {})
                matches = relationships.get("matches", {}).get("data", [])
                if not matches: return
                
                all_match_ids = [m["id"] for m in matches]
                new_matches = []
                
                last_checked = p.get("lastCheckedMatchId")
                for mid in all_match_ids:
                    if mid == last_checked: break
                    new_matches.append(mid)
                
                # Обмежуємо до 5 матчів за раз щоб не перевантажувати API
                matches_to_process = new_matches[:5]
                if not matches_to_process: return
                
                create_log(f"[MATCH] Обробка {len(matches_to_process)} матчів для {p['pubgNickname']}")
                
                for mid in reversed(matches_to_process): # Від старіших до новіших
                    match_details = await get_match(mid)
                    if not match_details or "included" not in match_details: continue
                    
                    participant = None
                    for inc in match_details["included"]:
                        if inc["type"] == 'participant' and inc.get("attributes", {}).get("stats", {}).get("playerId") == pubg_data["id"]:
                            participant = inc
                            break
                    
                    if participant:
                        stats = participant["attributes"]["stats"]
                        
                        # 1. Перемога (Chicken Dinner)
                        if stats.get("winPlace") == 1 and win_channel:
                            embed = discord.Embed(
                                title='🍗 WINNER WINNER CHICKEN DINNER!',
                                description=f'**{p["pubgNickname"]}** виграв матч!',
                                color=0xFFCC00
                            )
                            embed.add_field(name='💀 Вбивств', value=str(stats.get('kills', 0)), inline=True)
                            embed.add_field(name='🎯 Шкода', value=str(round(stats.get('damageDealt', 0))), inline=True)
                            
                            mention = f"<@{p['userId']}>" if p.get('userId') and not p.get('isExternal') else f"**{p['pubgNickname']}**"
                            await win_channel.send(content=f"🎉 Вітаємо {mention}!", embed=embed)
                            create_log(f"[WIN] Перемога для {p['pubgNickname']}")
                            await asyncio.sleep(2.0) # Затримка проти спаму
                        
                        # 2. Досягнення
                        if p.get("userId"):
                            await check_achievements(client, p["userId"], p["pubgNickname"], stats, win_channel_id)
                        
                        # 3. Рекорди
                        await check_records(p, stats)
                        
                        # 4. Тижнева статистика
                        p["weeklyWins"] = p.get("weeklyWins", 0) + (1 if stats.get("winPlace") == 1 else 0)
                        p["weeklyKills"] = p.get("weeklyKills", 0) + stats.get("kills", 0)
                        
                        # 5. Місячна статистика
                        p["monthlyWins"] = p.get("monthlyWins", 0) + (1 if stats.get("winPlace") == 1 else 0)
                        p["monthlyKills"] = p.get("monthlyKills", 0) + stats.get("kills", 0)
                
                # Оновлюємо останній перевірений матч
                p["lastCheckedMatchId"] = matches_to_process[0]
                await save_data()
                
            except Exception as e:
                create_log(f"[ERROR] Помилка перевірки матчів для {p.get('pubgNickname')}: {e}")
                
        add_to_queue(task)
