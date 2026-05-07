import discord
from discord import app_commands
from discord.ext import commands
import time

from utils.data_handler import add_idea, get_all_ideas, delete_idea, clear_all_ideas
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
    def __init__(self, ideas):
        super().__init__(timeout=300)
        self.ideas = ideas
        self.current_index = 0
        self.update_buttons()

    def update_buttons(self):
        # Оновлюємо стан кнопок залежно від того, чи є ще ідеї
        has_ideas = len(self.ideas) > 0
        self.accept_btn.disabled = not has_ideas
        self.reject_btn.disabled = not has_ideas
        self.next_btn.disabled = len(self.ideas) <= 1
        
        # Кнопка очищення активна завжди, якщо є хоч одна ідея (або навіть якщо 0, просто для зручності)
        self.clear_btn.disabled = not has_ideas

    def get_current_embed(self):
        if not self.ideas:
            return discord.Embed(
                title="📭 Немає ідей",
                description="Всі ідеї розглянуті або база порожня.",
                color=0x95a5a6
            )
            
        idea = self.ideas[self.current_index]
        idea_id, user_id, username, idea_text, timestamp = idea
        
        embed = discord.Embed(
            title=f"💡 Ідея #{idea_id}",
            description=f"**Від:** {username} (<@{user_id}>)\n**Дата:** <t:{int(timestamp / 1000)}:R>\n\n**Текст:**\n{idea_text}",
            color=0xf1c40f
        )
        embed.set_footer(text=f"Ідея {self.current_index + 1} з {len(self.ideas)}")
        return embed

    @discord.ui.button(label="Прийняти", style=discord.ButtonStyle.success, custom_id="idea_accept", emoji="✅")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        idea = self.ideas[self.current_index]
        idea_id = idea[0]
        
        # Видаляємо з бази, так як прийняли
        await delete_idea(idea_id)
        self.ideas.pop(self.current_index)
        
        if self.current_index >= len(self.ideas) and len(self.ideas) > 0:
            self.current_index = 0
            
        self.update_buttons()
        
        # Повідомляємо адміна
        await interaction.response.send_message("✅ Ідею відзначено як прийняту (вона видалена з черги).", ephemeral=True)
        await interaction.message.edit(embed=self.get_current_embed(), view=self)

    @discord.ui.button(label="Відхилити", style=discord.ButtonStyle.danger, custom_id="idea_reject", emoji="❌")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        idea = self.ideas[self.current_index]
        idea_id = idea[0]
        
        # Видаляємо з бази
        await delete_idea(idea_id)
        self.ideas.pop(self.current_index)
        
        if self.current_index >= len(self.ideas) and len(self.ideas) > 0:
            self.current_index = 0
            
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    @discord.ui.button(label="Наступна", style=discord.ButtonStyle.secondary, custom_id="idea_next", emoji="➡️")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index = (self.current_index + 1) % len(self.ideas)
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    @discord.ui.button(label="Видалити всі нерозглянуті", style=discord.ButtonStyle.danger, custom_id="idea_clear_all", emoji="🧹", row=1)
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await clear_all_ideas()
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
    @is_admin()
    async def ideas_review_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        ideas = await get_all_ideas()
        view = AdminIdeasReviewView(ideas)
        embed = view.get_current_embed()
        
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="setup_ideas_panel", description="Створити панель для прийому ідей в поточному каналі (Адмін)")
    @is_admin()
    async def setup_ideas_panel_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="💡 Скринька ідей та пропозицій",
            description=(
                "Маєте ідею, як покращити бота чи клан? Знайшли баг або хочете запропонувати нову фічу?\n\n"
                "Натисніть кнопку нижче, щоб відправити свою пропозицію напряму адміністрації.\n"
                "Всі ідеї ретельно розглядаються в кінці тижня!"
            ),
            color=0x3498db
        )
        await interaction.channel.send(embed=embed, view=IdeaPanelView())
        await interaction.response.send_message("✅ Панель успішно створена в цьому каналі!", ephemeral=True)

async def setup(bot):
    bot.add_view(IdeaPanelView())
    await bot.add_cog(IdeasCog(bot))
    print("Loaded extension: ideas")
