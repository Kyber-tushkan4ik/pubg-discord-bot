import discord
from discord.ext import commands
from discord import app_commands
import time

from utils.data_handler import get_balance, add_balance, add_message_stat

# Внутрішня пам'ять для кулдауну отримання монет за повідомлення
message_cooldowns = {}
COOLDOWN_MS = 60000 # 1 повідомлення в хвилину дає BP

class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Переглянути свій профіль та баланс BP")
    async def profile(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        balance = get_balance(target.id)
        
        embed = discord.Embed(
            title=f"Профіль гравця: {target.display_name}",
            color=0xF1C40F
        )
        embed.set_thumbnail(url=target.display_avatar.url if target.display_avatar else target.default_avatar.url)
        embed.add_field(name="💰 Баланс BP (Battle Points)", value=f"**{balance}** BP", inline=False)
        
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        
        user_id = str(message.author.id)
        now = int(time.time() * 1000)
        
        # Додаємо статистику повідомлень для тижневої аналітики
        add_message_stat(user_id)
        
        # Перевірка кулдауну для нарахування BP
        last_reward = message_cooldowns.get(user_id, 0)
        if now - last_reward >= COOLDOWN_MS:
            message_cooldowns[user_id] = now
            add_balance(user_id, 1) # 1 BP за повідомлення

async def setup(bot):
    await bot.add_cog(EconomyCog(bot))
    print("Loaded extension: economy")
