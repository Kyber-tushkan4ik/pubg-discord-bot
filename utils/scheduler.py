import discord
from discord.ext import tasks
import asyncio
import os
import json
import time
from datetime import datetime, timezone

from .data_handler import get_data, save_data, mark_dirty, get_settings, save_settings
from .pubg_api import get_player, get_player_season_stats, get_latest_match_date, get_match, get_players_batch
from .helpers import create_log, ms_to_readable, translate_map, cleanup_old_assets
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
            await asyncio.wait_for(task(), timeout=300.0)
        except asyncio.TimeoutError:
            create_log(f"[QUEUE ERROR] Task timed out (300s)")
        except Exception as e:
            create_log(f"[QUEUE ERROR] {type(e).__name__}: {e}")
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
        
        settings = get_settings()
        today_str = time.strftime("%Y-%m-%d")
        
        # Щотижневий звіт та скидання статистики (понеділок)
        if time.localtime().tm_wday == 0:
            if settings.get("lastWeeklyReportDate") != today_str:
                await send_weekly_report(client)
                settings["lastWeeklyReportDate"] = today_str
                await save_settings()
                
            if settings.get("lastWeeklyResetDate") != today_str:
                user_data = get_data()
                for p in user_data.values():
                    p["weeklyWins"] = 0
                    p["weeklyKills"] = 0
                await save_data()
                settings["lastWeeklyResetDate"] = today_str
                await save_settings()
                cleanup_old_assets(max_age_hours=0) # Глибоке очищення всіх тимчасових файлів щопонеділка
                create_log("[SCHEDULER] Тижневу статистику скинуто, проведено глибоке очищення файлів.")

        # Щомісячний звіт та скидання (1-ше число)
        if time.localtime().tm_mday == 1 and settings.get("lastMonthlyReportDate") != today_str:
            await send_monthly_report(client)
            settings["lastMonthlyReportDate"] = today_str
            
            # Скидання місячної статистики
            user_data = get_data()
            for p in user_data.values():
                p["monthlyWins"] = 0
                p["monthlyKills"] = 0
            await save_data()
            settings["lastMonthlyResetDate"] = today_str
            await save_settings()
            create_log("[SCHEDULER] Місячний звіт надіслано, статистику скинуто.")
            
    @tasks.loop(minutes=60)
    async def hourly_tasks():
        await update_stats_and_ranks(client)
        cleanup_old_assets() # Додаємо очищення старих зображень

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
    players = [p for p in user_data.values() if p.get("pubgNickname") and (p.get("weeklyWins", 0) > 0 or p.get("weeklyKills", 0) > 0)]
    if not players: return
    
    bot_settings = get_settings()
    report_ch_id = bot_settings.get("reportsChannelId") or CONFIG.get("WEEKLY_REPORT_CHANNEL_ID") or CONFIG.get("LOG_CHANNEL_ID")
    if not report_ch_id: return
    report_ch = client.get_channel(int(report_ch_id))
    if not report_ch:
        try: report_ch = await client.fetch_channel(int(report_ch_id))
        except: return
    
    # Сортування: Перемоги, потім вбивства
    players.sort(key=lambda p: (p.get("weeklyWins", 0), p.get("weeklyKills", 0)), reverse=True)
    
    embed = discord.Embed(
        title='🍗 Тиждень виживання завершено!',
        description="Хто тут з'їв найбільше курки?\n\n",
        color=0xFFA500
    )
    
    table = "```\n#  Гравець          🏆  💀\n"
    table += "----------------------------\n"
    for i, p in enumerate(players[:10]):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        nick = p['pubgNickname'][:14].ljust(14)
        wins = str(p.get("weeklyWins", 0)).rjust(2)
        kills = str(p.get("weeklyKills", 0)).rjust(3)
        table += f"{medal.ljust(2)} {nick} {wins} {kills}\n"
    table += "```"
    
    embed.description += table
    embed.set_footer(text="Підсумки за останній тиждень.")
    await report_ch.send(embed=embed)

async def send_monthly_report(client):
    create_log('[SCHEDULER] Генерування щомісячного звіту...')
    user_data = get_data()
    players = [p for p in user_data.values() if p.get("pubgNickname") and (p.get("monthlyWins", 0) > 0 or p.get("monthlyKills", 0) > 0)]
    if not players: return
    
    bot_settings = get_settings()
    report_ch_id = bot_settings.get("reportsChannelId") or CONFIG.get("WEEKLY_REPORT_CHANNEL_ID") or CONFIG.get("LOG_CHANNEL_ID")
    report_ch = client.get_channel(int(report_ch_id))
    if not report_ch:
        try: report_ch = await client.fetch_channel(int(report_ch_id))
        except: return
    
    players.sort(key=lambda p: (p.get("monthlyWins", 0), p.get("monthlyKills", 0)), reverse=True)
    
    embed = discord.Embed(
        title='🦖 Наш УАЗік проїхав ще один місяць!',
        description="Ось список пасажирів-чемпіонів:\n\n",
        color=0x3498DB
    )
    
    table = "```\n#  Гравець          🏆  💀\n"
    table += "----------------------------\n"
    for i, p in enumerate(players[:15]):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        nick = p['pubgNickname'][:14].ljust(14)
        wins = str(p.get("monthlyWins", 0)).rjust(2)
        kills = str(p.get("monthlyKills", 0)).rjust(3)
        table += f"{medal.ljust(2)} {nick} {wins} {kills}\n"
    table += "```"
    
    embed.description += table
    embed.set_footer(text=f"Підсумки за {time.strftime('%B %Y')}")
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
                    
                    await process_single_player_stats_and_ranks(bot, key, p, pubg_data)
                except Exception as e:
                    create_log(f"[ERROR STATS BATCH] {e}")
        add_to_queue(batch_task)

async def check_special_roles(bot, guild, member, stats, nickname, debug_channel=None):
    special_roles = CONFIG.get("SPECIAL_ROLES", {})
    earned_roles = []
    
    for role_name, criteria in special_roles.items():
        passed = False
        if 'Санітар' in role_name:
            passed = stats.get('revives', 0) >= criteria.get('revives', 15) or stats.get('heals', 0) >= criteria.get('heals', 80)
        elif 'Ліквідатор' in role_name:
            ratio = stats.get('headshotKills', 0) / (stats.get('kills', 1) or 1)
            passed = stats.get('kills', 0) >= criteria.get('minKills', 10) and ratio >= criteria.get('headshotRatio', 0.25)
        elif 'Берсерк' in role_name:
            avg_dmg = stats.get('damageDealt', 0) / (stats.get('roundsPlayed', 1) or 1)
            passed = avg_dmg >= criteria.get('avgDamage', 250)
        elif 'Бойовий товариш' in role_name:
            passed = stats.get('assists', 0) >= criteria.get('assists', 5)
        elif 'Перевізник' in role_name:
            passed = stats.get('rideDistance', 0) >= criteria.get('rideDistance', 50000)
        elif 'Скажений Макс' in role_name:
            passed = stats.get('roadKills', 0) >= criteria.get('roadKills', 5)
        elif 'Скаут' in role_name:
            passed = stats.get('walkDistance', 0) >= criteria.get('walkDistance', 25000)
        elif 'Вцілілий' in role_name:
            ratio = stats.get('top10s', 0) / (stats.get('roundsPlayed', 1) or 1)
            passed = stats.get('roundsPlayed', 0) >= criteria.get('minRounds', 10) and ratio >= criteria.get('top10Ratio', 0.25)
        elif 'Затятий гравець' in role_name:
            passed = stats.get('roundsPlayed', 0) >= criteria.get('roundsPlayed', 250)
            
        if passed: earned_roles.append(role_name)
    
    created_roles = []
    granted_roles = []
    
    for role_name in earned_roles:
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            color_hex = special_roles.get(role_name, {}).get("color", "0xf1c40f")
            role_color = discord.Color(int(color_hex, 16))
            role = await guild.create_role(name=role_name, color=role_color)
            created_roles.append(role_name)
        if role not in member.roles:
            await member.add_roles(role)
            granted_roles.append(role_name)
            create_log(f"[SPECIAL] {nickname} -> {role_name}")
            
    if created_roles:
        created_str = ", ".join([f"`{r}`" for r in created_roles])
        await send_log(bot, f"🆕 Створені нові спеціальні ролі: {created_str}")

    if granted_roles:
        granted_str = ", ".join([f"`{r}`" for r in granted_roles])
        await send_log(bot, f"🏆 Гравцю **{nickname}** видано ролі: {granted_str}")
        if debug_channel: await debug_channel.send(f"🎖️ **Видано спецролі**: {granted_str}")
            
    # Автоматичне видалення старих (замінених) ролей
    deprecated = {
        "Медик": "Санітар",
        "Головоріз": "Ліквідатор",
        "Термінатор": "Ліквідатор",
        "Асистент": "Бойовий товариш",
        "Водій": "Перевізник",
        "Водій (Стат)": "Перевізник",
        "Мандрівник": "Скаут",
        "Виживач": "Вцілілий",
        "Задрот": "Затятий гравець",
        "Скажений Макс": "Скажений Макс (Стат)"
    }
    
    for old_name, new_name in deprecated.items():
        if new_name in earned_roles or any(r.name == new_name for r in member.roles):
            old_role = discord.utils.get(guild.roles, name=old_name)
            if old_role and old_role in member.roles:
                await member.remove_roles(old_role)
                create_log(f"[CLEANUP] Removed {old_name} from {nickname} because they have {new_name}")
    
    if debug_channel and not earned_roles:
        await debug_channel.send("🔍 Жодних нових спеціальних ролей не виявлено.")

async def check_recent_matches(client: discord.Client):
    global _first_match_scan_done
    is_quiet = not _first_match_scan_done
    _first_match_scan_done = True
    
    create_log(f"[SCHEDULER] Перевірка матчів {'(ТИХИЙ РЕЖИМ)' if is_quiet else ''}...")
    user_data = get_data()
    bot_settings = get_settings()
    win_channel_id = bot_settings.get("reportsChannelId") or CONFIG.get("WIN_NOTIF_CHANNEL_ID")
    win_channel = client.get_channel(int(win_channel_id)) if win_channel_id else None
    if not win_channel and win_channel_id:
        try: win_channel = await client.fetch_channel(int(win_channel_id))
        except: pass
    
    players_list = [(k, v) for k, v in user_data.items() if v.get("pubgNickname")]
    
    for i in range(0, len(players_list), 10):
        batch = players_list[i:i+10]
        nicknames = [p[1]["pubgNickname"] for p in batch]
        
        async def batch_task(nicks=nicknames, b=batch, q=is_quiet):
            pubg_players = await get_players_batch(nicks)
            for pubg_data in pubg_players:
                try:
                    p_nick_low = pubg_data["attributes"]["name"].lower()
                    entry = next((e for e in b if e[1]["pubgNickname"].lower() == p_nick_low), None)
                    if not entry: continue
                    key, p = entry
                    
                    # Викликаємо спільну функцію обробки
                    await process_single_player_matches(client, key, p, pubg_data, is_quiet=q)
                    
                except Exception as e:
                    create_log(f"[ERROR BATCH MATCH] {e}")
        add_to_queue(batch_task)

async def process_single_player_matches(client: discord.Client, key, p, pubg_data, is_quiet=False, debug_channel=None):
    """
    Обробляє нові матчі для одного гравця.
    Якщо вказано debug_channel, туди будуть надсилатися детальні звіти.
    """
    p_id = pubg_data["id"]
    p_nickname = pubg_data["attributes"]["name"]
    
    relationships = pubg_data.get("relationships", {})
    matches_data = relationships.get("matches", {})
    matches = matches_data.get("data", [])
    
    if not matches:
        if debug_channel: await debug_channel.send(f"🔍 Гравця **{p_nickname}**: Матчів не знайдено.")
        return 0

    new_matches = []
    last_checked = p.get("lastCheckedMatchId")
    for m in matches:
        if m["id"] == last_checked: break
        new_matches.append(m["id"])

    if not new_matches:
        if debug_channel: await debug_channel.send(f"🔍 Гравця **{p_nickname}**: Нових матчів немає (останній перевірений: `{last_checked}`).")
        return 0

    # Запам'ятовуємо останній матч ВІДРАЗУ
    p["lastCheckedMatchId"] = new_matches[0]
    mark_dirty(key)
    await save_data()

    if is_quiet:
        create_log(f"[MATCH] Тихе оновлення для {p_nickname} ({len(new_matches)} матчів)")
        if debug_channel: await debug_channel.send(f"🤫 Гравця **{p_nickname}**: Тихе оновлення ({len(new_matches)} матчів).")
        return len(new_matches)

    bot_settings = get_settings()
    win_channel_id = bot_settings.get("reportsChannelId") or CONFIG.get("WIN_NOTIF_CHANNEL_ID")
    win_channel = client.get_channel(int(win_channel_id)) if win_channel_id else None
    if not win_channel and win_channel_id:
        try: win_channel = await client.fetch_channel(int(win_channel_id))
        except: pass
    
    processed_count = 0
    for mid in reversed(new_matches[:5]):
        try:
            match = await get_match(mid)
            if not match or "data" not in match: 
                if debug_channel: await debug_channel.send(f"⚠️ Не вдалося отримати деталі матчу `{mid}`.")
                continue
            
            # Перевірка свіжості матчу (тільки якщо не дебаг)
            if not debug_channel:
                try:
                    c_at_str = match["data"]["attributes"]["createdAt"]
                    c_at = datetime.fromisoformat(c_at_str.replace('Z', '+00:00'))
                    if (datetime.now(timezone.utc) - c_at).total_seconds() > 7200: 
                        continue
                except: pass

            stats = None
            for inc in match.get("included", []):
                if inc["type"] == 'participant' and inc.get("attributes", {}).get("stats", {}).get("playerId") == p_id:
                    stats = inc["attributes"]["stats"]
                    break
            
            if stats:
                processed_count += 1
                if debug_channel:
                    msg = (f"🎮 **Знайдено матч** `{mid}`:\n"
                           f"• Місце: **{stats.get('winPlace')}**\n"
                           f"• Вбивств: **{stats.get('kills')}**\n"
                           f"• Шкода: **{round(stats.get('damageDealt'))}**")
                    await debug_channel.send(msg)

                if stats.get("winPlace") == 1:
                    bot_settings = get_settings()
                    reported = bot_settings.get("reportedMatches", [])
                    
                    if mid not in reported:
                        reported.append(mid)
                        if len(reported) > 100:
                            reported = reported[-100:]
                        bot_settings["reportedMatches"] = reported
                        await save_settings()
                        
                        clan_winners = []
                        mentions = []
                        
                        user_data = get_data()
                        clan_users_low = {u.get("pubgNickname", "").lower(): u for u in user_data.values() if u.get("pubgNickname")}
                        
                        # Пошук усіх переможців з клану в цьому матчі
                        for inc in match.get("included", []):
                            if inc["type"] == 'participant':
                                p_stats = inc.get("attributes", {}).get("stats", {})
                                if p_stats.get("winPlace") == 1:
                                    n_low = p_stats.get("name", "").lower()
                                    if n_low in clan_users_low:
                                        u_data = clan_users_low[n_low]
                                        m = f"<@{u_data['userId']}>" if u_data.get('userId') and not u_data.get('isExternal') else f"**{p_stats.get('name')}**"
                                        if m not in mentions:
                                            mentions.append(m)
                                            clan_winners.append(f"• {m} — 💀 Вбивств: **{p_stats.get('kills', 0)}** | 🎯 Шкода: **{round(p_stats.get('damageDealt', 0))}**")
                        
                        # --- ЖОРСТКЕ ОБМЕЖЕННЯ ТА НАДСИЛАННЯ СПОВІЩЕННЯ (ПОЗА ЦИКЛОМ) ---
                        message_sent_for_this_match = False
                        
                        if clan_winners and not message_sent_for_this_match:
                            m_attr = match.get("data", {}).get("attributes", {})
                            raw_mode = m_attr.get("gameMode", "squad")
                            
                            # Фільтрація TDM
                            if raw_mode == 'tdm':
                                create_log(f"[TDM] Пропуск перемоги у TDM для {p_nickname}")
                                message_sent_for_this_match = True # Позначаємо як оброблене
                            else:
                                mode_map = {
                                    "squad": "Команди TPP",
                                    "squad-fpp": "Команди FPP",
                                    "duo": "Дуо TPP",
                                    "duo-fpp": "Дуо FPP",
                                    "solo": "Соло TPP",
                                    "solo-fpp": "Соло FPP"
                                }
                                nice_mode = mode_map.get(raw_mode, raw_mode.upper())
                                map_name = translate_map(m_attr.get("mapName", "PUBG"))
                                
                                is_squad = len(clan_winners) > 1
                                title = '🍗 ПЕРЕМОГА СКВАДУ!' if is_squad else '🍗 ПЕРЕМОГА!'
                                match_url = f"https://pubglookup.com/matches/{mid}"
                                
                                embed = discord.Embed(
                                    title=title, 
                                    url=match_url,
                                    description=f"Наші розносять лобі! 🚀\n\n**Режим:** `{nice_mode}`\n**Карта:** `{map_name}`\n\n" + "\n".join(clan_winners), 
                                    color=0xFFCC00
                                )
                                embed.add_field(name="🔗 Підтвердження", value=f"[Переглянути деталі на PUBG Lookup]({match_url})", inline=False)
                                embed.set_footer(text="Офіційні дані PUBG API")
        
                                await win_channel.send(content=f"🎉 Вітаємо {' '.join(mentions)}!", embed=embed)
                                create_log(f"[WIN] Перемога зафіксована для матчу {mid} ({len(clan_winners)} гравців з клану)!")
                                message_sent_for_this_match = True
                
                if p.get("userId"):
                    m_attr = match.get("data", {}).get("attributes", {})
                    await check_achievements(client, p["userId"], p_nickname, stats, win_channel_id, game_mode=m_attr.get("gameMode"))
                await check_records(p, stats)
                
                # Оновлення тижневої/місячної статистики
                p["weeklyWins"] = p.get("weeklyWins", 0) + (1 if stats.get("winPlace") == 1 else 0)
                p["weeklyKills"] = p.get("weeklyKills", 0) + stats.get("kills", 0)
                p["monthlyWins"] = p.get("monthlyWins", 0) + (1 if stats.get("winPlace") == 1 else 0)
                p["monthlyKills"] = p.get("monthlyKills", 0) + stats.get("kills", 0)
                mark_dirty(key)
                
        except Exception as e:
            create_log(f"[ERROR MATCH PROC] {p_nickname} {mid}: {e}")
            if debug_channel: await debug_channel.send(f"❌ Помилка обробки матчу `{mid}`: {e}")
            
    await save_data()
    return processed_count

async def process_single_player_stats_and_ranks(bot, key, p, pubg_data, debug_channel=None):
    """
    Оновлює статистику (Lifetime) та ранги для одного гравця.
    """
    p_nickname = pubg_data["attributes"]["name"]
    try:
        stats = await get_player_season_stats(pubg_data["id"], 'lifetime')
        if not stats or "attributes" not in stats:
            if debug_channel: await debug_channel.send(f"⚠️ Не вдалося отримати Lifetime статистику для **{p_nickname}**.")
            return

        gm_stats = stats["attributes"]["gameModeStats"]
        
        # Вибираємо режим з найбільшою кількістю зіграних раундів серед доступних Squad-режимів
        modes_to_check = ['squad-fpp', 'squad', 'squadFPP']
        squad_stats = None
        max_rounds = -1
        
        for m_name in modes_to_check:
            m_data = gm_stats.get(m_name)
            if m_data and m_data.get('roundsPlayed', 0) > max_rounds:
                max_rounds = m_data.get('roundsPlayed', 0)
                squad_stats = m_data
                
        if not squad_stats or max_rounds == 0:
            if debug_channel: await debug_channel.send(f"🔍 Гравця **{p_nickname}**: Немає даних для режиму Squad.")
            return

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
        
        if debug_channel:
            await debug_channel.send(f"📈 **Оновлено статистику** ({p_nickname}):\n• K/D: **{kd}**\n• Wins: **{wins}**\n• Avg Dmg: **{p['avgDamage']}**")

        # Оновлення ролей
        u_id = p.get("userId")
        g_id = p.get("guildId")
        
        # Fallback: пробуємо розпарсити ключ, якщо дані відсутні
        if not u_id or not g_id:
            if '-' in str(key):
                parts = str(key).split('-')
                if not u_id: u_id = parts[0]
                if not g_id: g_id = parts[1]
            else:
                # Якщо ключ - це просто userId (старий формат)
                if not u_id: u_id = str(key)
        
        if not u_id:
            if debug_channel: await debug_channel.send("⚠️ Не вдалося визначити Discord ID користувача для оновлення ролей.")
            return
            
        if p.get("isExternal"):
            if debug_channel: await debug_channel.send("ℹ️ Гравець є зовнішнім (External), ролі Discord не оновлюються.")
            return

        guild = None
        if g_id:
            guild = bot.get_guild(int(g_id))
        
        if not guild and debug_channel:
            # Спробуємо взяти гільдію з каналу дебагу, якщо g_id не знайдено
            guild = debug_channel.guild
            
        if not guild:
            if debug_channel: await debug_channel.send(f"⚠️ Не вдалося знайти сервер (Guild ID: {g_id}) для оновлення ролей.")
            return
        
        member = guild.get_member(int(u_id))
        if not member:
            try: 
                member = await guild.fetch_member(int(u_id))
            except: 
                if debug_channel: await debug_channel.send(f"⚠️ Користувача з ID `{u_id}` не знайдено на сервері.")
                return
        
        if not member: return

        rank_roles = CONFIG.get("RANK_ROLES", {})
        target_role_name = list(rank_roles.keys())[-1] if rank_roles else "🔰 Новачок"
        target_color = "0x2ecc71"
        for role_name, data in sorted(rank_roles.items(), key=lambda x: x[1].get('min_kd', 0), reverse=True):
            if kd >= data.get('min_kd', 0):
                target_role_name = role_name
                target_color = data.get('color', "0x2ecc71")
                break
        
        if not any(r.name == target_role_name for r in member.roles):
            role_obj = discord.utils.get(guild.roles, name=target_role_name)
            if not role_obj:
                role_obj = await guild.create_role(name=target_role_name, color=discord.Color(int(target_color, 16)))
            
            to_remove = [r for r in member.roles if r.name in rank_roles and r.name != target_role_name]
            if to_remove: await member.remove_roles(*to_remove)
            await member.add_roles(role_obj)
            create_log(f"[RANK] {p_nickname} -> {target_role_name}")
            if debug_channel: await debug_channel.send(f"🎖️ **Оновлено ранг**: {target_role_name}")
        else:
            if debug_channel: await debug_channel.send(f"🎖️ Ранг вже актуальний: {target_role_name}")

        await check_special_roles(bot, guild, member, squad_stats, p_nickname, debug_channel=debug_channel)
    except Exception as e:
        create_log(f"[ERROR SINGLE STATS] {p_nickname}: {e}")
        if debug_channel: await debug_channel.send(f"❌ Помилка оновлення рангів: {e}")
