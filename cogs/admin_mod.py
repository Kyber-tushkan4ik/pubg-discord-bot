import discord
from discord import app_commands
from discord.ext import commands
import json
import os

from utils.data_handler import get_data, save_data, get_settings, save_settings, delete_data
from utils.pubg_api import get_player
from utils.helpers import get_record_key, find_record, create_log, is_admin
from utils.moderation import add_warning, clear_warnings
from utils.scheduler import check_recent_matches, update_stats_and_ranks, send_weekly_report, check_inactivity
import time

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

class AdminCog(commands.Cog):
    manage_tracking = app_commands.Group(name="manage_tracking", description="Керування відстеженням активності")
    mod_group = app_commands.Group(name="mod", description="Команди модерації")

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="admin_link", description="Прив'язати PUBG нікнейм до Discord користувача (Адмін)")
    @app_commands.describe(target_user="Discord користувач", nickname="Нікнейм гравця в PUBG")
    @is_admin()
    async def admin_link(self, interaction: discord.Interaction, target_user: discord.Member, nickname: str):
        await interaction.response.defer()
        try:
            player = await get_player(nickname)
            if not player:
                await interaction.followup.send(f"❌ Гравця з нікнеймом **{nickname}** не знайдено в PUBG.", ephemeral=True)
                return
                
            guild_id = str(interaction.guild.id)
            user_id = str(target_user.id)
            key = get_record_key(user_id, guild_id)
            
            user_data = get_data()
            record = find_record(user_data, user_id, guild_id)
            
            if not record:
                user_data[key] = {
                    "username": str(target_user),
                    "userId": user_id,
                    "guildId": guild_id
                }
                record = user_data[key]
                
            real_name = player.get("attributes", {}).get("name", nickname)
            record["pubgNickname"] = real_name
            await save_data()
            
            embed = discord.Embed(
                title='✅ Профіль прив\'язано',
                description=f"Користувача **{target_user.mention}** успішно прив'язано до PUBG нікнейму **{real_name}**.",
                color=0x00FF00
            )
            await interaction.followup.send(embed=embed)
            
            try:
                bot_member = interaction.guild.me
                if bot_member.guild_permissions.manage_nicknames:
                    if target_user.id != interaction.guild.owner_id:
                        if bot_member.top_role > target_user.top_role:
                            await target_user.edit(nick=real_name)
                            create_log(f"[NICKNAME] Success: {target_user} -> {real_name}")
            except Exception as e:
                create_log(f"[NICKNAME] Error for {target_user}: {e}")
                
        except Exception as e:
            await interaction.followup.send("Сталася помилка. Перевірте API ключ.", ephemeral=True)



    @app_commands.command(name="admin_unlink", description="Видалити прив'язку PUBG нікнейму від Discord користувача (Адмін)")
    @app_commands.describe(user="Discord користувач")
    @is_admin()
    async def admin_unlink(self, interaction: discord.Interaction, user: discord.Member):
        user_data = get_data()
        record = find_record(user_data, str(user.id), str(interaction.guild.id))

        if not record or not record.get("pubgNickname"):
            await interaction.response.send_message(f"❌ У користувача **{user.display_name}** немає прив'язаного PUBG нікнейму.", ephemeral=True)
            return

        old_nick = record["pubgNickname"]
        del record["pubgNickname"]
        await save_data()

        embed = discord.Embed(
            title='✅ Прив\'язку видалено',
            description=f"Користувача **{user.mention}** відв'язано від нікнейму **{old_nick}**.",
            color=0xFF0000
        )
        await interaction.response.send_message(embed=embed)

    @manage_tracking.command(name="user", description="Припинити або відновити стеження за користувачем")
    @app_commands.describe(target="Користувач", status="Стежити? (True - так, False - ні)")
    @is_admin()
    async def manage_tracking_user(self, interaction: discord.Interaction, target: discord.Member, status: bool):
        key = get_record_key(str(target.id), str(interaction.guild.id))
        user_data = get_data()
        record = find_record(user_data, str(target.id), str(interaction.guild.id))

        if not record:
            user_data[key] = {
                "username": str(target),
                "userId": str(target.id),
                "guildId": str(interaction.guild.id)
            }
            record = user_data[key]

        record["untracked"] = not status
        await save_data()

        status_str = 'УВІМКНЕНО' if status else 'ВИМКНЕНО'
        await interaction.response.send_message(f"✅ Стеження за **{target.display_name}** тепер: **{status_str}**.", ephemeral=True)

    @manage_tracking.command(name="role", description='Ввімкнути або вимкнути стеження за всією роллю "Поплічник"')
    @app_commands.describe(enabled="Стежити за роллю?")
    @is_admin()
    async def manage_tracking_role(self, interaction: discord.Interaction, enabled: bool):
        bot_settings = get_settings()
        bot_settings["disableClanTracking"] = not enabled
        save_settings()

        status_str = 'УВІМКНЕНО' if enabled else 'ВИМКНЕНО'
        role_name = CONFIG.get("ROLE_SUCCESS", "Поплічник")
        await interaction.response.send_message(f"✅ Стеження за роллю **\"{role_name}\"** тепер: **{status_str}**.", ephemeral=True)

    @app_commands.command(name="clan_tracking", description='Керування відстеженням всієї ролі "Поплічник"')
    @app_commands.describe(action="Дія: увімкнути або вимкнути")
    @app_commands.choices(action=[
        app_commands.Choice(name='Увімкнути (Відновити)', value='on'),
        app_commands.Choice(name='Вимкнути (Зупинити)', value='off'),
        app_commands.Choice(name='Відновити для ВСІХ (скинути індивідуальні ігнори)', value='reset_all')
    ])
    @is_admin()
    async def clan_tracking(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        act = action.value
        bot_settings = get_settings()
        user_data = get_data()
        role_name = CONFIG.get("ROLE_SUCCESS", "Поплічник")

        if act == 'on':
            bot_settings["disableClanTracking"] = False
            await save_settings()
            await interaction.response.send_message(f"✅ Стеження за роллю **\"{role_name}\"** ВІДНОВЛЕНО.", ephemeral=True)
        elif act == 'off':
            bot_settings["disableClanTracking"] = True
            await save_settings()
            await interaction.response.send_message(f"🛑 Стеження за роллю **\"{role_name}\"** ПРИЗУПИНЕНО.", ephemeral=True)
        elif act == 'reset_all':
            bot_settings["disableClanTracking"] = False
            await save_settings()

            count = 0
            for key, data in user_data.items():
                if data.get("untracked"):
                    del data["untracked"]
                    count += 1
            await save_data()

            await interaction.response.send_message(f"✅ Стеження відновлено для всіх. Скинуто індивідуальні ігнори для **{count}** користувачів.", ephemeral=True)

    @app_commands.command(name="warn_inactive", description="Розіслати попередження неактивним учасникам (Адмін)")
    @app_commands.describe(days="Кількість днів неактивності", dry_run="Тестовий режим (тільки показати список)")
    @is_admin()
    async def warn_inactive(self, interaction: discord.Interaction, days: int = None, dry_run: bool = False):
        await interaction.response.defer()
        
        limit_days = days if days else CONFIG.get("INACTIVITY_DAYS_LIMIT", 14)
        limit_ms = limit_days * 24 * 3600000
        now = int(time.time() * 1000)

        user_data = get_data()
        role_success_name = CONFIG.get("ROLE_SUCCESS", "Поплічник")
        
        clan_members = [m for m in interaction.guild.members if any(r.name == role_success_name for r in m.roles)]

        if not clan_members:
            await interaction.followup.send("⚠️ Не знайдено жодного учасника з роллю клану.")
            return

        inactive_users = []
        game_name = CONFIG.get("GAME_NAME", "PUBG: BATTLEGROUNDS")

        for member in clan_members:
            data = find_record(user_data, str(member.id), str(interaction.guild.id))
            if data and data.get("untracked"):
                continue

            last_seen = data.get("lastPubgSeen", 0) if data else 0

            is_playing = any(a.name == game_name for a in member.activities)
            if is_playing:
                last_seen = now

            if now - last_seen > limit_ms:
                inactive_users.append({
                    "member": member,
                    "days": (now - last_seen) // (24 * 3600000),
                    "nickname": data.get("pubgNickname", member.name) if data else member.name
                })

        if not inactive_users:
            await interaction.followup.send(f"✅ Чудово! Немає учасників, які відсутні більше **{limit_days}** днів.")
            return

        list_str = "\n".join([f"• **{u['nickname']}** (<@{u['member'].id}>) — {u['days']} днів" for u in inactive_users])[:4000]

        if dry_run:
            embed = discord.Embed(
                title=f"📋 Кандидати на попередження ({len(inactive_users)})",
                description=f"Ці користувачі відсутні більше {limit_days} днів:\n\n{list_str}\n\n*Це тестовий режим, повідомлення НЕ надіслано.*",
                color=0xFFFF00
            )
            await interaction.followup.send(embed=embed)
            return

        success_count = 0
        fail_count = 0
        failed_usernames = []

        await interaction.followup.send(f"📨 Починаю розсилку для **{len(inactive_users)}** користувачів...")

        msg_text = (f"Вітаємо. Ви були відсутні в грі PUBG понад **{limit_days}** днів.\n"
                    "У зв'язку з тривалою неактивністю, вас буде виключено з клану найближчим часом.\n"
                    "Якщо ви бажаєте повернутися або вважаєте це помилкою — будь ласка, зверніться до Адміністратора або Модератора.\n\n"
                    "*Це автоматичне повідомлення від бота клану.*")

        for u in inactive_users:
            try:
                await u['member'].send(msg_text)
                success_count += 1
            except Exception as e:
                fail_count += 1
                failed_usernames.append(u['nickname'])
                create_log(f"Failed to DM {u['nickname']}: {e}")
            import asyncio
            await asyncio.sleep(1)

        report_embed = discord.Embed(
            title='📨 Звіт про розсилку',
            color=0xff9900 if fail_count > 0 else 0x00FF00
        )
        report_embed.add_field(name='Всього знайдено', value=str(len(inactive_users)), inline=True)
        report_embed.add_field(name='Надіслано успішно', value=str(success_count), inline=True)
        report_embed.add_field(name='Не вдалося надіслати', value=str(fail_count), inline=True)
        
        if failed_usernames:
            report_embed.description = f"**Не отримали повідомлення:**\n{', '.join(failed_usernames)}"

        await interaction.followup.send(embed=report_embed)

    @app_commands.command(name="add_external", description="Додати гравця клану, якого немає в Discord (Адмін)")
    @app_commands.describe(nickname="PUBG нікнейм")
    @is_admin()
    async def add_external(self, interaction: discord.Interaction, nickname: str):
        await interaction.response.defer()
        try:
            player = await get_player(nickname)
            if not player:
                await interaction.followup.send(f"❌ Гравець **{nickname}** не знайдений в PUBG.")
                return

            user_data = get_data()
            real_name = player.get("attributes", {}).get("name", nickname)

            existing = next((u for u in user_data.values() if u.get("pubgNickname", "").lower() == real_name.lower()), None)
            if existing:
                mention = "зовнішнього запису" if existing.get("userId", "").startswith('ext_') else f"<@{existing.get('userId')}>"
                await interaction.followup.send(f"❌ Гравець **{real_name}** вже є в базі (прив'язаний до {mention}).")
                return

            external_id = f"ext_{int(time.time() * 1000)}"
            key = f"{external_id}-{interaction.guild.id}"

            user_data[key] = {
                "userId": external_id,
                "guildId": str(interaction.guild.id),
                "username": f"[External] {real_name}",
                "pubgNickname": real_name,
                "isExternal": True,
                "isActive": False
            }
            await save_data()

            embed = discord.Embed(
                title='✅ Гравця додано',
                description=f"Гравця **{real_name}** додано до бази даних.\nВін буде відображатися в топах та статистиці.",
                color=0x2ecc71
            )
            embed.set_footer(text=f"ID: {external_id}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            create_log(f"Error add_external: {e}")
            await interaction.followup.send("Помилка при додаванні гравця.")

    @app_commands.command(name="remove_external", description="Видалити зовнішнього гравця з бази даних (Адмін)")
    @app_commands.describe(nickname="PUBG нікнейм гравця або ID")
    @is_admin()
    async def remove_external(self, interaction: discord.Interaction, nickname: str):
        input_str = nickname.strip()
        user_data = get_data()

        entry_key, entry_user = None, None
        for key, user in user_data.items():
            is_ext = user.get("isExternal") or (user.get("userId") and str(user.get("userId")).startswith('ext_'))
            if not is_ext:
                continue
            
            p_nick = user.get("pubgNickname", "")
            if p_nick.lower() == input_str.lower():
                entry_key, entry_user = key, user
                break
                
            if key == input_str or user.get("userId") == input_str:
                entry_key, entry_user = key, user
                break
                
        if not entry_key:
            candidates = []
            for key, user in user_data.items():
                is_ext = user.get("isExternal") or (user.get("userId") and str(user.get("userId")).startswith('ext_'))
                if is_ext and user.get("pubgNickname") and input_str.lower() in user.get("pubgNickname").lower():
                    candidates.append(f"• {user.get('pubgNickname')} (ID: `{key}`)")
            
            msg = f"❌ Зовнішнього гравця **{input_str}** не знайдено."
            if candidates:
                msg += f"\n🔍 Можливо ви мали на увазі:\n" + "\n".join(candidates) + "\n\n💡 Ви можете скопіювати ID та вставити його замість нікнейму для видалення."
            else:
                msg += " (Переконайтеся, що це саме зовнішній гравець)"
                
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await delete_data(entry_key)
        
        embed = discord.Embed(
            title='🗑️ Гравця видалено',
            description=f"Зовнішній профіль гравця **{entry_user.get('pubgNickname')}** було успішно видалено з бази даних.\nID: {entry_key}",
            color=0xe74c3c
        )
        await interaction.response.send_message(embed=embed)

    @mod_group.command(name="warn", description="Видати попередження користувачу")
    @app_commands.describe(user="Користувач", reason="Причина")
    @is_admin()
    async def mod_warn(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        warn_count = await add_warning(self.bot, str(interaction.guild.id), str(user.id), f"Адмін: {reason}")
        await interaction.response.send_message(f"Попередження видано <@{user.id}>. Попереджень: {warn_count}", ephemeral=True)

    @mod_group.command(name="clear_warns", description="Очистити попередження користувача")
    @app_commands.describe(user="Користувач")
    @is_admin()
    async def mod_clear_warns(self, interaction: discord.Interaction, user: discord.Member):
        success = await clear_warnings(str(user.id))
        if success:
            await interaction.response.send_message(f"Попередження для <@{user.id}> очищено.", ephemeral=True)
        else:
            await interaction.response.send_message(f"У користувача <@{user.id}> немає попереджень.", ephemeral=True)

    @app_commands.command(name="debug_run", description="Ручний запуск запланованих завдань (Адмін)")
    @app_commands.describe(task="Яке завдання запустити?")
    @app_commands.choices(task=[
        app_commands.Choice(name='Daily Check (Matches & Sniper)', value='daily_check'),
        app_commands.Choice(name='Update Ranks', value='update_ranks'),
        app_commands.Choice(name='Weekly Report', value='weekly_report'),
        app_commands.Choice(name='Inactivity Check', value='inactivity_check')
    ])
    @is_admin()
    async def debug_run(self, interaction: discord.Interaction, task: app_commands.Choice[str]):
        await interaction.response.send_message(f"⏳ Запуск завдання: **{task.value}**...", ephemeral=True)
        try:
            if task.value == 'daily_check':
                await check_recent_matches(self.bot)
                await interaction.edit_original_response(content=f"✅ Завдання **Daily Check** завершено (додано в чергу). Перевірте логи.")
            elif task.value == 'update_ranks':
                await update_stats_and_ranks(self.bot)
                await interaction.edit_original_response(content=f"✅ Завдання **Update Ranks** завершено (додано в чергу). Перевірте логи.")
            elif task.value == 'weekly_report':
                await send_weekly_report(self.bot)
                await interaction.edit_original_response(content=f"✅ Завдання **Weekly Report** завершено.")
            elif task.value == 'inactivity_check':
                await check_inactivity(self.bot)
                await interaction.edit_original_response(content=f"✅ Завдання **Inactivity Check** завершено (додано в чергу).")
        except Exception as e:
            create_log(f"Error debug_run: {e}")
            await interaction.edit_original_response(content=f"❌ Помилка при виконанні завдання: {e}")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
    print("Loaded extension: admin_mod")
