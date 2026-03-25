import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import random
import time
import asyncio

from utils.data_handler import get_data, save_data
from utils.core import handle_success, send_log
from utils.helpers import is_admin

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

CLAN_FACTS = [
    "Наш клан був заснований у 2021 році групою справжніх фанатів PUBG.",
    "Найбільша кількість перемог за один вечір у нас — 12 поспіль!",
    "Наш засновник колись виграв матч, маючи в руках лише сковорідку.",
    "У нас є гравці з понад 5000 годинами в ігрі.",
    "Ми регулярно проводимо внутрішні турніри з призами."
]

ROLES = {
    "🎯 Снайпер": "Любитель дальніх пострілів та точності.",
    "🔥 Штурмовик": "Завжди на передовій, перший входить у будівлі.",
    "🚑 Медик": "Рятує команду у найскладніших ситуаціях.",
    "🚗 Водій": "Король доріг, знає кожен поворот на Ерангелі."
}

class ClanIntroCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.intro_sessions = {} # user_id -> state

    @app_commands.command(name="intro_setup", description="Встановити панель ознайомлення (Адмін)")
    @is_admin()
    async def intro_setup(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="👋 Ласкаво просимо до нашого клану!",
            description="Щоб стати повноправним учасником та отримати доступ до всіх каналів, пройдіть невелике ознайомлення.\n\nНатисніть кнопку нижче, щоб почати!",
            color=0xFFD700
        )
        embed.set_image(url="https://i.imgur.com/qg9b9dE.png") # Замініть на реальне фото клану
        
        view = StartIntroView(self)
        await interaction.response.send_message("Панель встановлена.", ephemeral=True)
        await interaction.channel.send(embed=embed, view=view)

    async def finish_intro(self, member: discord.Member):
        await handle_success(member)

class StartIntroView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🚀 Почати ознайомлення", style=discord.ButtonStyle.success, custom_id="start_intro")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        self.cog.intro_sessions[user_id] = {"step": 1, "answers": [], "role": None, "voice_done": False, "cmd_done": False}
        await self.send_step(interaction, 1)

    async def send_step(self, interaction: discord.Interaction, step: int):
        user_id = interaction.user.id
        session = self.cog.intro_sessions[user_id]
        
        progress = (step / 5) * 100
        progress_bar = "▓" * (step * 2) + "░" * ((5 - step) * 2)
        
        fact = random.choice(CLAN_FACTS)
        
        embed = discord.Embed(color=0x3498db)
        embed.set_footer(text=f"Прогрес: {progress_bar} {progress:.0f}%")
        
        if step == 1:
            embed.title = "📜 Крок 1: Наша Місія та Правила"
            embed.description = (
                "Ми — спільнота гравців, які цінують взаємодопомогу та адекватне спілкування.\n\n"
                "**Основні правила:**\n"
                "1. Поважай тіммейтів.\n"
                "2. Не використовуй чити.\n"
                "3. Слухай капітана під час матчу.\n\n"
                f"*Цікавий факт: {fact}*"
            )
            view = QuizView(self.cog, step)
        elif step == 2:
            embed.title = "❓ Крок 2: Невеличка вікторина"
            embed.description = "Дайте відповідь на запитання, щоб ми знали, що ви прочитали правила.\n\n**Запитання:** Що заборонено використовувати в нашому клані?"
            view = QuizView(self.cog, step)
        elif step == 3:
            embed.title = "🎭 Крок 3: Ваша роль у грі"
            embed.description = "Виберіть свою спеціалізацію. Це допоможе іншим швидше знаходити напарників."
            view = RoleView(self.cog, step)
        elif step == 4:
            embed.title = "🔊 Крок 4: Голосовий та Командний зв'язок"
            embed.description = (
                "Ми цінуємо активне спілкування.\n\n"
                "**Завдання:**\n"
                "1. Спробуйте використати команду `/p_stats` у будь-якому текстовому каналі (публічно або тут).\n"
                "2. Зайдіть у будь-який голосовий канал хоча б на 1 хвилину.\n\n"
                "Коли виконаєте, натисніть кнопку перевірки."
            )
            view = CheckTaskView(self.cog, step)
        elif step == 5:
            embed.title = "🎉 Фінал: Вітаємо у клані!"
            embed.description = (
                "Ви пройшли всі етапи ознайомлення!\n\n"
                "Натисніть кнопку нижче, щоб отримати роль повноправного учасника та почати грати з нами."
            )
            view = FinalView(self.cog, step)

        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class QuizView(discord.ui.View):
    def __init__(self, cog, step):
        super().__init__(timeout=120)
        self.cog = cog
        self.step = step
        if step == 2:
            self.add_item(discord.ui.Button(label="Чити", style=discord.ButtonStyle.danger, custom_id="ans_wrong"))
            self.add_item(discord.ui.Button(label="Мікрофон", style=discord.ButtonStyle.secondary, custom_id="ans_wrong2"))
            self.add_item(discord.ui.Button(label="Заборонене ПЗ", style=discord.ButtonStyle.success, custom_id="ans_correct"))

    @discord.ui.button(label="Наступний крок", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.step == 1:
            await StartIntroView(self.cog).send_step(interaction, 2)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.data.get("custom_id") == "ans_correct":
            await interaction.response.send_message("✅ Правильно!", ephemeral=True)
            await StartIntroView(self.cog).send_step(interaction, 3)
            return False
        elif interaction.data.get("custom_id") == "ans_wrong" or interaction.data.get("custom_id") == "ans_wrong2":
            await interaction.response.send_message("❌ Спробуйте ще раз! Згадайте правила про чити та ПЗ.", ephemeral=True)
            return False
        return True

class RoleView(discord.ui.View):
    def __init__(self, cog, step):
        super().__init__(timeout=120)
        self.cog = cog
        for role_name in ROLES:
            btn = discord.ui.Button(label=role_name, style=discord.ButtonStyle.secondary)
            btn.callback = self.make_callback(role_name)
            self.add_item(btn)

    def make_callback(self, role_name):
        async def callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            self.cog.intro_sessions[user_id]["role"] = role_name
            # Тут можна було б реально видавати роль у Discord, якщо вона існує
            await interaction.response.send_message(f"✅ Ви обрали роль: {role_name}", ephemeral=True)
            await StartIntroView(self.cog).send_step(interaction, 4)
        return callback

class CheckTaskView(discord.ui.View):
    def __init__(self, cog, step):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="🔄 Перевірити виконання", style=discord.ButtonStyle.primary)
    async def check(self, interaction: discord.Interaction, button: discord.ui.Button):
        # В реальності тут була б складна логіка перевірки через базу або кеш
        # Для демонстрації ми просто "віримо" користувачу або даємо заглушку
        # Можна додати перевірку voice_state прямо тут:
        member = interaction.guild.get_member(interaction.user.id)
        is_in_voice = member.voice is not None
        
        if is_in_voice:
            await interaction.response.send_message("✅ Голосовий зв'язок перевірено! Команди теж (заглушка).", ephemeral=True)
            await StartIntroView(self.cog).send_step(interaction, 5)
        else:
            await interaction.response.send_message("❌ Зайдіть, будь ласка, у будь-який голосовий канал сервера.", ephemeral=True)

class FinalView(discord.ui.View):
    def __init__(self, cog, step):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="✅ Завершити та приєднатися", style=discord.ButtonStyle.success)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.finish_intro(interaction.user)
        await interaction.response.edit_message(content="🎉 Вітаємо! Ви тепер повноправний учасник клану. Канали відкрито!", embed=None, view=None)

async def setup(bot):
    await bot.add_cog(ClanIntroCog(bot))
    print("Loaded extension: clan_intro")
