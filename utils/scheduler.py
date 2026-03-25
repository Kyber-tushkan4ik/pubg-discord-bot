import discord
from discord.ext import tasks
import asyncio
import os
import json
import time
from datetime import datetime, timezone

from .data_handler import get_data, save_data, mark_dirty
from .pubg_api import get_player, get_player_season_stats, get_latest_match_date, get_match, get_players_batch
from .helpers import create_log, ms_to_readable
from .achievements import check_achievements
from .records import check_records

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

queue = asyncio.Queue()
_first_match_scan_done = False
_queue_worker_started = False

async def process_queue():
    global _queue_worker_started
    if _queue_worker_started:
        return
    _queue_worker_started = True
    
    while True:
        task = await queue.get()
        try:
            await asyncio.wait_for(task(), timeout=45.0)
        except Exception as e:
            create_log(f"[QUEUE ERROR] {e}")
        finally:
            queue.task_done()
            await asyncio.sleep(CONFIG.get("API_DELAY_MS", 15000) / 1000.0)

def add_to_queue(task):
    queue.put_nowait(task)

async def send_log(bot, message):
    log_channel_id = CONFIG.get("LOG_CHANNEL_ID")
    if not log_channel_id:
        return
    
    channel = bot.get_channel(int(log_channel_id))
    if channel:
        await channel.send(f"📋 {message}")

def init_scheduler(client: discord.Client):
    if not _queue_worker_started:
        client.loop.create_task(process_queue())
    
    @tasks.loop(hours=24)
    async def daily_tasks():
        create_log("[SCHEDULER] Запуск щоденних завдань...")
        await check_inactivity(client)
        
        from .data_handler import get_settings, save_settings
        settings = get_settings()
        today_str = time.strftime("%Y-%m-%d")
        
        # Щотижневий звіт (неділя)
        if time.localtime().tm_wday == 6 and settings.get("lastWeeklyReportDate") != today_str:
            await send_weekly_report(client)
            settings["lastWeeklyReportDate"] = today_str
            await save_settings()
            
        # Скидання тижневої статистики (понеділок)
        if time.localtime().tm_wday == 0 and settings.get("lastWeeklyResetDate") != today_str:
            user_data = get_data()
            for p in user_data.values():
                p["weeklyWins"] = 0
                p["weeklyKills"] = 0
            await save_data()
            settings["lastWeeklyResetDate"] = today_str
            await save_settings()
            create_log("[SCHEDULER] Тижневу статистику скинуто.")
            
    @tasks.loop(minutes=60)
    async def hourly_tasks():
        await update_stats_and_ranks(client)

    @tasks.loop(minutes=30)
    async def match_check_tasks():
        await check_recent_matches(client)

    @tasks.loop(minutes=5)
    async def heartbeat_tasks():
        user_data = get_data()
        now = int(time.time() * 1000)
        count = 0
        for key, p in user_data.items():
            if p.get("isActive") and p.get("lastSessionStart") and not p.get("isPaused"):
                duration = now - p["lastSessionStart"]
                if 0 < duration < 3600000:
                    p["totalPlayTime"] = p.get("totalPlayTime", 0) + duration
                    p["lastSessionStart"] = now
                    count += 1
        if count > 0:
            await save_data()

    daily_tasks.start()
    hourly_tasks.start()
    match_check_tasks.start()
    heartbeat_tasks.start()
    create_log('[SCHEDULER] Всі завдання планувальника активовано.')

async def send_weekly_report(client):
    create_log('[SCHEDULER] Генерування щотижневого звіту...')
    user_data = get_data()
    players = [p for p in user_data.values() if p.get("pubgNickname")]
    if not players: return
    
    report_ch_id = CONFIG.get("WEEKLY_REPORT_CHANNEL_ID")
    if not report_ch_id: return
    report_ch = client.get_channel(int(report_ch_id))
    if not report_ch: return
    
    active = sorted(players, key=lambda p: p.get("weeklyKills", 0), reverse=True)[:5]
    embed = discord.Embed(title='📊 ТОП-5 Гравців Тижня (Kills)', color=0x0099ff)
    for i, p in enumerate(active):
        embed.add_field(name=f"{i+1}. {p['pubgNickname']}", value=f"Вбивств: {p.get('weeklyKills', 0)}, Перемог: {p.get('weeklyWins', 0)}", inline=False)
    await report_ch.send(embed=embed)

async def check_inactivity(client):
    user_data = get_data()
    players = [x for x in user_data.values() if x.get("pubgNickname")]
    
    for i in range(0, len(players), 10):
        batch = players[i:i+10]
        nicknames = [p["pubgNickname"] for p in batch]
        
        async def batch_task(nicks=nicknames, b=batch):
            pubg_players = await get_players_batch(nicks)
            for pubg_data in pubg_players:
                try:
                    p_nick_low = pubg_data["attributes"]["name"].lower()
                    player = next((p for p in b if p["pubgNickname"].lower() == p_nick_low), None)
                    if not player: continue
                    
                    last_date = await get_latest_match_date(pubg_data)
                    if not last_date: continue
                    last_dt = datetime.fromisoformat(last_date.replace('Z', '+00:00'))
                    inactive_days = (datetime.now(timezone.utc) - last_dt).days
                    if inactive_days >= CONFIG.get("INACTIVITY_DAYS_LIMIT", 14):
                        create_log(f"[INACTIVE] {player['pubgNickname']} не активний {inactive_days} дн.")
                except Exception as e:
                    create_log(f"[ERROR INACTIVITY] {e}")
        add_to_queue(batch_task)

async def update_stats_and_ranks(bot):
    create_log('[SCHEDULER] Оновлення статики та рангів...')
    user_data = get_data()
    players_list = [(k, v) for k, v in user_data.items() if v.get("pubgNickname")]
    
    for i in range(0, len(players_list), 10):
        batch = players_list[i:i+10]
        nicknames = [p[1]["pubgNickname"] for p in batch]
        
        async def batch_task(nicks=nicknames, b=batch):
            pubg_players = await get_players_batch(nicks)
            for pubg_data in pubg_players:
                try:
                    p_nick_low = pubg_data["attributes"]["name"].lower()
                    entry = next((e for e in b if e[1]["pubgNickname"].lower() == p_nick_low), None)
                    if not entry: continue
                    key, p = entry
                    
                    stats = await get_player_season_stats(pubg_data["id"], 'lifetime')
                    if not stats or "attributes" not in stats: continue
                    
                    gm_stats = stats["attributes"]["gameModeStats"]
                    squad_stats = gm_stats.get('squad-fpp') or gm_stats.get('squad') or gm_stats.get('squadFPP')
                    if not squad_stats: continue
                    
                    # Оновлення даних
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
                    mark_dirty(key)
                    await save_data()
                    
                    # Оновлення ролей
                    u_id = p.get("userId")
                    g_id = p.get("guildId")
                    if not u_id or p.get("isExternal"): continue
                    guild = bot.get_guild(int(g_id))
                    if not guild: continue
                    
                    # Оптимізація: спочатку пробуємо get_member (кеш)
                    member = guild.get_member(int(u_id))
                    if not member:
                        try:
                            member = await guild.fetch_member(int(u_id))
                        except: continue
                    if not member: continue
                    
                    rank_roles = CONFIG.get("RANK_ROLES", {})
                    target_role_name = "Новачок"
                    for role_name, min_kd in sorted(rank_roles.items(), key=lambda x: x[1], reverse=True):
                        if kd >= min_kd:
                            target_role_name = role_name
                            break
                    
                    if not any(r.name == target_role_name for r in member.roles):
                        role_obj = discord.utils.get(guild.roles, name=target_role_name)
                        if not role_obj:
                            role_obj = await guild.create_role(name=target_role_name)
                        
                        to_remove = [r for r in member.roles if r.name in rank_roles and r.name != target_role_name]
                        if to_remove: await member.remove_roles(*to_remove)
                        await member.add_roles(role_obj)
                        create_log(f"[RANK] {p['pubgNickname']} -> {target_role_name}")

                    await check_special_roles(bot, guild, member, squad_stats, p['pubgNickname'])
                except Exception as e:
                    create_log(f"[ERROR STATS BATCH] {e}")
        add_to_queue(batch_task)

async def check_special_roles(bot, guild, member, stats, nickname):
    special_roles = CONFIG.get("SPECIAL_ROLES", {})
    earned_roles = []
    
    for role_name, criteria in special_roles.items():
        passed = False
        if role_name == 'Санітар':
            passed = stats.get('revives', 0) >= criteria.get('revives', 15) or stats.get('heals', 0) >= criteria.get('heals', 80)
        elif role_name == 'Ліквідатор':
            ratio = stats.get('headshotKills', 0) / (stats.get('kills', 1) or 1)
            passed = stats.get('kills', 0) >= criteria.get('minKills', 10) and ratio >= criteria.get('headshotRatio', 0.25)
        elif role_name == 'Берсерк':
            avg_dmg = stats.get('damageDealt', 0) / (stats.get('roundsPlayed', 1) or 1)
            passed = avg_dmg >= criteria.get('avgDamage', 250)
        elif role_name == 'Бойовий товариш':
            passed = stats.get('assists', 0) >= criteria.get('assists', 5)
        elif role_name == 'Перевізник':
            passed = stats.get('rideDistance', 0) >= criteria.get('rideDistance', 50000)
        elif role_name == 'Скажений Макс (Стат)':
            passed = stats.get('roadKills', 0) >= criteria.get('roadKills', 5)
        elif role_name == 'Скаут':
            passed = stats.get('walkDistance', 0) >= criteria.get('walkDistance', 25000)
        elif role_name == 'Вцілілий':
            ratio = stats.get('top10s', 0) / (stats.get('roundsPlayed', 1) or 1)
            passed = stats.get('roundsPlayed', 0) >= criteria.get('minRounds', 10) and ratio >= criteria.get('top10Ratio', 0.25)
        elif role_name == 'Затятий гравець':
            passed = stats.get('roundsPlayed', 0) >= criteria.get('roundsPlayed', 250)
            
        if passed: earned_roles.append(role_name)
    
    for role_name in earned_roles:
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            role = await guild.create_role(name=role_name, color=discord.Color.gold())
            await send_log(bot, f"🆕 Створена нова спеціальна роль: `{role_name}`")
        if role not in member.roles:
            await member.add_roles(role)
            await send_log(bot, f"🏆 Гравцю {nickname} видано роль: `{role_name}`")
            create_log(f"[SPECIAL] {nickname} -> {role_name}")

async def check_recent_matches(client: discord.Client):
    global _first_match_scan_done
    is_quiet = not _first_match_scan_done
    _first_match_scan_done = True
    
    create_log(f"[SCHEDULER] Перевірка матчів {'(ТИХИЙ РЕЖИМ)' if is_quiet else ''}...")
    user_data = get_data()
    win_channel_id = CONFIG.get("WIN_NOTIF_CHANNEL_ID")
    win_channel = client.get_channel(int(win_channel_id)) if win_channel_id else None
    
    players_list = [(k, v) for k, v in user_data.items() if v.get("pubgNickname")]
    
    for i in range(0, len(players_list), 10):
        batch = players_list[i:i+10]
        nicknames = [p[1]["pubgNickname"] for p in batch]
        
        async def batch_task(nicks=nicknames, b=batch, q=is_quiet):
            pubg_players = await get_players_batch(nicks)
            for pubg_data in pubg_players:
                try:
                    p_id = pubg_data["id"]
                    p_nick_low = pubg_data["attributes"]["name"].lower()
                    entry = next((e for e in b if e[1]["pubgNickname"].lower() == p_nick_low), None)
                    if not entry: continue
                    key, p = entry
                    
                    matches = pubg_data.get("relationships", {}).get("matches", {}).get("data", [])
                    if not matches: continue
                    
                    new_matches = []
                    last_checked = p.get("lastCheckedMatchId")
                    for m in matches:
                        if m["id"] == last_checked: break
                        new_matches.append(m["id"])
                    
                    if not new_matches: continue
                    
                    # Запам'ятовуємо останній матч ВІДРАЗУ
                    p["lastCheckedMatchId"] = new_matches[0]
                    mark_dirty(key)
                    await save_data()
                    
                    if q:
                        create_log(f"[MATCH] Тихе оновлення для {p['pubgNickname']} ({len(new_matches)} матчів)")
                        continue

                    for mid in reversed(new_matches[:5]):
                        try:
                            match = await get_match(mid)
                            if not match or "data" not in match: continue
                            
                            try:
                                c_at_str = match["data"]["attributes"]["createdAt"]
                                c_at = datetime.fromisoformat(c_at_str.replace('Z', '+00:00'))
                                if (datetime.now(timezone.utc) - c_at).total_seconds() > 7200: continue
                            except: pass

                            stats = None
                            for inc in match.get("included", []):
                                if inc["type"] == 'participant' and inc.get("attributes", {}).get("stats", {}).get("playerId") == p_id:
                                    stats = inc["attributes"]["stats"]
                                    break
                            
                            if stats:
                                if stats.get("winPlace") == 1:
                                    mention = f"<@{p['userId']}>" if p.get('userId') and not p.get('isExternal') else f"**{p['pubgNickname']}**"
                                    if win_channel:
                                        embed = discord.Embed(title='🍗 ПЕРЕМОГА!', description=f'**{p["pubgNickname"]}** виграв матч!', color=0xFFCC00)
                                        embed.add_field(name='💀 Вбивств', value=str(stats.get('kills', 0)), inline=True)
                                        embed.add_field(name='🎯 Шкода', value=str(round(stats.get('damageDealt', 0))), inline=True)
                                        await win_channel.send(content=f"🎉 Вітаємо {mention}!", embed=embed)
                                    create_log(f"[WIN] {p['pubgNickname']} переміг!")
                                
                                if p.get("userId"):
                                    await check_achievements(client, p["userId"], p["pubgNickname"], stats, win_channel_id)
                                await check_records(p, stats)
                                
                                p["weeklyWins"] = p.get("weeklyWins", 0) + (1 if stats.get("winPlace") == 1 else 0)
                                p["weeklyKills"] = p.get("weeklyKills", 0) + stats.get("kills", 0)
                                p["monthlyWins"] = p.get("monthlyWins", 0) + (1 if stats.get("winPlace") == 1 else 0)
                                p["monthlyKills"] = p.get("monthlyKills", 0) + stats.get("kills", 0)
                                mark_dirty(key)
                        except Exception as e:
                            create_log(f"[ERROR MATCH PROC] {p['pubgNickname']} {mid}: {e}")
                    await save_data()
                except Exception as e:
                    create_log(f"[ERROR BATCH MATCH] {e}")
        add_to_queue(batch_task)
