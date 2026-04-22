import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import random

class MusicStatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_path = os.path.join(os.path.dirname(__file__), '../config.json')
        self.current_index = 0
        self.songs = []
        self.playlist_url = ""
        self.load_config()
        self.update_status.start()

    def load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.songs = config.get("MUSIC_SONGS", [])
                self.playlist_url = config.get("MUSIC_PLAYLIST_URL", "")
            print(f"[MUSIC] Завантажено {len(self.songs)} пісень для статусу.")
        except Exception as e:
            print(f"[ERROR MUSIC] Не вдалося завантажити музичний конфіг: {e}")

    def cog_unload(self):
        self.update_status.cancel()

    @tasks.loop(minutes=5)
    async def update_status(self):
        if not self.songs:
            return

        song = self.songs[self.current_index]
        try:
            # Встановлюємо статус "Слухає [Пісня]"
            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name=song
            )
            await self.bot.change_presence(activity=activity)
            # print(f"[MUSIC STATUS] Змінено статус на: {song}")
            
            # Переходимо до наступної пісні (по кругу)
            self.current_index = (self.current_index + 1) % len(self.songs)
        except Exception as e:
            print(f"[ERROR MUSIC STATUS] Помилка оновлення статусу: {e}")

    @update_status.before_loop
    async def before_update_status(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="playlist", description="Отримати посилання на плейлист YouTube Music")
    async def playlist(self, interaction: discord.Interaction):
        if not self.playlist_url:
            await interaction.response.send_message("❌ Посилання на плейлист не налаштовано.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎵 Плейлист YouTube Music",
            description="Ось посилання на музичний плейлист, який зараз «слухає» бот:",
            color=0xFF0000
        )
        embed.add_field(name="🔗 Посилання", value=f"[Відкрити в YouTube Music]({self.playlist_url})")
        embed.set_footer(text="Гарного прослуховування! 🎧")
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(MusicStatusCog(bot))
    print("Loaded extension: music_status")
