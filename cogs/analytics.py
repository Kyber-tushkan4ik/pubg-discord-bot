import discord
from discord.ext import commands, tasks
import json
import os
import datetime

from utils.data_handler import get_top_activity, reset_weekly_activity
from utils.helpers import create_log

class AnalyticsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.weekly_analytics_loop.start()

    def cog_unload(self):
        self.weekly_analytics_loop.cancel()

    @tasks.loop(hours=1) # Перевіряємо щогодини
    async def weekly_analytics_loop(self):
        from utils.data_handler import get_settings, save_settings
        settings = get_settings()
        last_analytics_str = settings.get("lastAnalyticsDate", "")
        today = datetime.datetime.now()
        
        if last_analytics_str:
            try:
                last_date = datetime.datetime.strptime(last_analytics_str, "%Y-%m-%d")
                if (today - last_date).days < 7:
                    return # Ще не пройшло 7 днів
            except ValueError:
                pass
                
        # Відправляємо статистику власнику
        owner_id = 776154533742641174
        user = await self.bot.fetch_user(owner_id)
        if not user:
            return

        top_data = get_top_activity()
        if not top_data:
            # Зберігаємо дату навіть якщо немає даних, щоб не спамило
            settings["lastAnalyticsDate"] = today.strftime("%Y-%m-%d")
            await save_settings()
            return

        # Сортування: 1) за повідомленнями, 2) за голосом
        top_msgs = sorted(top_data, key=lambda x: x[1], reverse=True)[:10]
        top_voice = sorted(top_data, key=lambda x: x[2], reverse=True)[:10]

        embed = discord.Embed(
            title="📊 Тижнева Аналітика Активності Сервера",
            description=f"Звіт за тиждень до {datetime.datetime.now().strftime('%d.%m.%Y')}",
            color=0x9B59B6
        )

        msg_text = ""
        for i, (uid, msgs, voice) in enumerate(top_msgs):
            if msgs > 0:
                msg_text += f"**{i+1}.** <@{uid}> — {msgs} пов.\n"
        if not msg_text:
            msg_text = "Немає активних в чаті."
        embed.add_field(name="💬 Топ за повідомленнями", value=msg_text, inline=False)

        voice_text = ""
        for i, (uid, msgs, voice) in enumerate(top_voice):
            if voice > 0:
                hours = voice / 3600000
                voice_text += f"**{i+1}.** <@{uid}> — {hours:.1f} год.\n"
        if not voice_text:
            voice_text = "Немає активних в голосі."
        embed.add_field(name="🎙️ Топ за голосовими", value=voice_text, inline=False)

        try:
            await user.send(embed=embed)
            create_log("[ANALYTICS] Тижневий звіт надіслано.")
        except Exception as e:
            create_log(f"[ANALYTICS ERROR] Failed to send report: {e}")

        # Скидаємо статистику
        reset_weekly_activity()
        
        # Зберігаємо дату
        settings["lastAnalyticsDate"] = today.strftime("%Y-%m-%d")
        await save_settings()

    @weekly_analytics_loop.before_loop
    async def before_weekly_analytics(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(AnalyticsCog(bot))
    print("Loaded extension: analytics")
