import discord
import time
import json
import os
from .data_handler import get_data, save_data, get_settings
from .helpers import create_log, ms_to_readable, get_record_key

# Завантаження конфігу
CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

async def send_log(client, message):
    log_ch_id = CONFIG.get("LOG_CHANNEL_ID")
    if log_ch_id and log_ch_id != "YOUR_LOG_CHANNEL_ID_HERE":
        try:
            channel = await client.fetch_channel(int(log_ch_id))
            if channel:
                await channel.send(message)
        except Exception as e:
            print(f"Помилка лог-каналу: {e}")

async def handle_success(member: discord.Member, time_taken_ms: int, play_time_ms: int):
    create_log(f"[SUCCESS] {member.name} (ID: {member.id}) passed adaptation.")
    try:
        guild = member.guild
        role_adapt = discord.utils.get(guild.roles, name=CONFIG.get("ROLE_ADAPT"))
        role_success = discord.utils.get(guild.roles, name=CONFIG.get("ROLE_SUCCESS"))

        if role_adapt in member.roles:
            await member.remove_roles(role_adapt)
        if role_success:
            await member.add_roles(role_success)

        embed = discord.Embed(
            title='🎉 Адаптацію успішно пройдено!',
            description=f'Вітаємо, {member.mention}! Ти успішно пройшов етап адаптації у клані.',
            color=0x4CAF50
        )
        embed.add_field(name='🎮 Час у грі', value=ms_to_readable(play_time_ms), inline=True)
        embed.add_field(name='⏱️ Загальний час', value=ms_to_readable(time_taken_ms), inline=True)
        embed.add_field(name='🏆 Нова роль', value=f'**{CONFIG.get("ROLE_SUCCESS")}**', inline=False)
        embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
        embed.set_footer(text='PUBG Bot System')
        
        try:
            await member.send(embed=embed)
            create_log(f"[DM SENT] To: {member.name} Content: 🎉 Адаптацію успішно пройдено! ({ms_to_readable(play_time_ms)})")
        except:
            create_log(f"[DM FAILED] User {member.name} has DMs closed.")

        days = time_taken_ms // (24 * 3600000)
        hours = (time_taken_ms % (24 * 3600000)) // 3600000
        await send_log(member.client, f"✅ Користувач **{member.mention}** пройшов адаптацію за {days} дн. {hours} год.")
    except Exception as e:
        print(f"Error in handle_success: {e}")

async def check_user(member: discord.Member, user_id: str):
    user_data = get_data()
    key = get_record_key(user_id, str(member.guild.id))
    record = user_data.get(key)

    if record and record.get("totalPlayTime", 0) >= CONFIG.get("REQUIRED_PLAY_MS", 0):
        record["isActive"] = False
        record["result"] = 'success'
        await save_data()
        elapsed = int(time.time() * 1000) - record.get("startTime", 0)
        await handle_success(member, elapsed, record["totalPlayTime"])

async def check_all_users(client: discord.Client):
    now = int(time.time() * 1000)
    user_data = get_data()
    made_changes = False
    
    for key, record in user_data.items():
        if not record.get("isActive") or record.get("isPaused"):
            continue

        current_total = record.get("totalPlayTime", 0)
        last_session = record.get("lastSessionStart")
        if last_session:
            current_total += (now - last_session)

        elapsed = now - record.get("startTime", 0)
        limit = CONFIG.get("TIME_LIMIT_MS", 0) + record.get("limitOffset", 0)

        guild_id = record.get("guildId")
        guild = client.get_guild(int(guild_id)) if guild_id else None
        
        # Якщо сервер не знайдено за ID, спробуємо знайти користувача в усіх доступних гільдіях (окрім Котяри)
        if not guild:
            for g in client.guilds:
                if "Котяри" in g.name: continue
                member = g.get_member(int(record.get("userId") or key))
                if member:
                    guild = g
                    break

        if not guild:
            continue
            
        user_id = record.get("userId") or key

        if elapsed > limit:
            if current_total < CONFIG.get("REQUIRED_PLAY_MS", 0):
                create_log(f"[FAIL] {record.get('username')} time expired.")
                record["isActive"] = False
                record["result"] = 'failed'
                made_changes = True
                try:
                    member = await guild.fetch_member(int(user_id))
                    msg = "😔 **Адаптація не пройдена**\nНа жаль, час вийшов."
                    await member.send(msg)
                    create_log(f"[DM SENT] To: {member.name} Content: {msg.replace(chr(10), ' ')}")
                except:
                    pass
                continue

        if current_total >= CONFIG.get("REQUIRED_PLAY_MS", 0):
            record["isActive"] = False
            record["totalPlayTime"] = current_total
            record["lastSessionStart"] = None
            record["result"] = 'success'
            made_changes = True
            try:
                member = await guild.fetch_member(int(user_id))
                await handle_success(member, elapsed, current_total)
            except:
                pass

    if made_changes:
        await save_data()

async def perform_startup_scan(client: discord.Client):
    if not client.guilds:
        return
    
    for guild in client.guilds:
        # Пропускаємо сервер Котяри за запитом користувача
        if "Котяри" in guild.name:
            # create_log(f"[SCAN] Пропускаємо сервер: {guild.name}")
            continue

        print(f"Сканування серверу: {guild.name}")
        
        try:
            members = await guild.chunk() if not guild.chunked else guild.members
        except Exception:
            members = guild.members
            
        user_data = get_data()
        count = 0
        now = int(time.time() * 1000)

        for member in members:
            if member.bot:
                continue

            key = get_record_key(str(member.id), str(guild.id))
            
            has_adapt = discord.utils.get(member.roles, name=CONFIG.get("ROLE_ADAPT")) is not None
            has_clan = discord.utils.get(member.roles, name=CONFIG.get("ROLE_SUCCESS")) is not None
            
            is_playing = False
            for a in member.activities:
                if a.name == CONFIG.get("GAME_NAME"):
                    # Перевіряємо деталі для врахування лише часу в матчі
                    if hasattr(a, 'details') and a.details:
                        details = a.details.lower()
                        if any(word in details for word in ["match", "матч", "playing", "грає"]):
                            is_playing = True
                            break
                    else:
                        # Якщо деталей немає, рахуємо за назвою
                        is_playing = True
                        break

            # 1. Ініціалізація адаптації
            if has_adapt:
                if key not in user_data and str(member.id) not in user_data:
                    create_log(f"[AUTO-START] Знайдено {member.name}")
                    user_data[key] = {
                        "startTime": now,
                        "totalPlayTime": 0,
                        "isActive": True,
                        "username": str(member),
                        "guildId": str(guild.id),
                        "userId": str(member.id)
                    }
                    count += 1

                record = user_data.get(key) or user_data.get(str(member.id))
                if record and record.get("isActive"):
                    last_session = record.get("lastSessionStart")
                    if is_playing:
                        if not last_session:
                            record["lastSessionStart"] = now
                            count += 1
                    else:
                        if last_session:
                            duration = now - last_session
                            # Обмеження на випадок тривалого крашу бота (макс 6 годин за раз)
                            duration = min(duration, 6 * 3600000) 
                            record["totalPlayTime"] = record.get("totalPlayTime", 0) + duration
                            record["lastSessionStart"] = None
                            count += 1
                    
                    if not record.get("guildId"): record["guildId"] = str(guild.id)
                    if not record.get("userId"): record["userId"] = str(member.id)

            # 2. Відстеження клану
            if has_clan:
                if key not in user_data and str(member.id) not in user_data:
                    user_data[key] = {"username": str(member), "userId": str(member.id), "guildId": str(guild.id)}
                
                c_record = user_data.get(key) or user_data.get(str(member.id))
                if not c_record.get("lastPubgSeen") and is_playing:
                    c_record["lastPubgSeen"] = now
                    count += 1

    if count > 0:
        await save_data()

    # YTM Check
    bot_settings = get_settings()
    ytm_source = bot_settings.get("ytmSource")
    if ytm_source:
        try:
            src = guild.get_member(int(ytm_source))
            if src:
                for a in src.activities:
                    if a.name in ['YouTube Music', 'Spotify']:
                        state = f"{a.details} - {a.state}" if hasattr(a, 'details') and hasattr(a, 'state') else a.name
                        await client.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=state))
                        break
        except:
            pass
