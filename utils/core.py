import discord
import time
import json
import os
from .data_handler import get_data, save_data, get_settings, mark_dirty
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

async def handle_success(member):
    guild = getattr(member, 'guild', None)
    if not guild:
        # Шукаємо сервер, де є роль адаптації
        # Беремо client через внутрішній атрибут або ігноруємо, якщо немає доступу
        client = getattr(member, '_state', getattr(member, '_client', None))
        if client and hasattr(client, '_get_client'):
            client = client._get_client()
            
        if client and hasattr(client, 'guilds'):
            for g in client.guilds:
                if discord.utils.get(g.roles, name=CONFIG.get("ROLE_ADAPT")):
                    guild = g
                    member = g.get_member(member.id) or await g.fetch_member(member.id)
                    break
    
    if not guild or not hasattr(member, 'roles'):
        create_log(f"[ERROR] Could not find guild context or member roles for {member}")
        print(f"Error giving role: Could not find guild context or member roles for {member}")
        return

    create_log(f"[SUCCESS] {member.name} (ID: {member.id}) passed clan introduction.")
    try:
        role_adapt = discord.utils.get(guild.roles, name=CONFIG.get("ROLE_ADAPT"))
        role_success = discord.utils.get(guild.roles, name=CONFIG.get("ROLE_SUCCESS"))

        if role_adapt and role_adapt in member.roles:
            await member.remove_roles(role_adapt)
        if role_success:
            await member.add_roles(role_success)
            
        # Записуємо в БД, що адаптація повністю пройдена
        user_data = get_data()
        key = get_record_key(str(member.id), str(guild.id))
        record = user_data.get(key)
        if not record:
            user_data[key] = {"username": str(member), "userId": str(member.id), "guildId": str(guild.id)}
            record = user_data[key]
        record["intro_done"] = True
        record["intro_started"] = True
        mark_dirty(key)
        await save_data()

        embed = discord.Embed(
            title='🎉 Ознайомлення завершено!',
            description=f'Вітаємо, {member.mention}! Ти став повноправним учасником нашого клану.',
            color=0x4CAF50
        )
        embed.add_field(name='🏆 Нова роль', value=f'**{CONFIG.get("ROLE_SUCCESS")}**', inline=False)
        embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
        embed.set_footer(text='Ти молодець🤗')
        
        try:
            await member.send(embed=embed)
            create_log(f"[DM SENT] To: {member.name} Content: 🎉 Ознайомлення завершено!")
        except Exception as dm_err:
            create_log(f"[DM FAILED] User {member.name} has DMs closed: {dm_err}")

        client_instance = getattr(member, '_state', None)
        if client_instance and hasattr(client_instance, '_get_client'):
            client_instance = client_instance._get_client()
        elif guild and hasattr(guild, 'me') and hasattr(guild.me, '_state'):
            client_instance = guild.me._state._get_client()
            
        if client_instance:
            await send_log(client_instance, f"✅ Користувач **{member.mention}** успішно пройшов ознайомлення та приєднався до клану!")
    except Exception as e:
        create_log(f"[ERROR] handle_success: {e}")
        print(f"Error in handle_success: {e}")

# Функції check_user, check_all_users та perform_startup_scan видалені, 
# оскільки відстеження ігрового часу більше не використовується.

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
            has_clan = discord.utils.get(member.roles, name=CONFIG.get("ROLE_SUCCESS")) is not None
            
            is_playing = False
            for a in member.activities:
                if a.name == CONFIG.get("GAME_NAME"):
                    is_playing = True
                    break

            # Відстеження активності клану (last seen)
            if has_clan:
                if key not in user_data and str(member.id) not in user_data:
                    user_data[key] = {"username": str(member), "userId": str(member.id), "guildId": str(guild.id)}
                
                c_record = user_data.get(key) or user_data.get(str(member.id))
                if not c_record.get("lastPubgSeen") and is_playing:
                    c_record["lastPubgSeen"] = now
                    mark_dirty(key)
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
