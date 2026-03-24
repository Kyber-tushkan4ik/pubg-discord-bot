import discord
from discord.ext import commands
import time
import os
import json
import re
import sqlite3

from utils.data_handler import get_data, save_data, get_settings
from utils.core import check_user, handle_success, send_log
from utils.helpers import create_log, ms_to_readable, get_record_key, find_record

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
DB_FILE = os.path.join(os.path.dirname(__file__), '../database.sqlite')

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

user_messages = {}
ANTI_SPAM_LIMIT = 5
ANTI_SPAM_INTERVAL = 5000

voice_sessions = {}

class EventsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        
        content = message.content.lower()
        user_id = str(message.author.id)
        guild_id = str(message.guild.id)
        
        is_mod_or_admin = any(r.name in CONFIG.get("ROLES_ADMIN", []) for r in message.author.roles)
        if is_mod_or_admin: return
        
        now = int(time.time() * 1000)
        spam_data = user_messages.get(user_id, [])
        recent = [t for t in spam_data if now - t < ANTI_SPAM_INTERVAL]
        recent.append(now)
        user_messages[user_id] = recent
        
        if len(recent) > ANTI_SPAM_LIMIT:
            try: await message.delete()
            except: pass
            await message.channel.send(f"⚠️ {message.author.mention}, припиніть спамити!", delete_after=5)
            
        found_word = None
        for word in CONFIG.get("FORBIDDEN_WORDS", []):
            if re.search(r'\b' + re.escape(word.lower()) + r'\b', content):
                found_word = word
                break
                
        if found_word:
            try: await message.delete()
            except: pass
            await message.channel.send(f"{message.author.mention}, ваші повідомлення містять заборонені слова.", delete_after=5)
            return
            
        url_regex = re.compile(r'(https?://[^\s]+|discord\.gg/[^\s]+|www\.[^\s]+)', re.IGNORECASE)
        is_allowed_channel = str(message.channel.id) in CONFIG.get("ALLOWED_LINK_CHANNELS", [])
        if url_regex.search(content) and not is_allowed_channel:
            try: await message.delete()
            except: pass
            await message.channel.send(f"{message.author.mention}, реклама заборонена.", delete_after=5)
            return

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get("custom_id")
            if custom_id in ["lfg_join", "lfg_leave"]:
                await interaction.response.send_message("LFG Buttons are handled in Slash Commands now", ephemeral=True)
            elif custom_id and custom_id.startswith("adapt_"):
                pass # Handled in adapt commands

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot: return
        create_log(f"[JOIN] {member.name} joined the server.")
        try:
            welcome_msg = CONFIG.get("GREETING_MESSAGE", "").replace("{user}", member.name)
            embed = discord.Embed(title="👋 Ласкаво просимо!", description=welcome_msg, color=0xFFD700)
            if member.guild.icon: embed.set_thumbnail(url=member.guild.icon.url)
            embed.set_footer(text=member.guild.name)
            await member.send(embed=embed)
        except Exception as e:
            create_log(f"[DM FAILED] User {member.name} DMs closed.")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        user_id = str(after.id)
        guild_id = str(after.guild.id)
        key = get_record_key(user_id, guild_id)
        user_data = get_data()
        
        adapt_name = CONFIG.get("ROLE_ADAPT")
        had_adapt = discord.utils.get(before.roles, name=adapt_name) is not None
        has_adapt = discord.utils.get(after.roles, name=adapt_name) is not None
        
        stop_roles = CONFIG.get("ROLES_STOP", [])
        has_stop = any(r.name in stop_roles for r in after.roles)
        
        if not had_adapt and has_adapt:
            if key in user_data and user_data[key].get("isActive"):
                create_log(f"[INFO] {after.name} re-acquired role.")
            else:
                create_log(f"[START] {after.name} started adaptation.")
                user_data[key] = {
                    "startTime": int(time.time() * 1000),
                    "totalPlayTime": 0,
                    "isActive": True,
                    "username": str(after),
                    "guildId": guild_id,
                    "userId": user_id
                }
                hours = CONFIG.get("REQUIRED_PLAY_MS", 0) // 3600000
                try:
                    await after.send(f"Вітаємо з початком адаптації! 🎮\nДякуємо, що доєднався до нас. Тобі потрібно відіграти {hours} годин у PUBG протягом 3 днів.\nБажаємо успіхів!")
                except: pass
                
        record = find_record(user_data, user_id, guild_id)
        
        if has_stop and record and record.get("isActive"):
            create_log(f"[STOP] {after.name} became Staff.")
            record["isActive"] = False
            record["lastSessionStart"] = None
            
        succ_role_name = CONFIG.get("ROLE_SUCCESS")
        if had_adapt and not has_adapt:
            has_succ = discord.utils.get(after.roles, name=succ_role_name) is not None
            if record and record.get("isActive") and not has_succ:
                create_log(f"[STOP] {after.name} lost adaptation manually.")
                record["isActive"] = False
                record["lastSessionStart"] = None
                
        await save_data()

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if not after: return
        user_id = str(after.id)
        guild_id = str(after.guild.id)
        key = get_record_key(user_id, guild_id)
        
        user_data = get_data()
        bot_settings = get_settings()
        
        if str(bot_settings.get("ytmSource")) == user_id:
            for act in after.activities:
                if act.name in ['YouTube Music', 'Spotify']:
                    state = f"{act.details} - {act.state}" if hasattr(act, 'details') and hasattr(act, 'state') else act.name
                    await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=state))
                    break
                    
        adapt_name = CONFIG.get("ROLE_ADAPT")
        succ_name = CONFIG.get("ROLE_SUCCESS")
        
        has_adapt = discord.utils.get(after.roles, name=adapt_name) is not None
        has_clan = discord.utils.get(after.roles, name=succ_name) is not None
        
        if not has_adapt and not has_clan: return
        if has_clan and bot_settings.get("disableClanTracking"): return
        
        game_name = CONFIG.get("GAME_NAME")
        is_playing = False
        for a in after.activities:
            if a.name == game_name:
                # Перевіряємо деталі для врахування лише часу в матчі
                if hasattr(a, 'details') and a.details:
                    details = a.details.lower()
                    # Зазвичай PUBG пише "Playing a match", "In Match" або "У матчі"
                    if any(word in details for word in ["match", "матч", "playing", "грає"]):
                        is_playing = True
                        break
                else:
                    # Якщо деталей немає (напр. вимкнено в налаштуваннях), рахуємо просто за назвою гри
                    is_playing = True
                    break

        was_playing = False
        if before:
            for a in before.activities:
                if a.name == game_name:
                    if hasattr(a, 'details') and a.details:
                        details = a.details.lower()
                        if any(word in details for word in ["match", "матч", "playing", "грає"]):
                            was_playing = True
                            break
                    else:
                        was_playing = True
                        break
        
        record = find_record(user_data, user_id, guild_id)
        if record and record.get("untracked"): return
        
        now = int(time.time() * 1000)
        
        if has_clan:
            if not record:
                user_data[key] = {"username": str(after), "userId": user_id, "guildId": guild_id}
                record = user_data[key]
            if is_playing or was_playing:
                record["lastPubgSeen"] = now
                await save_data()
                
        if not record or not record.get("isActive") or not has_adapt or record.get("isPaused"): return
        
        if not was_playing and is_playing:
            if not record.get("lastSessionStart"):
                record["lastSessionStart"] = now
                create_log(f"[GAME START] {record.get('username')}")
                await save_data()
                
        if was_playing and not is_playing and record.get("lastSessionStart"):
            duration = now - record["lastSessionStart"]
            record["totalPlayTime"] = record.get("totalPlayTime", 0) + duration
            record["lastSessionStart"] = None
            create_log(f"[GAME END] {record.get('username')} +{ms_to_readable(duration)}")
            await save_data()
            await check_user(after, user_id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        user_id = str(member.id)
        now = int(time.time() * 1000)
        
        if not before.channel and after.channel:
            voice_sessions[user_id] = now
            try:
                conn = sqlite3.connect(DB_FILE)
                conn.execute(
                    "INSERT INTO voice_stats (userId, totalTime, lastJoin) VALUES (?, 0, ?) ON CONFLICT(userId) DO UPDATE SET lastJoin = ?",
                    (user_id, now, now)
                )
                conn.commit()
                conn.close()
            except: pass
        elif before.channel and not after.channel:
            joined_at = voice_sessions.pop(user_id, None)
            if joined_at:
                duration = now - joined_at
                try:
                    conn = sqlite3.connect(DB_FILE)
                    conn.execute("UPDATE voice_stats SET totalTime = totalTime + ? WHERE userId = ?", (duration, user_id))
                    conn.commit()
                    conn.close()
                except: pass
                if duration > 3600000:
                    create_log(f"[VOICE] {member.name} spent {(duration/3600000):.1f}h in voice.")

async def setup(bot):
    await bot.add_cog(EventsCog(bot))
    print("Loaded extension: events")
