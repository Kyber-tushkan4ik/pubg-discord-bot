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
from utils.data_handler import get_data

class ActivityScanner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        # Кеш для зменшення запитів до API (зберігається в пам'яті до рестарту)
        self.cache = {} 

    @app_commands.command(name="check_activity", description="Перевірити активність гравців (до 5 скріншотів)")
    async def check_activity(self, interaction: discord.Interaction, image1: discord.Attachment, image2: discord.Attachment=None, image3: discord.Attachment=None, image4: discord.Attachment=None, image5: discord.Attachment=None):
        await interaction.response.defer(ephemeral=False)
        
        images = [img for img in [image1, image2, image3, image4, image5] if img is not None]
        
        if not images:
            return await interaction.followup.send("❌ Будь ласка, завантажте хоча б одне зображення.")

        try:
            all_names = []
            
            status_msg = await interaction.followup.send("⏳ Зчитую текст із зображень...", wait=True)
            
            # Використовуємо Gemini для OCR
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            prompt = "Extract all player names from this image. Return ONLY the names, each on a new line. Only return strings that match a standard PUBG username (letters, numbers, underscores, hyphens, max 16 chars). Exclude any extraneous text or interface elements."
            
            for img_attachment in images:
                if not img_attachment.content_type or not img_attachment.content_type.startswith('image/'):
                    continue
                
                img_bytes = await img_attachment.read()
                img = Image.open(io.BytesIO(img_bytes))
                
                response = await asyncio.to_thread(model.generate_content, [img, prompt])
                
                text = response.text
                for line in text.split('\n'):
                    name = line.strip()
                    if re.match(r'^[A-Za-z0-9_-]{4,16}$', name):
                        all_names.append(name)
            
            names = list(set(all_names)) # Прибираємо дублікати
            
            if not names:
                return await status_msg.edit(content="❌ Не вдалося знайти жодного дійсного імені на зображеннях.")
                
            await status_msg.edit(content=f"⏳ Знайдено унікальних гравців: {len(names)}. Перевіряю активність (з кешуванням)...")
            
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
                
            await status_msg.edit(content=None, embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Сталася помилка при обробці: {e}")

async def setup(bot):
    await bot.add_cog(ActivityScanner(bot))
    print("Loaded extension: activity_scanner")
