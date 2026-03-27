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


ROLES = {
    "🎯 Снайпер": "Любитель дальніх пострілів та точності.",
    "🔥 Берсерк": "Завжди на передовій, перший входить у будівлі.",
    "🚑 Санітар": "Рятує команду у найскладніших ситуаціях.",
    "🚗 Перевізник": "Король доріг, знає кожен поворот на Ерангелі."
}

QUIZ_POOL = [
    {
        "q": "Якою мовою потрібно спілкуватися в загальних чатах?",
        "correct": "Українською",
        "wrong": ["Будь-якою", "Англійською"]
    },
    {
        "q": "Куди дозволено (тихенько) кидати фото котів?",
        "correct": "🎴скриншоти-відео",
        "wrong": ["Куди завгодно", "Заборонено"]
    },
    {
        "q": "Що потрібно додати до свого нікнейму?",
        "correct": "Нік з PUBG",
        "wrong": ["Номер телефону", "Прізвище"]
    },
    {
        "q": "Чи можна рекламувати інші сервери в DM або чатах?",
        "correct": "Заборонено",
        "wrong": ["Тільки в DM", "Так, можна"]
    },
    {
        "q": "Які теми обговорень заборонені?",
        "correct": "Політика та релігія",
        "wrong": ["Прогноз погоди", "Стратегії в PUBG"]
    },
    {
        "q": "Що робити, якщо хочете стрімити з LFG-лобі?",
        "correct": "Питати дозволу у всіх",
        "wrong": ["Просто стрімити", "Питати тільки адміна"]
    }
]

class ClanIntroCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.intro_sessions = {} # user_id -> state
        self.auto_invite_task = self.bot.loop.create_task(self.auto_invite_loop())

    async def auto_invite_loop(self):
        """Фонова задача для автоматичного запрошення людей з роллю Адаптація."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                user_data = get_data()
                role_name = CONFIG.get("ROLE_ADAPT")
                
                for guild in self.bot.guilds:
                    role = discord.utils.get(guild.roles, name=role_name)
                    if not role: continue
                    
                    for member in role.members:
                        if member.bot: continue
                        user_id = str(member.id)
                        guild_id = str(guild.id)
                        key = f"{user_id}_{guild_id}"
                        
                        record = user_data.get(key) or user_data.get(user_id)
                        # Якщо людини немає в БД або вона ще не проходила ознайомлення
                        if not record or (not record.get("intro_started") and not record.get("intro_done")):
                            await self.send_intro_dm(member)
                            if not record:
                                user_data[key] = {"username": str(member), "userId": user_id, "guildId": guild_id}
                                record = user_data[key]
                            record["intro_started"] = True
                            await save_data()
                            await asyncio.sleep(2) # Затримка проти спаму
                            
            except Exception as e:
                print(f"Error in auto_invite_loop: {e}")
            
            await asyncio.sleep(3600) # Перевірка раз на годину

    async def send_intro_dm(self, member: discord.Member):
        embed = discord.Embed(
            title="👋 Помітили, що ти ще не пройшов ознайомлення",
            description=f"Привіт, {member.mention}! У тебе є роль **Адаптація**, але ти ще не скористався нашою новою системою ознайомлення.\n\nБудь ласка, натисни кнопку нижче, щоб швидко пройти квест та отримати повний доступ!",
            color=0x3498db
        )
        view = StartIntroView(self)
        try:
            await member.send(embed=embed, view=view)
        except:
            pass

    @app_commands.command(name="intro_setup", description="Встановити панель ознайомлення (Адмін)")
    @is_admin()
    async def intro_setup(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="👋 Ласкаво просимо до нашого клану!",
            description="Щоб стати повноправним учасником та отримати доступ до всіх каналів, пройдіть невелике ознайомлення.\n\nНатисніть кнопку нижче, щоб почати!",
            color=0xFFD700
        )
        # Оновлюємо зображення на локальне для стабільності
        img_path = os.path.join(os.path.dirname(__file__), '../assets/clan_welcome.png')
        file = None
        if os.path.exists(img_path):
            file = discord.File(img_path, filename="clan_welcome.png")
            embed.set_image(url="attachment://clan_welcome.png")
        
        view = StartIntroView(self)
        await interaction.response.send_message("Панель встановлена.", ephemeral=True)
        if file:
            await interaction.channel.send(embed=embed, view=view, file=file)
        else:
            await interaction.channel.send(embed=embed, view=view)

    @app_commands.command(name="send_intro", description="Надіслати запрошення до ознайомлення учаснику (Адмін)")
    @app_commands.describe(member="Учасник, якому надіслати запрошення")
    @is_admin()
    async def send_intro(self, interaction: discord.Interaction, member: discord.Member):
        embed = discord.Embed(
            title="👋 Привіт! Запрошуємо до ознайомлення",
            description=f"{member.mention}, адміністрація просить тебе пройти невелике ознайомлення з нашим кланом, щоб отримати повний доступ до всіх каналів.\n\nНатисніть кнопку нижче, щоб почати!",
            color=0xFFD700
        )
        view = StartIntroView(self)
        try:
            await member.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Запрошення успішно надіслано учаснику {member.mention} в особисті повідомлення.", ephemeral=True)
            await send_log(self.bot, f"🔔 Адмін {interaction.user.mention} надіслав персональне запрошення до ознайомлення для {member.mention}")
        except Exception:
            await interaction.response.send_message(f"❌ Не вдалося надіслати повідомлення {member.mention}. Можливо, у нього закриті приватні повідомлення.", ephemeral=True)

    async def finish_intro(self, member: discord.Member):
        await handle_success(member)

class StartIntroView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🚀 Почати ознайомлення", style=discord.ButtonStyle.success, custom_id="start_intro")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        # Обираємо 2 випадкових питання з пулу
        random_questions = random.sample(QUIZ_POOL, 2)
        self.cog.intro_sessions[user_id] = {
            "step": 1, 
            "questions": random_questions,
            "answers": [], 
            "role": None, 
            "voice_done": False, 
            "cmd_done": False
        }
        await self.send_step(interaction, 1)

    async def send_step(self, interaction: discord.Interaction, step: int):
        user_id = interaction.user.id
        session = self.cog.intro_sessions[user_id]
        
        progress = (step / 5) * 100
        # Коригуємо візуальний прогрес для 2.5 (друге питання)
        display_step = step if step <= 5 else 2.5
        progress_bar = "▓" * int(display_step * 2) + "░" * int((5 - display_step) * 2)
        
        embed = discord.Embed(color=0x3498db)
        embed.set_footer(text=f"Прогрес: {progress_bar} {min(100, progress):.0f}%")
        
        if step == 1:
            embed.title = "📜 Крок 1: Правила нашого сервера"
            rules_text = (
                "1. **Нікнейм:** Змініть ім'я або додайте ігровий нік з PUBG у дужках.\n"
                "2. **Ввічливість:** Будьте ввічливі та дружні до всіх.\n"
                "3. **Конфлікти:** Жодних політики, релігії чи конфліктних дискусій.\n"
                "4. **Повага:** Ніякої мови ненависті чи дискримінації.\n"
                "5. **Реклама:** Заборонена реклама інших серверів/сайтів (чат та DM).\n"
                "6. **Спам:** Заборонено спам та надмірний оффтоп.\n"
                "7. **Лайка:** Ніякої надмірної лайки (публічний сервер).\n"
                "8. **Фейки:** Не видавайте себе за інших членів або розробників.\n"
                "9. **Мова:** Загальні канали — тільки **Українською мовою**.\n"
                "10. **Піратство:** Не обговорюйте піратство та реселерів ключів.\n"
                "11. **Чити:** Заборонено продаж читів/хаків.\n"
                "12. **Попрошайництво:** Не просіть купити або подарувати гру.\n"
                "13. **Стріми:** Питайте дозволу перед записом відео в LFG-лобі.\n"
                "14. **Боти:** Не спамте ботами у невідведених чатах.\n"
                "15. **Медіа:** Відео та скріншоти — у відповідні чати.\n"
                "16. **Коти:** Дозволено (тихенько) кидати фото котів у 🎴скриншоти чи 📸фото.\n\n"
                "Прочитали? Натисніть кнопку нижче!"
            )
            embed.description = rules_text
            view = QuizView(self.cog, step)
        elif step == 2:
            q_data = session["questions"][0]
            embed.title = "❓ Крок 2: Перевірка знань (1/2)"
            embed.description = f"**Запитання:** {q_data['q']}"
            view = QuizView(self.cog, step, q_data)
        elif step == 25:
            q_data = session["questions"][1]
            embed.title = "❓ Крок 2: Перевірка знань (2/2)"
            embed.description = f"**Запитання:** {q_data['q']}"
            view = QuizView(self.cog, 25, q_data)
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
    def __init__(self, cog, step, q_data=None):
        super().__init__(timeout=120)
        self.cog = cog
        self.step = step
        
        if step in [2, 25] and q_data:
            options = [
                {"label": q_data["correct"], "style": discord.ButtonStyle.success, "cid": f"correct_{step}"}
            ]
            for i, w in enumerate(q_data["wrong"]):
                options.append({"label": w, "style": discord.ButtonStyle.secondary, "cid": f"wrong_{step}_{i}"})
            
            # Рандомізуємо порядок кнопок
            random.shuffle(options)
            
            for opt in options:
                self.add_item(discord.ui.Button(label=opt["label"], style=opt["style"], custom_id=opt["cid"]))

    @discord.ui.button(label="Наступний крок", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.step == 1:
            await StartIntroView(self.cog).send_step(interaction, 2)

    async def interaction_check(self, interaction: discord.Interaction):
        cid = interaction.data.get("custom_id")
        if cid == "correct_2":
            await interaction.response.send_message("✅ Правильно!", ephemeral=True)
            await StartIntroView(self.cog).send_step(interaction, 25)
            return False
        elif cid == "correct_25":
            await interaction.response.send_message("✅ Правильно! Останній ривок.", ephemeral=True)
            await StartIntroView(self.cog).send_step(interaction, 3)
            return False
        elif "wrong" in cid:
            await interaction.response.send_message("❌ Неправильно! Будь ласка, перечитайте правила ще раз.", ephemeral=True)
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
            
            guild = interaction.guild
            member = interaction.user
            
            # Очищуємо саму назву ролі від емодзі для пошуку/створення
            clean_name = role_name.split(" ", 1)[-1] if " " in role_name else role_name
            
            await interaction.response.defer(ephemeral=True)
            
            try:
                # Шукаємо існуючу роль
                target_role = discord.utils.get(guild.roles, name=clean_name)
                
                if not target_role:
                    # Створюємо роль, якщо її немає
                    target_role = await guild.create_role(name=clean_name, color=discord.Color.blue(), mentionable=True)
                    await send_log(self.cog.bot, f"🆕 Створено нову ігрову роль: `{clean_name}`")
                
                # Видаємо роль
                await member.add_roles(target_role)
                await interaction.followup.send(f"✅ Вам видано роль: **{role_name}**", ephemeral=True)
                await StartIntroView(self.cog).send_step(interaction, 4)
                
            except Exception as e:
                print(f"Error giving role: {e}")
                await interaction.followup.send(f"❌ Не вдалося видати роль. Перевірте мої права (Manage Roles).", ephemeral=True)
                
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
