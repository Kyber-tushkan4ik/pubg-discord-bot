import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import aiohttp
import asyncio
import json
import os
from utils.data_handler import DB_FILE

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

class NewsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = int(CONFIG.get("NEWS_CHANNEL_ID", 1297667294738124840))
        self.news_url = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=578080&count=8&maxlength=300&feeds=steam_community_announcements"
        self.session = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.pubg_monitor.start()

    async def cog_unload(self):
        self.pubg_monitor.cancel()
        if self.session:
            await self.session.close()

    def cog_unload(self):
        self.pubg_monitor.cancel()

    async def is_news_saved(self, news_id):
        def _is_saved():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM news_feed WHERE id = ?", (str(news_id),))
            result = cursor.fetchone()
            conn.close()
            return result is not None
        return await asyncio.to_thread(_is_saved)

    async def save_news(self, news_id, title, url, date, type_str):
        def _save():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO news_feed (id, title, url, date, type)
                VALUES (?, ?, ?, ?, ?)
            ''', (str(news_id), title, url, date, type_str))
            conn.commit()
            conn.close()
        await asyncio.to_thread(_save)

    @tasks.loop(minutes=30)
    async def pubg_monitor(self):
        await self.bot.wait_until_ready()
        
        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            return  # Канал не знайдено, або бот не має доступу
            
        try:
            # Спочатку перевіримо останні повідомлення в каналі, щоб не дублювати
            history_titles = set()
            try:
                async for msg in channel.history(limit=20):
                    if msg.author == self.bot.user and msg.embeds:
                        history_titles.add(msg.embeds[0].title)
            except Exception as e:
                print(f"[NewsMonitor] Не вдалося зчитати історію чату: {e}")

            if self.session is None:
                self.session = aiohttp.ClientSession()

            async with self.session.get(self.news_url) as response:
                if response.status == 200:
                    data = await response.json()
                    news_items = data.get("appnews", {}).get("newsitems", [])
                    
                    # Йдемо від старішої до новішої (щоб зберігати порядок, реверсуємо)
                    for item in reversed(news_items):
                        news_id = item.get("gid")
                        is_saved = await self.is_news_saved(news_id)
                        if not is_saved:
                            title = item.get("title", "")
                            url = item.get("url", "").strip()
                            if not url.startswith("http"):
                                url = "https://store.steampowered.com/news/app/578080/"
                            contents = item.get("contents", "")
                            date = item.get("date")
                            
                            # Перевіряємо історію каналу, щоб уникнути дубляжів при збої бази даних
                            if title in history_titles:
                                await self.save_news(news_id, title, url, date, item.get("feedname"))
                                continue
                            
                            # Ігноруємо щотижневі звіти про бани та інші спам-пости
                            if "bans notice" in title.lower() or "weekly ban" in title.lower():
                                await self.save_news(news_id, title, url, date, item.get("feedname"))
                                continue
                            
                            # Зберігаємо в базі
                            await self.save_news(news_id, title, url, date, item.get("feedname"))
                            
                            # Відправляємо в канал
                            embed = discord.Embed(
                                title=title,
                                url=url,
                                description=f"{contents}\n\n[Читати повністю...]({url})",
                                color=0xff9900
                            )
                            embed.set_author(name="PUBG: BATTLEGROUNDS Новини", icon_url="https://steamuserimages-a.akamaihd.net/ugc/2000216766347514930/AB13B4AD977119DDAFD9FD52A127CCDC6788CC25/")
                            embed.set_footer(text="Steam Community News")
                            
                            await channel.send(embed=embed)
        except Exception as e:
            print(f"[NewsMonitor] Помилка: {e}")

    @app_commands.command(name="news", description="Отримати останні новини PUBG")
    async def get_news(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            if self.session is None:
                self.session = aiohttp.ClientSession()

            async with self.session.get(self.news_url) as response:
                if response.status == 200:
                    data = await response.json()
                    items = data.get("appnews", {}).get("newsitems", [])
                    
                    # Відфільтруємо бани для ручної команди теж
                    valid_items = [i for i in items if "bans notice" not in i.get("title", "").lower() and "weekly ban" not in i.get("title", "").lower()]
                    
                    if not valid_items:
                        await interaction.followup.send("❌ Немає актуальних новин або Steam API недоступний.")
                        return
                        
                    item = valid_items[0]
                    title = item.get("title", "")
                    url = item.get("url", "").strip()
                    if not url.startswith("http"):
                        url = "https://store.steampowered.com/news/app/578080/"
                    contents = item.get("contents", "")
                    
                    embed = discord.Embed(
                        title=title,
                        url=url,
                        description=f"{contents}\n\n[Читати повністю...]({url})",
                        color=0xff9900
                    )
                    embed.set_author(name="Останній патч / Новина", icon_url="https://steamuserimages-a.akamaihd.net/ugc/2000216766347514930/AB13B4AD977119DDAFD9FD52A127CCDC6788CC25/")
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send("❌ Steam API повернуло помилку.")
        except Exception as e:
            await interaction.followup.send(f"❌ Помилка з'єднання: {e}")

async def setup(bot):
    await bot.add_cog(NewsCog(bot))
    print("Loaded extension: news")
