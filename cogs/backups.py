import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import datetime

from utils.helpers import create_log

DB_FILE = os.path.join(os.path.dirname(__file__), '../database.sqlite')
CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
OWNER_ID = 776154533742641174

class BackupsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.backup_loop.start()

    def cog_unload(self):
        self.backup_loop.cancel()

    @tasks.loop(hours=1) # Перевіряємо щогодини
    async def backup_loop(self):
        from utils.data_handler import get_settings, save_settings
        settings = get_settings()
        last_backup_str = settings.get("lastBackupDate", "")
        today = datetime.datetime.now()
        
        # Перевірка: чи пройшло 3 дні з останнього бекапу
        if last_backup_str:
            try:
                last_date = datetime.datetime.strptime(last_backup_str, "%Y-%m-%d")
                if (today - last_date).days < 3:
                    return # Ще не пройшло 3 дні
            except ValueError:
                pass
                
        # Робимо бекап
        await self.send_backup()
        
        # Зберігаємо дату
        settings["lastBackupDate"] = today.strftime("%Y-%m-%d")
        await save_settings()

    @backup_loop.before_loop
    async def before_backup(self):
        await self.bot.wait_until_ready()

    async def send_backup(self):
        user = await self.bot.fetch_user(OWNER_ID)
        if not user:
            return

        files = []
        if os.path.exists(DB_FILE):
            files.append(discord.File(DB_FILE, filename=f"database_backup_{datetime.datetime.now().strftime('%Y%m%d')}.sqlite"))
        if os.path.exists(CONFIG_FILE):
            files.append(discord.File(CONFIG_FILE, filename=f"config_backup_{datetime.datetime.now().strftime('%Y%m%d')}.json"))

        if not files:
            await user.send("⚠️ Помилка бекапу: Файли не знайдено.")
            return

        embed = discord.Embed(
            title="💾 Автоматичний Бекап Системи",
            description="Ось ваші останні файли бази даних та конфігурації.",
            color=0x2ECC71,
            timestamp=datetime.datetime.now()
        )

        try:
            await user.send(embed=embed, files=files)
            create_log("[BACKUP] Резервні копії надіслано власнику.")
        except Exception as e:
            create_log(f"[BACKUP ERROR] Failed to send backup: {e}")

    @app_commands.command(name="test_backup", description="[Адмін] Зробити та надіслати бекап негайно")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_backup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.send_backup()
        await interaction.followup.send("✅ Бекап надіслано вам в особисті повідомлення!")

async def setup(bot):
    await bot.add_cog(BackupsCog(bot))
    print("Loaded extension: backups")
