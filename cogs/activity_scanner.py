import discord
from discord.ext import commands
from discord import app_commands
import os
import io
import re
import asyncio
import datetime
import time
from PIL import Image
import google.generativeai as genai
from utils.pubg_api import get_players_batch, get_latest_match_date
from utils.data_handler import get_data, add_tracked_player, remove_tracked_player, get_all_tracked_players
from discord.ext import tasks

# Kyiv time timezone (UTC+3)
KYIV_TZ = datetime.timezone(datetime.timedelta(hours=3))

class UntrackView(discord.ui.View):
    def __init__(self, bot, nicknames):
        super().__init__(timeout=None)
        self.bot = bot
        # discord has a limit of 25 buttons per view
        for nick in nicknames[:25]:
            btn = discord.ui.Button(label=f"❌ {nick}", style=discord.ButtonStyle.danger, custom_id=f"untrack_{nick}")
            btn.callback = self.make_callback(nick)
            self.add_item(btn)

    def make_callback(self, nickname):
        async def callback(interaction: discord.Interaction):
            await remove_tracked_player(nickname)
            # Remove button from view
            for child in self.children:
                if child.custom_id == f"untrack_{nickname}":
                    self.remove_item(child)
                    break
            
            try:
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ Гравець **{nickname}** видалений з відстеження.", ephemeral=True)
            except Exception as e:
                print(f"Error editing view: {e}")
        return callback

    def __init__(self, bot):
        self.bot = bot
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        # Кеш для зменшення запитів до API (зберігається в пам'яті до рестарту)
        self.cache = {} 
        
        self.ctx_menu = app_commands.ContextMenu(
            name="🔍 Аналіз Активності",
            callback=self.check_activity_context
        )
        self.bot.tree.add_command(self.ctx_menu)
        self.daily_tracker_report.start()

    async def cog_unload(self):
        self.daily_tracker_report.cancel()
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=KYIV_TZ))
    async def daily_tracker_report(self):
        print("[ActivityScanner] Запуск щоденного звіту о 00:00...")
        names = await get_all_tracked_players()
        if not names:
            return
            
        # Знаходимо канал для звітів (можемо використати log channel або reports channel)
        from utils.data_handler import get_settings
        import json
        
        bot_settings = get_settings()
        report_ch_id = bot_settings.get("reportsChannelId")
        if not report_ch_id:
            try:
                with open('config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    report_ch_id = config.get("LOG_CHANNEL_ID")
            except:
                pass
                
        if not report_ch_id:
            print("[ActivityScanner] Не знайдено канал для звіту.")
            return
            
        channel = self.bot.get_channel(int(report_ch_id))
        if not channel:
            try:
                channel = await self.bot.fetch_channel(int(report_ch_id))
            except:
                return
                
        # Генеруємо звіт
        user_data = get_data()
        pubg_to_discord = {v.get('pubgNickname', '').lower(): v.get('userId') for k, v in user_data.items() if v.get('pubgNickname')}
        now_ts = time.time()
        
        # Отримуємо гравців батчами (по 10 штук за раз)
        for i in range(0, len(names), 10):
            batch = names[i:i+10]
            batch_data = await get_players_batch(batch)
            
            for p_data in batch_data:
                p_name = p_data.get('attributes', {}).get('name')
                if p_name:
                    last_match_str = await get_latest_match_date(p_data)
                    self.cache[p_name] = {"date_str": last_match_str, "checked_at": now_ts, "exists": True}
                    await asyncio.sleep(0.5)
            
            for b_name in batch:
                found = any(k.lower() == b_name.lower() for k in self.cache)
                if not found:
                    self.cache[b_name] = {"date_str": None, "checked_at": now_ts, "exists": False}
                    
        linked_report = []
        unlinked_report = []
        
        for name in names:
            discord_id = pubg_to_discord.get(name.lower())
            cache_key = next((k for k in self.cache if k.lower() == name.lower()), name)
            cache_data = self.cache.get(cache_key)
            
            if not cache_data or not cache_data.get('exists'):
                info_str = f"**{name}**: Гравець не знайдений"
                (linked_report if discord_id else unlinked_report).append((name, info_str, -1))
                continue
                
            last_match_str = cache_data.get('date_str')
            if last_match_str:
                last_match_date = datetime.datetime.strptime(last_match_str, "%Y-%m-%dT%H:%M:%SZ")
                diff = datetime.datetime.utcnow() - last_match_date
                days = diff.days
                time_str = "Сьогодні" if days == 0 else "Вчора" if days == 1 else f"{days} днів тому"
                info_str = f"**{name}**: {time_str}"
                sort_key = days
            else:
                info_str = f"**{name}**: Немає матчів"
                sort_key = 9999
                
            if discord_id:
                info_str += f" (<@{discord_id}>)"
                linked_report.append((name, info_str, sort_key))
            else:
                unlinked_report.append((name, info_str, sort_key))
            
        linked_report.sort(key=lambda x: x[2], reverse=True)
        unlinked_report.sort(key=lambda x: x[2], reverse=True)
        
        embed = discord.Embed(title="📊 Щоденний звіт про активність (00:00)", color=discord.Color.purple())
        if linked_report:
            embed.add_field(name="🔗 З прив'язаним Discord", value="\n".join([x[1] for x in linked_report])[:1024], inline=False)
        if unlinked_report:
            embed.add_field(name="👤 Без прив'язаного Discord", value="\n".join([x[1] for x in unlinked_report])[:1024], inline=False)
        if not linked_report and not unlinked_report:
            embed.description = "Немає даних для відображення."
            
        view = UntrackView(self.bot, names)
        msg = await channel.send(embed=embed, view=view)
        
        if len(names) > 25:
            for i in range(25, len(names), 25):
                chunk = names[i:i+25]
                chunk_view = UntrackView(self.bot, chunk)
                await channel.send("Додаткові гравці:", view=chunk_view)

    @app_commands.command(name="check_activity", description="Перевірити активність гравців (до 5 скріншотів)")
    async def check_activity(self, interaction: discord.Interaction, image1: discord.Attachment, image2: discord.Attachment=None, image3: discord.Attachment=None, image4: discord.Attachment=None, image5: discord.Attachment=None):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=False)
        except discord.HTTPException:
            pass
        
        images = [img for img in [image1, image2, image3, image4, image5] if img is not None]
        
        if not images:
            return await interaction.followup.send("❌ Будь ласка, завантажте хоча б одне зображення.")

        await self.process_images(interaction, images)

    async def check_activity_context(self, interaction: discord.Interaction, message: discord.Message):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=False)
        except discord.HTTPException:
            pass # Якщо не встигли за 3 секунди, ігноруємо помилку і відправимо в канал
        
        images = [attachment for attachment in message.attachments if attachment.content_type and attachment.content_type.startswith('image/')]
        
        if not images:
            try:
                return await interaction.followup.send("❌ У цьому повідомленні немає зображень для аналізу.")
            except:
                return await interaction.channel.send(f"{interaction.user.mention} ❌ У цьому повідомленні немає зображень для аналізу.")
            
        await self.process_images(interaction, images)

    @commands.command(name="check", aliases=["check_activity", "аналіз"])
    async def check_activity_prefix(self, ctx):
        images = [attachment for attachment in ctx.message.attachments if attachment.content_type and attachment.content_type.startswith('image/')]
        
        if not images:
            return await ctx.send("❌ Будь ласка, прикріпіть фотографії прямо до цього повідомлення (можна кинути групу фото і додати коментар `!check`).")
            
        await self.process_images(ctx, images)

    async def process_images(self, context, images: list):
        is_interaction = isinstance(context, discord.Interaction)
        user = context.user if is_interaction else context.author
        channel = context.channel

        try:
            all_names = []
            
            if is_interaction:
                try:
                    status_msg = await context.followup.send("⏳ Зчитую текст із зображень...", wait=True)
                except:
                    status_msg = await channel.send(f"{user.mention} ⏳ Зчитую текст із зображень...")
            else:
                status_msg = await context.send("⏳ Зчитую текст із зображень...")
            
            # Використовуємо Gemini 2.5 Flash-Lite для OCR, щоб уникнути жорсткого ліміту в 20 запитів
            model = genai.GenerativeModel('gemini-2.5-flash-lite')
            prompt = "Extract all player names from ALL the provided images. Return ONLY the names, each on a new line. Only return strings that match a standard PUBG username (letters, numbers, underscores, hyphens, max 16 chars). Exclude any extraneous text or interface elements. Combine all names into one list without duplicates."
            
            pil_images = []
            for img_attachment in images:
                if not img_attachment.content_type or not img_attachment.content_type.startswith('image/'):
                    continue
                
                img_bytes = await img_attachment.read()
                img = Image.open(io.BytesIO(img_bytes))
                pil_images.append(img)
                
            if pil_images:
                # Відправляємо всі фотографії в одному запиті, щоб не перевищити ліміт (5 запитів на хвилину)
                content_payload = pil_images + [prompt]
                response = await asyncio.to_thread(model.generate_content, content_payload)
                
                text = response.text
                for line in text.split('\n'):
                    name = line.strip()
                    if re.match(r'^[A-Za-z0-9_-]{4,16}$', name):
                        all_names.append(name)
            
            names = list(set(all_names)) # Прибираємо дублікати
            
            if not names:
                return await status_msg.edit(content=f"{user.mention} ❌ Не вдалося знайти жодного дійсного імені на зображеннях.")
            
            # Додаємо знайдені нікнейми до бази відстеження
            for name in names:
                await add_tracked_player(name)
                
            try:
                await status_msg.edit(content=f"⏳ Знайдено унікальних гравців: {len(names)}. Перевіряю активність (з кешуванням)... Це може зайняти певний час через ліміти API.")
            except discord.HTTPException:
                pass # Ігноруємо помилку, якщо токен вже закінчився
            
            user_data = get_data()
            pubg_to_discord = {v.get('pubgNickname', '').lower(): v.get('userId') for k, v in user_data.items() if v.get('pubgNickname')}
            
            now_ts = time.time()
            CACHE_LIFETIME = 6 * 3600 # Кешуємо дані на 6 годин
            
            # Визначаємо, кого треба отримати з API
            names_to_fetch = []
            for n in names:
                if n not in self.cache or (now_ts - self.cache[n]['checked_at'] > CACHE_LIFETIME):
                    names_to_fetch.append(n)
            
            # Отримуємо гравців батчами (по 10 штук за раз)
            player_objects = {}
            for i in range(0, len(names_to_fetch), 10):
                batch = names_to_fetch[i:i+10]
                batch_data = await get_players_batch(batch)
                
                for p_data in batch_data:
                    p_name = p_data.get('attributes', {}).get('name')
                    if p_name:
                        # Ми отримуємо лише загальну інфу, дату останнього матчу треба діставати окремо
                        last_match_str = await get_latest_match_date(p_data)
                        
                        # Зберігаємо в кеш
                        self.cache[p_name] = {
                            "date_str": last_match_str,
                            "checked_at": now_ts,
                            "exists": True
                        }
                        # Невелика затримка після запиту матчу, бо це окремі API-дзвінки
                        await asyncio.sleep(0.5)
                
                # Записуємо тих, кого API не знайшов
                for b_name in batch:
                    # Шукаємо case-insensitive
                    found = any(k.lower() == b_name.lower() for k in self.cache)
                    if not found:
                        self.cache[b_name] = {
                            "date_str": None,
                            "checked_at": now_ts,
                            "exists": False
                        }
            
            # Дані для звіту
            linked_report = []
            unlinked_report = []
            
            for name in names:
                discord_id = pubg_to_discord.get(name.lower())
                
                # Знаходимо кеш-запис (незалежно від регістру)
                cache_key = next((k for k in self.cache if k.lower() == name.lower()), name)
                cache_data = self.cache.get(cache_key)
                
                if not cache_data or not cache_data.get('exists'):
                    info_str = f"**{name}**: Гравець не знайдений"
                    if discord_id:
                        linked_report.append((name, info_str, -1))
                    else:
                        unlinked_report.append((name, info_str, -1))
                    continue
                    
                last_match_str = cache_data.get('date_str')
                
                if last_match_str:
                    last_match_date = datetime.datetime.strptime(last_match_str, "%Y-%m-%dT%H:%M:%SZ")
                    now = datetime.datetime.utcnow()
                    diff = now - last_match_date
                    days = diff.days
                    
                    if days == 0:
                        time_str = "Сьогодні"
                    elif days == 1:
                        time_str = "Вчора"
                    else:
                        time_str = f"{days} днів тому"
                        
                    info_str = f"**{name}**: {time_str}"
                    sort_key = days
                else:
                    info_str = f"**{name}**: Немає матчів"
                    sort_key = 9999
                    
                if discord_id:
                    info_str += f" (<@{discord_id}>)"
                    linked_report.append((name, info_str, sort_key))
                else:
                    unlinked_report.append((name, info_str, sort_key))
                
            # Сортування: ті що довше не грали - перші
            linked_report.sort(key=lambda x: x[2], reverse=True)
            unlinked_report.sort(key=lambda x: x[2], reverse=True)
            
            # Формуємо Embed
            embed = discord.Embed(title="📊 Звіт про активність гравців", color=discord.Color.blue())
            
            if linked_report:
                linked_text = "\n".join([x[1] for x in linked_report])
                if len(linked_text) > 1024:
                    linked_text = linked_text[:1020] + "..."
                embed.add_field(name="🔗 З прив'язаним Discord", value=linked_text, inline=False)
                
            if unlinked_report:
                unlinked_text = "\n".join([x[1] for x in unlinked_report])
                if len(unlinked_text) > 1024:
                    unlinked_text = unlinked_text[:1020] + "..."
                embed.add_field(name="👤 Без прив'язаного Discord", value=unlinked_text, inline=False)
                
            if not linked_report and not unlinked_report:
                embed.description = "Немає даних для відображення."
                
            view = UntrackView(self.bot, names)
                
            try:
                await status_msg.edit(content=None, embed=embed, view=view)
            except discord.HTTPException:
                await channel.send(content=f"{user.mention}, звіт готовий:", embed=embed, view=view)
            
            # Якщо гравців більше 25, створюємо додаткові повідомлення з кнопками
            if len(names) > 25:
                for i in range(25, len(names), 25):
                    chunk = names[i:i+25]
                    chunk_view = UntrackView(self.bot, chunk)
                    if is_interaction:
                        await context.followup.send("Додаткові гравці:", view=chunk_view, ephemeral=True)
                    else:
                        await channel.send("Додаткові гравці:", view=chunk_view)
            
        except Exception as e:
            try:
                if 'status_msg' in locals():
                    await status_msg.edit(content=f"❌ Сталася помилка при обробці: {e}")
                elif is_interaction:
                    await context.followup.send(f"❌ Сталася помилка при обробці: {e}")
                else:
                    await context.send(f"❌ Сталася помилка при обробці: {e}")
            except:
                await channel.send(f"{user.mention} ❌ Сталася помилка при обробці: {e}")

async def setup(bot):
    await bot.add_cog(ActivityScanner(bot))
    print("Loaded extension: activity_scanner")
