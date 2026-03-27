import discord
from discord import app_commands
from discord.ext import commands
import json
import os

from utils.data_handler import get_data, save_data, get_settings, save_settings
from utils.pubg_api import get_player
from utils.helpers import get_record_key, find_record, create_log, ms_to_readable, is_admin, is_admin_check
import time

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Показати список доступних команд")
    async def help_cmd(self, interaction: discord.Interaction):
        is_admin = is_admin_check(interaction)
        
        embed = discord.Embed(
            title='📖 Список команд бота',
            description='Ось список команд, які ви можете використовувати:',
            color=0xF2A900
        )
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)
            
        embed.add_field(
            name='🎮 Загальні команди',
            value="\n".join([
                '**/p_stats [нікинейм]** — Переглянути статистику PUBG',
                '**/link [нікинейм]** — Прив\'язати свій PUBG нікнейм',
                '**/unlink** — Видалити власну прив\'язку профілю',
                '**/adapt_status** — Переглянути свій прогрес адаптації',
                '**/clan_status** — Переглянути статистику клану',
                '**/top_active** — Рейтинг найактивніших',
                '**/help** — Показати це повідомлення'
            ]),
            inline=False
        )
        
        if is_admin:
            embed.add_field(
                name='🛠️ Адміністративні команди',
                value="\n".join([
                    '**/admin_link [користувач] [нік]**',
                    '**/admin_unlink [користувач]**',
                    '**/manage_tracking**',
                    '**/adapt_finish [користувач]**',
                    '**/adapt_cancel [користувач]**',
                    '**/adapt_pause / /adapt_resume**',
                    '**/adapt_add_time / /adapt_remove_time**',
                    '**/adapt_deadline_extend / /reduce**',
                    '**/adapt_archive**',
                    '**/adapt_fix_glitch**'
                ]),
                inline=False
            )
            embed.set_footer(text='Ви бачите цей список, тому що у вас є права адміністратора.')
        else:
            embed.set_footer(text='Бажаємо приємної гри!')
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="link", description="Прив'язати свій PUBG нікнейм")
    @app_commands.describe(nickname="Ваш нікнейм у PUBG")
    async def link(self, interaction: discord.Interaction, nickname: str):
        await interaction.response.defer()
        try:
            player = await get_player(nickname)
            if not player:
                await interaction.followup.send(f"❌ Гравця з нікнеймом **{nickname}** не знайдено в PUBG.", ephemeral=True)
                return
                
            real_name = player.get("attributes", {}).get("name", nickname)
            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild.id)
            key = get_record_key(user_id, guild_id)
            
            user_data = get_data()
            record = find_record(user_data, user_id, guild_id)
            
            if not record:
                user_data[key] = {
                    "username": str(interaction.user)
                }
                record = user_data[key]
                
            record["userId"] = user_id
            record["guildId"] = guild_id
            record["pubgNickname"] = real_name
            await save_data()
            
            embed = discord.Embed(
                title='✅ Профіль прив\'язано',
                description=f"Вас успішно прив'язано до PUBG нікнейму **{real_name}**. Тепер ви можете використовувати `/p_stats` без параметрів.",
                color=0x00FF00
            )
            await interaction.followup.send(embed=embed)
            
            try:
                bot_member = interaction.guild.me
                # Використовуємо app_permissions для слеш-команд, це надійніше
                if not interaction.app_permissions.manage_nicknames:
                    create_log(f"[NICKNAME] Missing 'manage_nicknames' permission in {interaction.guild.name} (app_permissions)")
                elif interaction.user.id == interaction.guild.owner_id:
                    create_log(f"[NICKNAME] Cannot change nickname for guild owner: {interaction.user}")
                    await interaction.followup.send("⚠️ Я не можу змінити ваш нікнейм, оскільки ви є власником сервера.", ephemeral=True)
                elif bot_member.top_role <= interaction.user.top_role:
                    create_log(f"[NICKNAME] Role hierarchy issue: {bot_member.top_role} <= {interaction.user.top_role}")
                    await interaction.followup.send("⚠️ Моя роль нижча або така сама, як ваша, тому я не можу змінити ваш нікнейм.", ephemeral=True)
                else:
                    await interaction.user.edit(nick=real_name)
                    create_log(f"[NICKNAME] Changed for {interaction.user} to {real_name}")
            except Exception as e:
                create_log(f"[NICKNAME] Помилка: {e}")
                
        except Exception as e:
            await interaction.followup.send("Сталася помилка. Перевірте API ключ.", ephemeral=True)

    @app_commands.command(name="unlink", description="Видалити свою прив'язку PUBG нікнейму")
    async def unlink(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild.id)
        user_data = get_data()
        record = find_record(user_data, user_id, guild_id)
        
        if not record or not record.get("pubgNickname"):
            await interaction.response.send_message("❌ У вас немає прив'язаного PUBG нікнейму.", ephemeral=True)
            return
            
        old_nick = record["pubgNickname"]
        del record["pubgNickname"]
        await save_data()
        
        embed = discord.Embed(
            title='✅ Прив\'язку видалено',
            description=f"Ваш профіль успішно відв'язано від нікнейму **{old_nick}**.",
            color=0xFF0000
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="balance", description="Розподілити гравців у голосовому каналі на дві рівні команди за K/D")
    async def balance(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Ви повинні бути у голосовому каналі.", ephemeral=True)
            return
            
        channel = interaction.user.voice.channel
        members = channel.members
        if len(members) < 2:
            await interaction.response.send_message("❌ В каналі занадто мало людей для балансу.", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        user_data = get_data()
        players = []
        for m in members:
            record = find_record(user_data, str(m.id), str(interaction.guild.id))
            kd = float(record.get("kd", 0.5)) if record and record.get("kd") else 0.5
            name = record.get("pubgNickname") if record and record.get("pubgNickname") else m.display_name
            players.append({"name": name, "kd": kd})
            
        players.sort(key=lambda x: x["kd"], reverse=True)
        
        team_a, team_b = [], []
        score_a, score_b = 0, 0
        
        for p in players:
            if score_a <= score_b:
                team_a.append(p)
                score_a += p["kd"]
            else:
                team_b.append(p)
                score_b += p["kd"]
                
        avg_a = score_a / len(team_a) if team_a else 0
        avg_b = score_b / len(team_b) if team_b else 0
        
        embed = discord.Embed(title=f'⚖️ Баланс команд ({channel.name})', color=0x3498db)
        embed.add_field(
            name=f'🔵 Команда A (Avg K/D: {avg_a:.2f})',
            value="\n".join([f"**{p['name']}** ({p['kd']})" for p in team_a]) or "Пусто",
            inline=True
        )
        embed.add_field(
            name=f'🔴 Команда B (Avg K/D: {avg_b:.2f})',
            value="\n".join([f"**{p['name']}** ({p['kd']})" for p in team_b]) or "Пусто",
            inline=True
        )
        embed.set_footer(text=f"Всього гравців: {len(players)}")
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="top_active", description="Топ активних учасників адаптації за прогресом")
    @is_admin()
    async def top_active(self, interaction: discord.Interaction):

        user_data = get_data()
        active_users = []
        now = int(time.time() * 1000)

        for key, record in user_data.items():
            if record.get("guildId") and record.get("guildId") != str(interaction.guild.id):
                continue

            if record.get("isActive"):
                current_total = record.get("totalPlayTime", 0)
                if record.get("lastSessionStart"):
                    current_total += (now - record.get("lastSessionStart"))
                active_users.append({
                    "tag": record.get("username", "Unknown"),
                    "time": current_total,
                    "isPlaying": bool(record.get("lastSessionStart"))
                })

        if not active_users:
            await interaction.response.send_message("Наразі немає активних участників адаптації.", ephemeral=True)
            return

        active_users.sort(key=lambda x: x["time"], reverse=True)
        top10 = active_users[:10]
        
        msg = "**🏆 Топ активних адаптантів:**\n"
        for i, u in enumerate(top10):
            status_icon = "🎮" if u["isPlaying"] else "💤"
            msg += f"{i+1}. **{u['tag']}** — {ms_to_readable(u['time'])} {status_icon}\n"

        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="lfg", description="Створити пошук групи (Looking For Group)")
    @app_commands.describe(mode="Режим гри", time="Час збору (наприклад 20:00)", desc="Додатковий опис", slots="Кількість місць")
    @app_commands.choices(mode=[
        app_commands.Choice(name='Squad', value='Squad'),
        app_commands.Choice(name='Duo', value='Duo'),
        app_commands.Choice(name='Ranked', value='Ranked')
    ])
    async def lfg(self, interaction: discord.Interaction, mode: app_commands.Choice[str], time: str, desc: str = '', slots: int = 4):
        slots = max(2, min(4, slots))
        
        embed = discord.Embed(
            title=f'📢 Шукаю гру: {mode.value}',
            description=f"**Час:** {time}\n**Опис:** {desc}\n\n**Учасники (1/{slots}):**\n1. {interaction.user.mention} (Host)",
            color=0x2ecc71
        )
        embed.set_footer(text=f"Slots: {slots}")
        
        view = LFGView(interaction.user, slots)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="ytm_sync", description="Увімкнути/Вимкнути синхронізацію статусу YouTube Music (Тільки для мене)")
    @app_commands.describe(enabled="Увімкнути (True) або Вимкнути (False)")
    @is_admin()
    async def ytm_sync(self, interaction: discord.Interaction, enabled: bool):
        bot_settings = get_settings()
        
        if enabled:
            bot_settings["ytmSource"] = str(interaction.user.id)
            await save_settings()
            await interaction.response.send_message(f"🎵 Синхронізацію YouTube Music **УВІМКНЕНО** для {interaction.user.display_name}.", ephemeral=True)
            
            ytm_act = next((a for a in interaction.user.activities if a.name in ["YouTube Music", "Spotify"]), None)
            if ytm_act and hasattr(ytm_act, "details") and hasattr(ytm_act, "state"):
                if getattr(ytm_act, "details") and getattr(ytm_act, "state"):
                    await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=f"{ytm_act.details} - {ytm_act.state}"))
        else:
            bot_settings["ytmSource"] = None
            await save_settings()
            await self.bot.change_presence(activity=None)
            await interaction.response.send_message("🔇 Синхронізацію YouTube Music **ВИМКНЕНО**.", ephemeral=True)

class LFGView(discord.ui.View):
    def __init__(self, host: discord.User, slots: int):
        super().__init__(timeout=None)
        self.host = host
        self.slots = slots
        self.participants = [host]

    def update_embed(self, embed: discord.Embed):
        participants_str = "\n".join([f"{i+1}. {p.mention}" + (" (Host)" if p == self.host else "") for i, p in enumerate(self.participants)])
        base_desc = embed.description.split("**Учасники")[0]
        embed.description = f"{base_desc}**Учасники ({len(self.participants)}/{self.slots}):**\n{participants_str}"
        return embed

    @discord.ui.button(label="Приєднатися", style=discord.ButtonStyle.success)
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.participants:
            await interaction.response.send_message("Ви вже в групі!", ephemeral=True)
            return
        if len(self.participants) >= self.slots:
            await interaction.response.send_message("Група вже повна!", ephemeral=True)
            return
            
        self.participants.append(interaction.user)
        embed = interaction.message.embeds[0]
        embed = self.update_embed(embed)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Вийти", style=discord.ButtonStyle.danger)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.participants:
            await interaction.response.send_message("Ви не в групі!", ephemeral=True)
            return
        if interaction.user == self.host:
            await interaction.response.send_message("Хост не може вийти. Видаліть повідомлення, якщо група більше не актуальна.", ephemeral=True)
            return
            
        self.participants.remove(interaction.user)
        embed = interaction.message.embeds[0]
        embed = self.update_embed(embed)
        await interaction.response.edit_message(embed=embed, view=self)

async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
    print("Loaded extension: general")
