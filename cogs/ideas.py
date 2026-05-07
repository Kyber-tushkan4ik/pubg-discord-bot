import discord
from discord import app_commands
from discord.ext import commands
import time

import time

from utils.data_handler import add_idea, get_ideas_by_status, update_idea_status, delete_idea, clear_all_ideas, get_settings
from utils.helpers import is_admin

class IdeaModal(discord.ui.Modal, title="Запропонувати ідею"):
    idea_input = discord.ui.TextInput(
        label="Ваша ідея для бота",
        style=discord.TextStyle.long,
        placeholder="Опишіть, що б ви хотіли додати або змінити...",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        idea_text = self.idea_input.value
        user_id = str(interaction.user.id)
        username = interaction.user.display_name
        
        await add_idea(user_id, username, idea_text)
        
        embed = discord.Embed(
            title="💡 Ідею надіслано!",
            description="Дякуємо! Ваша ідея збережена. Адміністратор розгляне її в кінці тижня.",
            color=0x2ecc71
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class AdminIdeasReviewView(discord.ui.View):
    def __init__(self, ideas, status='pending'):
        super().__init__(timeout=300)
        self.ideas = list(ideas)
        self.current_index = 0
        self.status = status
        self.update_buttons()

    def update_buttons(self):
        has_ideas = len(self.ideas) > 0
        self.accept_btn.disabled = not has_ideas or self.status == 'accepted'
        self.reject_btn.disabled = not has_ideas or self.status == 'rejected'
        self.next_btn.disabled = len(self.ideas) <= 1
        self.clear_btn.disabled = not has_ideas

    def get_current_embed(self):
        status_titles = {
            'pending': "📥 Нові пропозиції (На розгляді)",
            'accepted': "✅ Схвалені ідеї (Архів)",
            'rejected': "❌ Відхилені ідеї"
        }
        
        if not self.ideas:
            return discord.Embed(
                title=status_titles.get(self.status, "📭 Список порожній"),
                description=f"У категорії **{self.status}** наразі немає записів.",
                color=0x95a5a6
            )
            
        idea = self.ideas[self.current_index]
        # Обратите внимание: формат из БД теперь (id, userId, username, ideaText, timestamp, status)
        idea_id, user_id, username, idea_text, timestamp, idea_status = idea
        
        colors = {'pending': 0xf1c40f, 'accepted': 0x2ecc71, 'rejected': 0xe74c3c}
        
        embed = discord.Embed(
            title=f"💡 Ідея #{idea_id}",
            description=f"**Від:** {username} (<@{user_id}>)\n**Дата:** <t:{int(timestamp / 1000)}:R>\n**Статус:** `{idea_status}`\n\n**Текст:**\n{idea_text}",
            color=colors.get(self.status, 0x3498db)
        )
        embed.set_footer(text=f"Ідея {self.current_index + 1} з {len(self.ideas)} • Категорія: {self.status}")
        return embed

    @discord.ui.button(label="Прийняти", style=discord.ButtonStyle.success, custom_id="idea_accept", emoji="✅")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        idea = self.ideas[self.current_index]
        idea_id, user_id, username, idea_text, timestamp, _ = idea
        
        # Оновлюємо статус у базі
        await update_idea_status(idea_id, 'accepted')
        
        # Архівуємо в канал
        settings = get_settings()
        report_channel_id = settings.get("reportsChannelId")
        archive_msg = ""
        if report_channel_id:
            try:
                channel = interaction.guild.get_channel(int(report_channel_id))
                if channel:
                    embed = discord.Embed(
                        title=f"✅ Прийнята ідея від {username}",
                        description=idea_text,
                        color=0x2ecc71,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="Автор", value=f"<@{user_id}>", inline=True)
                    embed.set_footer(text=f"ID ідеї: {idea_id}")
                    await channel.send(embed=embed)
                    archive_msg = f" та архівована в канал <#{report_channel_id}>"
            except: pass

        self.ideas.pop(self.current_index)
        if self.current_index >= len(self.ideas) and len(self.ideas) > 0:
            self.current_index = 0
            
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        await interaction.followup.send(f"✅ Ідею #{idea_id} прийнято{archive_msg}.", ephemeral=True)

    @discord.ui.button(label="Відхилити", style=discord.ButtonStyle.danger, custom_id="idea_reject", emoji="❌")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        idea = self.ideas[self.current_index]
        idea_id = idea[0]
        
        await update_idea_status(idea_id, 'rejected')
        self.ideas.pop(self.current_index)
        
        if self.current_index >= len(self.ideas) and len(self.ideas) > 0:
            self.current_index = 0
            
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        await interaction.followup.send(f"❌ Ідею #{idea_id} відхилено.", ephemeral=True)

    @discord.ui.button(label="Наступна", style=discord.ButtonStyle.secondary, custom_id="idea_next", emoji="➡️")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index = (self.current_index + 1) % len(self.ideas)
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    @discord.ui.button(label="Видалити всі в цій категорії", style=discord.ButtonStyle.danger, custom_id="idea_clear_cat", emoji="🗑️", row=1)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Видаляємо тільки ті, що мають поточний статус
        for idea in self.ideas:
            await delete_idea(idea[0])
            
        self.ideas = []
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)
        await interaction.followup.send("🧹 Всі залишені ідеї були успішно видалені з бази.", ephemeral=True)

class IdeaPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Запропонувати ідею", style=discord.ButtonStyle.primary, custom_id="persistent_idea_panel_btn", emoji="💡")
    async def create_idea_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IdeaModal())

    @discord.ui.button(label="На розгляді", style=discord.ButtonStyle.secondary, custom_id="panel_view_pending", emoji="📥")
    async def view_pending(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_admin()(interaction):
            await interaction.response.send_message("❌ Ця кнопка тільки для адміністрації.", ephemeral=True)
            return
        ideas = await get_ideas_by_status('pending')
        view = AdminIdeasReviewView(ideas, status='pending')
        await interaction.response.send_message(embed=view.get_current_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="Прийняті", style=discord.ButtonStyle.secondary, custom_id="panel_view_accepted", emoji="✅")
    async def view_accepted(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_admin()(interaction):
            await interaction.response.send_message("❌ Ця кнопка тільки для адміністрації.", ephemeral=True)
            return
        ideas = await get_ideas_by_status('accepted')
        view = AdminIdeasReviewView(ideas, status='accepted')
        await interaction.response.send_message(embed=view.get_current_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="Відхилені", style=discord.ButtonStyle.secondary, custom_id="panel_view_rejected", emoji="❌")
    async def view_rejected(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_admin()(interaction):
            await interaction.response.send_message("❌ Ця кнопка тільки для адміністрації.", ephemeral=True)
            return
        ideas = await get_ideas_by_status('rejected')
        view = AdminIdeasReviewView(ideas, status='rejected')
        await interaction.response.send_message(embed=view.get_current_embed(), view=view, ephemeral=True)

class IdeasCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="idea", description="Запропонувати ідею або покращення для бота")
    @app_commands.checks.cooldown(3, 86400, key=lambda i: i.user.id) # 3 ідеї на день
    async def idea_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_modal(IdeaModal())
        
    @idea_cmd.error
    async def idea_cmd_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(f"⏳ Ви вже запропонували забагато ідей. Спробуйте знову через {int(error.retry_after/3600)} годин.", ephemeral=True)

    @app_commands.command(name="ideas_review", description="Переглянути та промодерувати запропоновані ідеї (Адмін)")
    @app_commands.describe(status="Яку категорію переглянути?")
    @app_commands.choices(status=[
        app_commands.Choice(name='На розгляді (Нові)', value='pending'),
        app_commands.Choice(name='Прийняті', value='accepted'),
        app_commands.Choice(name='Відхилені', value='rejected')
    ])
    @is_admin()
    async def ideas_review_cmd(self, interaction: discord.Interaction, status: str = 'pending'):
        await interaction.response.defer(ephemeral=True)
        
        ideas = await get_ideas_by_status(status)
        view = AdminIdeasReviewView(ideas, status=status)
        embed = view.get_current_embed()
        
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="setup_ideas_panel", description="Створити розширену панель управління ідеями (Адмін)")
    @is_admin()
    async def setup_ideas_panel_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="💡 Центр ідей та пропозицій",
            description=(
                "Вітаємо! У цьому розділі ви можете вплинути на розвиток нашого бота та клану.\n\n"
                "🔹 **Гравці:** Натисніть кнопку **💡 Запропонувати ідею**, щоб відкрити форму.\n"
                "🔸 **Адміністрація:** Використовуйте кнопки нижче для перегляду нових, прийнятих або відхилених пропозицій.\n\n"
                "*Всі ваші ідеї допомагають нам ставати кращими!*"
            ),
            color=0x3498db
        )
        embed.set_thumbnail(url="https://i.imgur.com/8N6y8Vl.png") # Приклад іконки лампочки
        await interaction.channel.send(embed=embed, view=IdeaPanelView())
        await interaction.response.send_message("✅ Розширену панель успішно створено!", ephemeral=True)

async def setup(bot):
    bot.add_view(IdeaPanelView())
    await bot.add_cog(IdeasCog(bot))
    print("Loaded extension: ideas")
