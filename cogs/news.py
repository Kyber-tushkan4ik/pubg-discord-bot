import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import aiohttp
from utils.data_handler import DB_FILE

class NewsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = 1297667294738124840
        self.news_url = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=578080&count=8&maxlength=300&feeds=steam_community_announcements"
        self.pubg_monitor.start()

    def cog_unload(self):
        self.pubg_monitor.cancel()

    def is_news_saved(self, news_id):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM news_feed WHERE id = ?", (str(news_id),))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def save_news(self, news_id, title, url, date, type):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO news_feed (id, title, url, date, type)
            VALUES (?, ?, ?, ?, ?)
        ''', (str(news_id), title, url, date, type))
        conn.commit()
        conn.close()

    @tasks.loop(minutes=30)
    async def pubg_monitor(self):
        await self.bot.wait_until_ready()
        
        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            return  # Канал не знайдено, або бот не має доступу
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.news_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        news_items = data.get("appnews", {}).get("newsitems", [])
                        
                        # Йдемо від старішої до новішої (щоб зберігати порядок, реверсуємо)
                        for item in reversed(news_items):
                            news_id = item.get("gid")
                            if not self.is_news_saved(news_id):
                                title = item.get("title", "")
                                url = item.get("url", "").strip()
                                if not url.startswith("http"):
                                    url = "https://store.steampowered.com/news/app/578080/"
                                contents = item.get("contents", "")
                                date = item.get("date")
                                
                                # Ігноруємо щотижневі звіти про бани та інші спам-пости
                                if "bans notice" in title.lower() or "weekly ban" in title.lower():
                                    self.save_news(news_id, title, url, date, item.get("feedname"))
                                    continue
                                
                                # Зберігаємо в базі
                                self.save_news(news_id, title, url, date, item.get("feedname"))
                                
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
            async with aiohttp.ClientSession() as session:
                async with session.get(self.news_url) as response:
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
