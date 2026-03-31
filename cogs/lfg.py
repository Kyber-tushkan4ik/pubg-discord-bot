import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import time
from utils.data_handler import get_data, get_settings, get_frequent_playmates

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

class InvitationView(discord.ui.View):
    def __init__(self, initiator_name, initiator_id, channel_id, bot):
        super().__init__(timeout=3600) # 1 hour timeout
        self.initiator_name = initiator_name
        self.initiator_id = initiator_id
        self.channel_id = channel_id
        self.bot = bot

    async def send_response(self, interaction: discord.Interaction, text: str):
        # Оновити DM отримувача
        await interaction.response.edit_message(content=f"✅ Ви відправили відповідь: **{text}**", view=None)
        
        # Визначення комічного тексту сповіщення (Варіант 5)
        responses = {
            "Так / Го!": f"🚀 **{interaction.user.name}** уже летить до вас зі швидкістю айрдропу! Го!",
            "Ні / Пізніше": f"🚫 **{interaction.user.name}** каже, що у нього лапки. Сьогодні він пасує.",
            "В мене фулл паті": f"🙅‍♂️ **{interaction.user.name}** уже в \"гаремі\"! Його сквад забитий під зав'язку.",
            "Я ласт катку": f"☠️ **{interaction.user.name}** уже однією ногою в лобі. Остання спроба — і все!"
        }
        
        notify_text = responses.get(text, f"🔔 **{interaction.user.name}** відповів: **{text}**")
        
        # Сповістити ініціатора в ОСОБИСТІ повідомлення
        initiator = self.bot.get_user(int(self.initiator_id))
        if initiator:
            try:
                await initiator.send(notify_text)
            except:
                pass

    @discord.ui.button(label="Так / Го!", style=discord.ButtonStyle.success, custom_id="lfg_yes")
    async def invite_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_response(interaction, "Так / Го!")

    @discord.ui.button(label="Ні / Пізніше", style=discord.ButtonStyle.danger, custom_id="lfg_no")
    async def invite_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_response(interaction, "Ні / Пізніше")

    @discord.ui.button(label="В мене фулл паті", style=discord.ButtonStyle.secondary, custom_id="lfg_full")
    async def invite_full(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_response(interaction, "В мене фулл паті")

    @discord.ui.button(label="Я ласт катку", style=discord.ButtonStyle.secondary, custom_id="lfg_last")
    async def invite_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_response(interaction, "Я ласт катку")

class LfgPanel(discord.ui.View):
    def __init__(self, initiator: discord.Member, bot, players_playing, players_online):
        super().__init__(timeout=600)
        self.initiator = initiator
        self.bot = bot
        self.players_playing = players_playing
        self.players_online = players_online
        
        # Populate select menu if there are players
        all_eligible = players_playing + players_online
        if all_eligible:
            options = []
            for p in all_eligible[:25]: # Max 25 in select menu
                status_emoji = "🎮" if p in players_playing else "🟢"
                options.append(discord.SelectOption(
                    label=p.name,
                    value=str(p.id),
                    description="Грає в PUBG" if p in players_playing else "В мережі",
                    emoji=status_emoji
                ))
            
            self.select_menu = discord.ui.Select(
                placeholder="Виберіть гравців для запрошення...",
                min_values=1,
                max_values=min(len(options), 10),
                options=options,
                custom_id="lfg_select"
            )
            self.select_menu.callback = self.select_callback
            self.add_item(self.select_menu)

    async def send_invitation(self, target: discord.Member, channel):
        try:
            view = InvitationView(self.initiator.name, self.initiator.id, channel.id, self.bot)
            embed = discord.Embed(
                title="🎮 Запрошення до гри",
                description=f"**{self.initiator.name}** запрошує вас пограти в PUBG разом!",
                color=0xFF9900
            )
            if self.initiator.avatar: embed.set_thumbnail(url=self.initiator.avatar.url)
            await target.send(embed=embed, view=view)
            return True
        except:
            return False

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.initiator.id:
            return await interaction.response.send_message("❌ Тільки ініціатор може використовувати це меню.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        invited_count = 0
        for user_id in self.select_menu.values:
            target = interaction.guild.get_member(int(user_id))
            if target:
                success = await self.send_invitation(target, interaction.channel)
                if success: invited_count += 1
                
        await interaction.followup.send(f"✅ Надіслано запрошення {invited_count} гравцям.", ephemeral=True)

    @discord.ui.button(label="Запросити всіх у PUBG", style=discord.ButtonStyle.primary, custom_id="btn_invite_pubg")
    async def invite_all_pubg(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.initiator.id:
            return await interaction.response.send_message("❌ Тільки ініціатор може використовувати цю кнопку.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        invited_count = 0
        for target in self.players_playing:
            success = await self.send_invitation(target, interaction.channel)
            if success: invited_count += 1
            
        await interaction.followup.send(f"✅ Надіслано запрошення {invited_count} гравцям, що грають в PUBG.", ephemeral=True)

    @discord.ui.button(label="Запросити всіх онлайн", style=discord.ButtonStyle.secondary, custom_id="btn_invite_online")
    async def invite_all_online(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.initiator.id:
            return await interaction.response.send_message("❌ Тільки ініціатор може використовувати цю кнопку.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        invited_count = 0
        for target in self.players_online:
            success = await self.send_invitation(target, interaction.channel)
            if success: invited_count += 1
            
        await interaction.followup.send(f"✅ Надіслано запрошення {invited_count} гравцям онлайн.", ephemeral=True)

class LfgCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="invite", description="Відкрити панель пошуку напарників")
    async def invite(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
        game_name = CONFIG.get("GAME_NAME", "PUBG: BATTLEGROUNDS")
        
        # Get playmates for sorting
        playmates = get_frequent_playmates(interaction.user.id)
        
        playing_pubg = []
        online_others = []
        
        for m in guild.members:
            if m.bot or m.status == discord.Status.offline or m.id == interaction.user.id:
                continue
                
            is_playing = any(act.name == game_name for act in m.activities)
            if is_playing:
                playing_pubg.append(m)
            else:
                online_others.append(m)
                
        # Sort each list by frequency
        def sort_key(member):
            try: return playmates.index(str(member.id))
            except: return 999999
            
        playing_pubg.sort(key=sort_key)
        online_others.sort(key=sort_key)
        
        embed = discord.Embed(
            title="🔍 Пошук напарників",
            description=f"Ініціатор: {interaction.user.mention}\n\n"
                        f"**Пріоритет 1: Грають в PUBG ({len(playing_pubg)})**\n"
                        f"**Пріоритет 2: В мережі ({len(online_others)})**\n\n"
                        "*Часті напарники відображаються першими у списках.*",
            color=0x3498DB
        )
        
        if playing_pubg:
            names = [m.name for m in playing_pubg[:10]]
            embed.add_field(name="🎮 Зараз у грі", value="\n".join(names), inline=True)
            
        if online_others:
            names = [m.name for m in online_others[:10]]
            embed.add_field(name="🟢 Онлайн", value="\n".join(names), inline=True)
            
        view = LfgPanel(interaction.user, self.bot, playing_pubg, online_others)
        await interaction.followup.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(LfgCog(bot))
    print("Loaded extension: lfg")
