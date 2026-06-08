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
    @app_commands.describe(action="Дія")
    @app_commands.choices(action=[
        app_commands.Choice(name="📊 Статус (Сервер, Диск)", value="status"),
        app_commands.Choice(name="📜 Логи (Останні записи)", value="logs"),
        app_commands.Choice(name="🌐 Пінг PUBG API", value="ping_api"),
        app_commands.Choice(name="🔄 Перезавантажити Cogs", value="reload_cogs"),
        app_commands.Choice(name="🧹 Очищення тимчасових файлів", value="cleanup"),
        app_commands.Choice(name="🚨 Тест помилок (Дебаг)", value="test_error")
    ])
    @is_admin()
    async def maintenance(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        act = action.value
        
        if act == "status":
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
            
        elif act == "logs":
            await interaction.response.defer(ephemeral=True)
            log_file = os.path.join(os.path.dirname(__file__), '../logs.txt')
            if not os.path.exists(log_file):
                await interaction.followup.send("❌ Файл логів не знайдено.")
                return
            
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            recent_logs = "".join(lines[-20:]) # Останні 20 рядків
            if len(recent_logs) > 1900:
                recent_logs = recent_logs[-1900:]
                
            embed = discord.Embed(title="📜 Останні логи", description=f"```log\n{recent_logs}\n```", color=0x36393f)
            await interaction.followup.send(embed=embed)
            
        elif act == "ping_api":
            await interaction.response.defer(ephemeral=True)
            import time
            from utils.pubg_api import get_seasons
            
            start = time.time()
            try:
                seasons = await get_seasons()
                ping = int((time.time() - start) * 1000)
                if seasons:
                    await interaction.followup.send(f"✅ **PUBG API працює відмінно!**\nЗатримка відповіді: `{ping}ms`\nКлюч API активний.")
                else:
                    await interaction.followup.send("⚠️ API повернуло пустий результат. Можливо, ключ невірний або API зараз нестабільне.")
            except Exception as e:
                await interaction.followup.send(f"❌ **Помилка з'єднання з API:**\n```\n{e}\n```\nМожливо, ключ прострочений або спрацював Rate Limit.")
                
        elif act == "reload_cogs":
            await interaction.response.defer(ephemeral=True)
            cogs_dir = os.path.dirname(__file__)
            loaded = 0
            errors = []
            
            for filename in os.listdir(cogs_dir):
                if filename.endswith('.py') and not filename.startswith('__'):
                    cog_name = f'cogs.{filename[:-3]}'
                    try:
                        await self.bot.reload_extension(cog_name)
                        loaded += 1
                    except Exception as e:
                        errors.append(f"{filename}: {e}")
            
            msg = f"✅ Успішно перезавантажено **{loaded}** модулів."
            if errors:
                msg += f"\n\n❌ **Помилки при перезавантаженні:**\n```\n" + "\n".join(errors)[:1000] + "\n```"
            await interaction.followup.send(msg)
            
        elif act == "cleanup":
            await interaction.response.send_message("🧹 Починаю очищення старих зображень та перевірку логів...", ephemeral=True)
            cleanup_old_assets(max_age_hours=0) # Видалити ВСІ тимчасові victory_*.png
            create_log(f"[ADMIN] {interaction.user} запустив ручне очищення.")
            await interaction.followup.send("✅ Очищення завершено. Тимчасові зображення перемог видалено.")
            
        elif act == "test_error":
            await interaction.response.send_message("🚨 Симулюю критичну помилку бази даних...", ephemeral=True)
            # Викликаємо глобальний обробник нібито виникла помилка
            import sqlite3
            fake_err = sqlite3.OperationalError("database or disk is full")
            import utils.data_handler as dh
            if dh._error_callback:
                dh._error_callback("Тестовий запит", fake_err)

async def setup(bot):
    await bot.add_cog(Maintenance(bot))
