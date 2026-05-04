import discord
from discord.ext import commands
from discord import app_commands
import os
import shutil
from utils.helpers import create_log, cleanup_old_assets, is_admin

class Maintenance(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="maintenance", description="Обслуговування бота та перевірка ресурсів")
    @app_commands.describe(action="Дія: status (статус), cleanup (очищення), test_error (тест помилок)")
    @is_admin()
    async def maintenance(self, interaction: discord.Interaction, action: str):
        if action == "status":
            await interaction.response.defer()
            
            # Перевірка розміру логів
            log_file = os.path.join(os.path.dirname(__file__), '../logs.txt')
            log_size = os.path.getsize(log_file) / (1024 * 1024) if os.path.exists(log_file) else 0
            
            # Перевірка розміру бази даних
            db_file = os.path.join(os.path.dirname(__file__), '../database.sqlite')
            db_size = os.path.getsize(db_file) / (1024 * 1024) if os.path.exists(db_file) else 0
            
            # Перевірка папки assets
            assets_dir = os.path.join(os.path.dirname(__file__), '../assets')
            assets_count = 0
            assets_size = 0
            if os.path.exists(assets_dir):
                for f in os.listdir(assets_dir):
                    fp = os.path.join(assets_dir, f)
                    if os.path.isfile(fp):
                        assets_count += 1
                        assets_size += os.path.getsize(fp)
            
            assets_size_mb = assets_size / (1024 * 1024)
            
            # Вільне місце на диску
            total, used, free = shutil.disk_usage("/")
            free_gb = free / (1024**3)
            
            embed = discord.Embed(
                title="🛠️ Статус системи",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="📁 Логи", value=f"{log_size:.2f} MB", inline=True)
            embed.add_field(name="🗄️ База даних", value=f"{db_size:.2f} MB", inline=True)
            embed.add_field(name="🖼️ Assets", value=f"{assets_count} файлів ({assets_size_mb:.2f} MB)", inline=True)
            embed.add_field(name="💾 Вільне місце", value=f"{free_gb:.2f} GB", inline=False)
            
            status_color = "🟢 OK" if free_gb > 1 else "🟡 Low Space" if free_gb > 0.1 else "🔴 CRITICAL"
            embed.add_field(name="⛽ Стан диска", value=status_color, inline=True)
            
            await interaction.followup.send(embed=embed)
            
        elif action == "cleanup":
            await interaction.response.send_message("🧹 Починаю очищення старих зображень та перевірку логів...", ephemeral=True)
            cleanup_old_assets(max_age_hours=0) # Видалити ВСІ тимчасові victory_*.png
            create_log(f"[ADMIN] {interaction.user} запустив ручне очищення.")
            await interaction.followup.send("✅ Очищення завершено. Тимчасові зображення перемог видалено.")
        elif action == "test_error":
            await interaction.response.send_message("🚨 Симулюю критичну помилку бази даних...", ephemeral=True)
            # Викликаємо глобальний обробник нібито виникла помилка
            import sqlite3
            fake_err = sqlite3.OperationalError("database or disk is full")
            import utils.data_handler as dh
            if dh._error_callback:
                dh._error_callback("Тестовий запит", fake_err)
        else:
            await interaction.response.send_message("❌ Невідома дія. Використовуйте `status`, `cleanup` або `test_error`.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Maintenance(bot))
