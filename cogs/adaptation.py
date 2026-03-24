import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import time

from utils.data_handler import get_data, save_data
from utils.core import check_user
from utils.helpers import get_record_key, find_record, create_log, ms_to_readable, is_admin

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

class AdaptationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="adapt_add_time", description="Додати час до прогресу (Адмін)")
    @app_commands.describe(target_user="Користувач", hours="Години")
    @is_admin()
    async def adapt_add_time(self, interaction: discord.Interaction, target_user: discord.Member, hours: int):
        user_data = get_data()
        record = find_record(user_data, str(target_user.id), str(interaction.guild.id))
        
        if not record or not record.get("isActive"):
            await interaction.response.send_message("Немає активної адаптації.", ephemeral=True)
            return
            
        record["totalPlayTime"] = record.get("totalPlayTime", 0) + (hours * 3600000)
        await save_data()
        
        await interaction.response.send_message(
            f"✅ Додано {hours} год. Новий час: {ms_to_readable(record['totalPlayTime'])}",
            ephemeral=True
        )
        
        required_ms = CONFIG.get("REQUIRED_PLAY_MS", 0)
        if record["totalPlayTime"] >= required_ms:
            try:
                await check_user(target_user, str(target_user.id))
            except Exception as e:
                pass



    @app_commands.command(name="adapt_status", description="Перевірити статус адаптації (свій або іншого)")
    @app_commands.describe(user="Користувач (пусто = перевірити себе)")
    async def adapt_status(self, interaction: discord.Interaction, user: discord.Member = None):
        target_user = user or interaction.user
        user_data = get_data()
        record = find_record(user_data, str(target_user.id), str(interaction.guild.id))

        if not record:
            await interaction.response.send_message(
                f"У користувача {target_user.display_name} немає активної або архівної адаптації.",
                ephemeral=True
            )
            return

        total_time = record.get("totalPlayTime", 0)
        now = int(time.time() * 1000)
        
        if record.get("isActive") and record.get("lastSessionStart"):
            total_time += (now - record["lastSessionStart"])

        played_str = ms_to_readable(total_time)
        elapsed = now - record.get("startTime", now)

        effective_limit_offset = record.get("limitOffset", 0)
        if record.get("isPaused") and record.get("pauseStartTime"):
            effective_limit_offset += (now - record["pauseStartTime"])
            
        limit = CONFIG.get("TIME_LIMIT_MS", 259200000) + effective_limit_offset
        remaining_time = max(0, limit - elapsed)

        status = "🟢 Активна" if record.get("isActive") else "🔴 Завершена"
        if record.get("isPaused"):
            status = "⏸️ Призупинена"
        elif record.get("lastSessionStart"):
            status += " (Зараз у грі)"
            
        if record.get("result"):
            status += f" [{str(record['result']).upper()}]"

        role_display = "Невідомо"
        try:
            role_display = target_user.top_role.name
        except Exception:
            pass

        req_hours = CONFIG.get("REQUIRED_PLAY_MS", 0) // 3600000

        embed = discord.Embed(title=f"Статус адаптації: {record.get('username')}", color=0x3498db)
        embed.add_field(name="Статус", value=status, inline=False)
        embed.add_field(name="Роль", value=role_display, inline=True)
        embed.add_field(name="Зіграно", value=f"{played_str} / {req_hours}год", inline=True)
        
        rem_str = ms_to_readable(remaining_time) if record.get("isActive") else "0хв"
        embed.add_field(name="Залишилось часу", value=rem_str, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="adapt_finish", description="Достроково завершити адаптацію успішно (Адмін)")
    @app_commands.describe(user="Користувач")
    @is_admin()
    async def adapt_finish(self, interaction: discord.Interaction, user: discord.Member):
        user_data = get_data()
        record = find_record(user_data, str(user.id), str(interaction.guild.id))

        if not record:
            await interaction.response.send_message("Немає активної адаптації.", ephemeral=True)
            return

        await interaction.response.send_message(f"🚀 Дострокове завершення для {user.display_name}...", ephemeral=True)

        record["totalPlayTime"] = CONFIG.get("REQUIRED_PLAY_MS", 0) + 1000
        record["result"] = 'success'
        await save_data()

        try:
            await check_user(user, str(user.id))
        except Exception as e:
            create_log(f"Error checking user after adapt_finish: {e}")



    @app_commands.command(name="adapt_cancel", description="Скасувати адаптацію (Адмін)")
    @app_commands.describe(user="Користувач")
    @is_admin()
    async def adapt_cancel(self, interaction: discord.Interaction, user: discord.Member):
        user_data = get_data()
        record = find_record(user_data, str(user.id), str(interaction.guild.id))

        if not record:
            await interaction.response.send_message("Немає активної адаптації.", ephemeral=True)
            return

        record["isActive"] = False
        record["result"] = 'cancelled'
        await save_data()

        await interaction.response.send_message(f"⛔ Адаптацію скасовано для {user.display_name}.", ephemeral=True)
        try:
            msg = "🛑 Твою адаптацію було скасовано адміністратором."
            await user.send(msg)
            create_log(f"[DM SENT] To: {user} Content: {msg}")
        except Exception:
            pass



    @app_commands.command(name="adapt_pause", description="Призупинити адаптації (Адмін)")
    @app_commands.describe(user="Користувач")
    @is_admin()
    async def adapt_pause(self, interaction: discord.Interaction, user: discord.Member):
        user_data = get_data()
        record = find_record(user_data, str(user.id), str(interaction.guild.id))

        if not record:
            await interaction.response.send_message("Немає активної адаптації.", ephemeral=True)
            return
        if record.get("isPaused"):
            await interaction.response.send_message("Вже на паузі.", ephemeral=True)
            return

        now = int(time.time() * 1000)
        record["isPaused"] = True
        record["pauseStartTime"] = now
        
        if record.get("lastSessionStart"):
            record["totalPlayTime"] = record.get("totalPlayTime", 0) + (now - record["lastSessionStart"])
            record["lastSessionStart"] = None
            
        await save_data()
        await interaction.response.send_message(f"⏸️ Адаптацію призупинено для {user.display_name}.", ephemeral=True)



    @app_commands.command(name="adapt_resume", description="Відновити адаптацію (Адмін)")
    @app_commands.describe(user="Користувач")
    @is_admin()
    async def adapt_resume(self, interaction: discord.Interaction, user: discord.Member):
        user_data = get_data()
        record = find_record(user_data, str(user.id), str(interaction.guild.id))

        if not record:
            await interaction.response.send_message("Немає активної адаптації.", ephemeral=True)
            return
        if not record.get("isPaused"):
            await interaction.response.send_message("Не на паузі.", ephemeral=True)
            return

        now = int(time.time() * 1000)
        paused_duration = now - record.get("pauseStartTime", now)
        record["limitOffset"] = record.get("limitOffset", 0) + paused_duration
        record["isPaused"] = False
        record["pauseStartTime"] = None

        game_name = CONFIG.get("GAME_NAME")
        if any(a.name == game_name for a in user.activities):
            record["lastSessionStart"] = now

        await save_data()
        await interaction.response.send_message(f"▶️ Адаптацію відновлено. Таймер продовжено на {ms_to_readable(paused_duration)}.", ephemeral=True)



    @app_commands.command(name="adapt_remove_time", description="Відняти час від ПРОГРЕСУ (Адмін)")
    @app_commands.describe(user="Користувач", hours="Години")
    @is_admin()
    async def adapt_remove_time(self, interaction: discord.Interaction, user: discord.Member, hours: int):
        user_data = get_data()
        record = find_record(user_data, str(user.id), str(interaction.guild.id))

        if not record:
            await interaction.response.send_message("Немає активної адаптації.", ephemeral=True)
            return

        new_val = record.get("totalPlayTime", 0) - (hours * 3600000)
        record["totalPlayTime"] = max(0, new_val)
        await save_data()

        await interaction.response.send_message(f"✅ Віднято {hours} год. Новий час: {ms_to_readable(record['totalPlayTime'])}", ephemeral=True)



    @app_commands.command(name="adapt_deadline_extend", description="Збільшити термін адаптації (Адмін)")
    @app_commands.describe(user="Користувач", hours="Години")
    @is_admin()
    async def adapt_deadline_extend(self, interaction: discord.Interaction, user: discord.Member, hours: int):
        user_data = get_data()
        record = find_record(user_data, str(user.id), str(interaction.guild.id))

        if not record:
            await interaction.response.send_message("Немає активної адаптації.", ephemeral=True)
            return

        record["limitOffset"] = record.get("limitOffset", 0) + (hours * 3600000)
        await save_data()
        limit_hours = (CONFIG.get("TIME_LIMIT_MS", 259200000) + record["limitOffset"]) / 3600000

        await interaction.response.send_message(f"✅ Термін ЗБІЛЬШЕНО на {hours} год. Ліміт: {limit_hours:.1f} год.", ephemeral=True)



    @app_commands.command(name="adapt_deadline_reduce", description="Зменшити термін адаптації (Адмін)")
    @app_commands.describe(user="Користувач", hours="Години")
    @is_admin()
    async def adapt_deadline_reduce(self, interaction: discord.Interaction, user: discord.Member, hours: int):
        user_data = get_data()
        record = find_record(user_data, str(user.id), str(interaction.guild.id))

        if not record:
            await interaction.response.send_message("Немає активної адаптації.", ephemeral=True)
            return

        record["limitOffset"] = record.get("limitOffset", 0) - (hours * 3600000)
        await save_data()
        limit_hours = (CONFIG.get("TIME_LIMIT_MS", 259200000) + record["limitOffset"]) / 3600000

        await interaction.response.send_message(f"✅ Термін ЗМЕНШЕНО на {hours} год. Ліміт: {limit_hours:.1f} год.", ephemeral=True)



    @app_commands.command(name="adapt_archive", description="Переглянути архів проходження адаптації")
    @app_commands.describe(status_filter="Фільтр")
    @app_commands.choices(status_filter=[
        app_commands.Choice(name='Успішно', value='success'),
        app_commands.Choice(name='Провалено', value='failed'),
        app_commands.Choice(name='Скасовано', value='cancelled')
    ])
    @is_admin()
    async def adapt_archive(self, interaction: discord.Interaction, status_filter: app_commands.Choice[str] = None):
        filter_val = status_filter.value if status_filter else None
        user_data = get_data()
        
        from typing import List, Dict, Any
        lst: List[Dict[str, Any]] = []

        for uid, data in user_data.items():
            if data.get("startTime") and not data.get("isActive"):
                st = data.get("result")
                if not st:
                    st = 'success' if data.get("totalPlayTime", 0) >= CONFIG.get("REQUIRED_PLAY_MS", 0) else 'failed'
                if filter_val and st != filter_val:
                    continue
                lst.append({
                    "tag": data.get("username"),
                    "status": st,
                    "time": data.get("totalPlayTime", 0),
                    "date": data.get("startTime", 0)
                })

        if not lst:
            f_text = f"(фільтр: {filter_val})" if filter_val else ""
            await interaction.response.send_message(f"Архів порожній {f_text}.", ephemeral=True)
            return

        lst.sort(key=lambda x: x["date"], reverse=True)

        f_text = f"({filter_val})" if filter_val else ""
        msg = f"**Архів адаптацій** {f_text}:\n"
        for item in lst[:20]:
            msg += f"• **{item['tag']}** - {item['status'].upper()} ({ms_to_readable(item['time'])})\n"
        
        if len(lst) > 20:
            msg += f"...ще {len(lst) - 20} записів."

        await interaction.response.send_message(msg, ephemeral=True)



    @app_commands.command(name="adapt_fix_glitch", description="Виправити помилковий провал адаптації (Адмін)")
    @app_commands.describe(user="Користувач", bonus_hours="Бонус години")
    @is_admin()
    async def adapt_fix_glitch(self, interaction: discord.Interaction, user: discord.Member, bonus_hours: int = 0):
        user_data = get_data()
        record = find_record(user_data, str(user.id), str(interaction.guild.id))

        if not record:
            key = get_record_key(str(user.id), str(interaction.guild.id))
            user_data[key] = {
                "startTime": int(time.time() * 1000) - CONFIG.get("REQUIRED_PLAY_MS", 0),
                "totalPlayTime": 0,
                "isActive": True,
                "username": str(user),
                "userId": str(user.id),
                "guildId": str(interaction.guild.id)
            }
            record = user_data[key]

        record["isActive"] = False
        record["result"] = 'success'
        req_ms = CONFIG.get("REQUIRED_PLAY_MS", 0)
        
        bonus_ms = bonus_hours * 3600000
        if record.get("totalPlayTime", 0) < req_ms:
            record["totalPlayTime"] = req_ms + bonus_ms
        else:
            record["totalPlayTime"] += bonus_ms
            
        await save_data()
        await interaction.response.send_message(f"🛠️ Виправлено для {user.display_name}. Статус: УСПІХ.", ephemeral=True)

        try:
            role_adapt_name = CONFIG.get("ROLE_ADAPT")
            role_success_name = CONFIG.get("ROLE_SUCCESS")
            
            role_adapt = discord.utils.get(interaction.guild.roles, name=role_adapt_name)
            role_success = discord.utils.get(interaction.guild.roles, name=role_success_name)

            if role_adapt in user.roles:
                await user.remove_roles(role_adapt)
            if role_success and role_success not in user.roles:
                await user.add_roles(role_success)

            apology_msg = "✅ **Оновлення статусу адаптації**\nСталася технічна помилка, через яку вам могло прийти сповіщення про провал.\n**Ви успішно пройшли адаптацію!** Вітаємо у клані! 🎉"
            await user.send(apology_msg)
            create_log(f"[DM SENT] To: {user} Content: {apology_msg.replace(chr(10), ' ')}")
            create_log(f"[FIX] Fixed status for {user}")
        except Exception as e:
            create_log(f"[FIX ERROR] Failed to fix roles/DMs for {user}: {e}")



    @app_commands.command(name="adapt", description="Відкрити панель керування адаптацією (Меню)")
    @is_admin()
    async def adapt_panel(self, interaction: discord.Interaction):
        await send_main_panel(interaction)




# --- UI Components for Adapt Panel ---

async def send_main_panel(interaction: discord.Interaction, is_update=False):
    embed = discord.Embed(
        title='🎛️ Панель Керування Адаптацією',
        description='Виберіть користувача зі списку нижче, щоб керувати його процесом адаптації, або перегляньте архів.',
        color=0x5865F2
    )
    embed.add_field(
        name='Доступні дії',
        value='• Статус\n• Пауза/Відновлення\n• Додавання/Зняття часу\n• Зміна дедлайну\n• Завершення/Скасування'
    )
    view = AdaptMainView()
    if is_update:
        await interaction.response.edit_message(embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def send_user_panel(interaction: discord.Interaction, user_id: str):
    user_data = get_data()
    record = find_record(user_data, user_id, str(interaction.guild.id))

    if not record:
        view = discord.ui.View()
        back_btn = discord.ui.Button(label="Назад", style=discord.ButtonStyle.primary, custom_id="adapt_home")
        
        async def back_callback(interaction: discord.Interaction):
            await send_main_panel(interaction, is_update=True)
            
        back_btn.callback = back_callback
        view.add_item(back_btn)
        await interaction.response.edit_message(content=f"❌ Запис для <@{user_id}> не знайдено.", embeds=[], view=view)
        return

    is_active = record.get("isActive", False)
    if is_active:
        status_text = '⏸️ Пауза' if record.get("isPaused") else '▶️ Активний'
    else:
        status_text = '⏹️ Не активний (Прив\'язаний)'

    color = 0x2ecc71 if is_active else 0x95a5a6
    embed = discord.Embed(
        title=f"⚙️ Керування: {record.get('username')}",
        description=f"**ID:** {user_id}\n**Статус:** {status_text}",
        color=color
    )
    
    total_time = record.get("totalPlayTime", 0)
    embed.add_field(name='⏳ Відіграно', value=ms_to_readable(total_time), inline=True)
    
    if is_active:
        dl_ts = (record.get("startTime", 0) + CONFIG.get("TIME_LIMIT_MS", 259200000) + record.get("limitOffset", 0)) // 1000
        embed.add_field(name='📅 Дедлайн', value=f"<t:{dl_ts}:R>", inline=True)
    else:
        embed.add_field(name='📅 Дедлайн', value='Не встановлено', inline=True)

    view = AdaptUserView(user_id, record)
    await interaction.response.edit_message(content='', embed=embed, view=view)


class AdaptMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.user_select = discord.ui.UserSelect(placeholder='🔍 Вибрати користувача...', min_values=1, max_values=1)
        self.user_select.callback = self.on_user_select
        self.add_item(self.user_select)

        self.archive_btn = discord.ui.Button(label='📂 Архів Адаптацій', style=discord.ButtonStyle.secondary)
        self.archive_btn.callback = self.on_archive
        self.add_item(self.archive_btn)

    async def on_user_select(self, interaction: discord.Interaction):
        user_id = str(self.user_select.values[0].id)
        await send_user_panel(interaction, user_id)

    async def on_archive(self, interaction: discord.Interaction):
        user_data = get_data()
        archived = [u for u in user_data.values() if not u.get("isActive") and u.get("result")]
        archived.sort(key=lambda x: x.get("startTime", 0), reverse=True)
        
        list_str = ""
        for u in archived[:10]:
            res = u.get("result")
            icon = '✅' if res == 'success' else ('❌' if res == 'failed' else '🚫')
            list_str += f"{icon} **{u.get('username')}** - {res} ({ms_to_readable(u.get('totalPlayTime', 0))})\n"
            
        embed = discord.Embed(title='📂 Архів (Останні 10)', description=list_str or 'Архів порожній')
        view = discord.ui.View()
        back_btn = discord.ui.Button(label="Назад", style=discord.ButtonStyle.primary)
        
        async def back_cb(i: discord.Interaction):
            await send_main_panel(i, True)
            
        back_btn.callback = back_cb
        view.add_item(back_btn)
        await interaction.response.edit_message(embed=embed, view=view)


class AdaptUserView(discord.ui.View):
    def __init__(self, user_id: str, record: dict):
        super().__init__(timeout=None)
        self.user_id = user_id
        is_active = record.get("isActive", False)
        is_paused = record.get("isPaused", False)

        # Row 1
        btn_status = discord.ui.Button(label='ℹ️ Деталі', style=discord.ButtonStyle.secondary, row=0)
        btn_status.callback = self.on_status
        self.add_item(btn_status)

        if is_active:
            btn_pause_resume = discord.ui.Button(
                label='▶️ Відновити' if is_paused else '⏸️ Пауза',
                style=discord.ButtonStyle.success if is_paused else discord.ButtonStyle.primary,
                row=0
            )
            btn_pause_resume.callback = self.on_pause_resume
            self.add_item(btn_pause_resume)
        else:
            btn_start = discord.ui.Button(label='▶️ Почати Адаптацію', style=discord.ButtonStyle.success, row=0)
            btn_start.callback = self.on_start
            self.add_item(btn_start)

        btn_back = discord.ui.Button(label='🏠 Назад', style=discord.ButtonStyle.secondary, row=0)
        btn_back.callback = lambda i: send_main_panel(i, True)
        self.add_item(btn_back)

        # Actions
        if is_active:
            btn_add = discord.ui.Button(label='+ Час', style=discord.ButtonStyle.secondary, row=1)
            btn_add.callback = lambda i: i.response.send_modal(TimeModal('add', self.user_id))
            self.add_item(btn_add)

            btn_rem = discord.ui.Button(label='- Час', style=discord.ButtonStyle.secondary, row=1)
            btn_rem.callback = lambda i: i.response.send_modal(TimeModal('remove', self.user_id))
            self.add_item(btn_rem)

            btn_ext = discord.ui.Button(label='+ Дедлайн', style=discord.ButtonStyle.secondary, row=1)
            btn_ext.callback = lambda i: i.response.send_modal(TimeModal('extend', self.user_id))
            self.add_item(btn_ext)

            btn_red = discord.ui.Button(label='- Дедлайн', style=discord.ButtonStyle.secondary, row=1)
            btn_red.callback = lambda i: i.response.send_modal(TimeModal('reduce', self.user_id))
            self.add_item(btn_red)

            btn_fin = discord.ui.Button(label='✅ Зарахувати', style=discord.ButtonStyle.success, row=2)
            btn_fin.callback = self.on_finish
            self.add_item(btn_fin)

            btn_can = discord.ui.Button(label='❌ Скасувати', style=discord.ButtonStyle.danger, row=2)
            btn_can.callback = self.on_cancel
            self.add_item(btn_can)

    async def on_status(self, interaction: discord.Interaction):
        record = find_record(get_data(), self.user_id, str(interaction.guild.id))
        embed = discord.Embed(title=f"📄 Детальний статус: {record.get('username')}", color=0x0099ff)
        embed.add_field(name='Play Time', value=ms_to_readable(record.get('totalPlayTime', 0)), inline=True)
        embed.add_field(name='Is Paused', value='Yes' if record.get('isPaused') else 'No', inline=True)
        embed.add_field(name='Limit Offset', value=ms_to_readable(record.get('limitOffset', 0)), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_pause_resume(self, interaction: discord.Interaction):
        user_data = get_data()
        record = find_record(user_data, self.user_id, str(interaction.guild.id))
        if record:
            record["isPaused"] = not record.get("isPaused", False)
            if record["isPaused"]:
                record["pauseStartTime"] = int(time.time() * 1000)
                if record.get("lastSessionStart"):
                    record["totalPlayTime"] = record.get("totalPlayTime", 0) + (int(time.time() * 1000) - record["lastSessionStart"])
                    record["lastSessionStart"] = None
            else:
                paused_duration = int(time.time() * 1000) - record.get("pauseStartTime", int(time.time() * 1000))
                record["limitOffset"] = record.get("limitOffset", 0) + paused_duration
                record["pauseStartTime"] = None
            await save_data()
            await send_user_panel(interaction, self.user_id)
        else:
            await interaction.response.send_message("Запис не знайдено", ephemeral=True)

    async def on_start(self, interaction: discord.Interaction):
        user_data = get_data()
        record = find_record(user_data, self.user_id, str(interaction.guild.id))
        if record:
            record["isActive"] = True
            record["isPaused"] = False
            record["startTime"] = int(time.time() * 1000)
            record["totalPlayTime"] = 0
            await save_data()
            await send_user_panel(interaction, self.user_id)

    async def on_finish(self, interaction: discord.Interaction):
        user_data = get_data()
        record = find_record(user_data, self.user_id, str(interaction.guild.id))
        if record:
            record["isActive"] = False
            record["result"] = 'success'
            await save_data()
            try:
                member = interaction.guild.get_member(int(self.user_id)) or await interaction.guild.fetch_member(int(self.user_id))
                await check_user(member, self.user_id)
                await interaction.response.edit_message(content=f"✅ Адаптацію для <@{self.user_id}> завершено успішно!", embeds=[], view=None)
            except Exception as e:
                await interaction.response.edit_message(content=f"✅ Статус оновлено в БД, але помилка: {e}", embeds=[], view=None)

    async def on_cancel(self, interaction: discord.Interaction):
        user_data = get_data()
        record = find_record(user_data, self.user_id, str(interaction.guild.id))
        if record:
            record["isActive"] = False
            record["result"] = 'cancelled'
            await save_data()
            await interaction.response.edit_message(content=f"❌ Адаптацію для <@{self.user_id}> скасовано.", embeds=[], view=None)


class TimeModal(discord.ui.Modal):
    def __init__(self, action_type: str, user_id: str):
        self.action_type = action_type
        self.user_id = user_id
        titles = {
            'add': 'Додати час гри',
            'remove': 'Зняти час гри',
            'extend': 'Подовжити дедлайн',
            'reduce': 'Зменшити дедлайн'
        }
        super().__init__(title=titles[action_type])
        self.hours_input = discord.ui.TextInput(
            label='Кількість годин',
            style=discord.TextStyle.short,
            placeholder='Наприклад: 1 або 0.5',
            required=True
        )
        self.add_item(self.hours_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = float(self.hours_input.value.replace(',', '.'))
            if val <= 0:
                raise ValueError()
        except:
            await interaction.response.send_message('❌ Введіть коректне додатнє число.', ephemeral=True)
            return

        user_data = get_data()
        record = find_record(user_data, self.user_id, str(interaction.guild.id))
        if not record:
            await interaction.response.send_message('Error', ephemeral=True)
            return

        ms = int(val * 3600000)
        msg = ""

        if self.action_type == 'add':
            record["totalPlayTime"] = record.get("totalPlayTime", 0) + ms
            msg = f"✅ Додано {val} год. до часу гри."
        elif self.action_type == 'remove':
            record["totalPlayTime"] = max(0, record.get("totalPlayTime", 0) - ms)
            msg = f"✅ Знято {val} год. з часу гри."
        elif self.action_type == 'extend':
            record["limitOffset"] = record.get("limitOffset", 0) + ms
            msg = f"✅ Дедлайн подовжено на {val} год."
        elif self.action_type == 'reduce':
            record["limitOffset"] = record.get("limitOffset", 0) - ms
            msg = f"✅ Дедлайн зменшено на {val} год."

        await save_data()
        await interaction.response.send_message(msg, ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdaptationCog(bot))
    print("Loaded extension: adaptation")
