import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import shutil
import datetime
from utils.helpers import create_log, cleanup_old_assets, is_admin

class Maintenance(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.monthly_clan_roster_check.start()

    def cog_unload(self):
        self.monthly_clan_roster_check.cancel()

    @tasks.loop(hours=24)
    async def monthly_clan_roster_check(self):
        now = datetime.datetime.now()
        # Перевіряємо, чи сьогодні 1-ше число місяця
        if now.day != 1:
            return
            
        from utils.data_handler import get_data, get_settings, save_settings
        settings = get_settings()
        
        current_month = f"{now.year}-{now.month}"
        if settings.get("lastMonthlyRosterCheck") == current_month:
            return
            
        try:
            user_data = get_data()
            discord_players = []
            external_players = []
            
            for key, user in user_data.items():
                if user.get("pubgNickname") and not user.get("untracked"):
                    is_ext = user.get("isExternal") or (user.get("userId") and str(user.get("userId")).startswith('ext_'))
                    if is_ext:
                        external_players.append(f"• {user.get('pubgNickname')} (ID: `{key}`)")
                    else:
                        discord_players.append(f"• {user.get('pubgNickname')} (<@{user.get('userId')}>)")
                        
            owner = await self.bot.fetch_user(776154533742641174)
            if not owner:
                return
                
            embed = discord.Embed(
                title="📅 Щомісячна перевірка складу клану",
                description=(
                    "Привіт! Почався новий місяць. Будь ласка, перевір список гравців, за якими бот веде відстеження.\n\n"
                    "**Чи покинув хтось клан за цей час?**\n"
                    "Якщо так, використай команду `/force_delete_user` або `/remove_external`, щоб я перестав вести за ними рахунок онлайну та оновлювати статистику."
                ),
                color=0x3498db
            )
            
            if discord_players:
                d_str = "\n".join(discord_players)
                if len(d_str) > 1024: d_str = d_str[:1000] + "..."
                embed.add_field(name=f"🎮 Гравці з Discord ({len(discord_players)})", value=d_str, inline=False)
                
            if external_players:
                e_str = "\n".join(external_players)
                if len(e_str) > 1024: e_str = e_str[:1000] + "..."
                embed.add_field(name=f"🌐 Зовнішні гравці ({len(external_players)})", value=e_str, inline=False)
                
            await owner.send(embed=embed)
            
            settings["lastMonthlyRosterCheck"] = current_month
            await save_settings()
        except Exception as e:
            create_log(f"Error in monthly_clan_roster_check: {e}")

    @monthly_clan_roster_check.before_loop
    async def before_monthly_check(self):
        await self.bot.wait_until_ready()

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

    @app_commands.command(name="control_panel", description="Кишеньковий пульт управління (тільки для адмінів)")
    @is_admin()
    async def control_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎛️ Пульт Управління Ботом",
            description="Використовуйте кнопки нижче для швидкого керування з телефону.",
            color=0x2b2d31
        )
        view = ControlPanelView(self.bot)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

class AnnouncementModal(discord.ui.Modal, title='Створити оголошення'):
    announcement_text = discord.ui.TextInput(
        label='Текст оголошення',
        style=discord.TextStyle.paragraph,
        placeholder='Введіть текст, який буде надіслано в головний канал...',
        required=True,
        max_length=2000
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        # Отримуємо налаштування для пошуку головного каналу (або використовуємо канал, з якого викликали)
        channel = interaction.channel
        
        embed = discord.Embed(
            title="📢 Оголошення",
            description=self.announcement_text.value,
            color=0xffcc00,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Від: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        
        await channel.send(embed=embed)
        await interaction.response.send_message("✅ Оголошення успішно надіслано!", ephemeral=True)

class ControlPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None) # Persistent view
        self.bot = bot

    @discord.ui.button(label="Рестарт Бота", style=discord.ButtonStyle.danger, emoji="🔄", custom_id="panel_restart")
    async def restart_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Немає прав.", ephemeral=True)
            
        await interaction.response.send_message("🔄 Перезапускаю бота...", ephemeral=True)
        create_log(f"[SYSTEM] Рестарт ініційований {interaction.user} через пульт.")
        import sys
        sys.exit(0) # Якщо бот запускається через PM2 або bash loop, він сам підніметься.

    @discord.ui.button(label="Очистити кеш", style=discord.ButtonStyle.secondary, emoji="🧹", custom_id="panel_cache")
    async def cache_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🧹 Очищаю тимчасові файли...", ephemeral=True)
        cleanup_old_assets(max_age_hours=0)
        await interaction.edit_original_response(content="✅ Тимчасові зображення перемог видалено.")

    @discord.ui.button(label="Звіт по БД", style=discord.ButtonStyle.success, emoji="📊", custom_id="panel_db")
    async def db_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        db_file = os.path.join(os.path.dirname(__file__), '../database.sqlite')
        db_size = os.path.getsize(db_file) / (1024 * 1024) if os.path.exists(db_file) else 0
        await interaction.response.send_message(f"🗄️ Розмір бази даних: **{db_size:.2f} MB**.\nБаза працює стабільно.", ephemeral=True)

    @discord.ui.button(label="Швидке оголошення", style=discord.ButtonStyle.primary, emoji="📢", custom_id="panel_announce")
    async def announce_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Немає прав.", ephemeral=True)
        await interaction.response.send_modal(AnnouncementModal(self.bot))


async def setup(bot):
    await bot.add_cog(Maintenance(bot))
