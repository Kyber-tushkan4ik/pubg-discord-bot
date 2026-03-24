import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
from dotenv import load_dotenv
from utils.core import perform_startup_scan
from utils.scheduler import init_scheduler

# Завантажуємо .env з поточної або батьківської папки
if os.path.exists('.env'):
    load_dotenv('.env')
else:
    load_dotenv('../.env')

TOKEN = os.getenv("DISCORD_TOKEN")

class PubgBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True
        intents.voice_states = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )

    async def global_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ У вас немає прав для використання цієї команди.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ У вас немає прав для використання цієї команди.", ephemeral=True)
            except Exception:
                pass
        else:
            cmd_name = interaction.command.name if interaction.command else 'Unknown'
            print(f"[ПОМИЛКА КОМАНДИ] {cmd_name}: {error}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Сталася помилка при виконанні команди.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Сталася помилка при виконанні команди.", ephemeral=True)
            except Exception:
                pass

    async def setup_hook(self):
        self.tree.on_error = self.global_app_command_error
        # Тут будемо завантажувати cogs
        cogs_dir = os.path.join(os.path.dirname(__file__), 'cogs')
        if not os.path.exists(cogs_dir):
            os.makedirs(cogs_dir)
            
        for filename in os.listdir(cogs_dir):
            if filename.endswith('.py') and not filename.startswith('__'):
                await self.load_extension(f'cogs.{filename[:-3]}')
                print(f'Завантажено розширення: {filename}')

bot = PubgBot()

@bot.event
async def on_ready():
    print(f'[СИСТЕМА] Бот {bot.user} підключився до Discord!')
    # Реєструємо слеш-команди глобально
    try:
        synced = await bot.tree.sync()
        print(f'[СИСТЕМА] Синхронізовано {len(synced)} команд(и)')
    except Exception as e:
        print(f'[ПОМИЛКА] Не вдалося синхронізувати команди: {e}')
    
    # Ініціалізація планувальника та сканування
    init_scheduler(bot)
    await perform_startup_scan(bot)

if __name__ == '__main__':
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("[ПОМИЛКА] Токен не знайдено. Переконайтеся, що файл .env існує.")
