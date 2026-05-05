import discord
from discord.ext import commands
from discord import app_commands

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Створити тікет", style=discord.ButtonStyle.primary, custom_id="ticket_create_btn", emoji="🎫")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        # Перевірка чи вже є тікет від цього користувача
        ticket_name = f"тікет-{interaction.user.name.lower()}"
        existing_channel = discord.utils.get(guild.channels, name=ticket_name)
        if existing_channel:
            await interaction.followup.send(f"У вас вже є відкритий тікет: {existing_channel.mention}", ephemeral=True)
            return

        # Налаштування прав
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, manage_messages=True, manage_permissions=True)
        }

        # Додавання прав для ролей адміністрації
        roles_to_mention = ["Біг босс 1488 лвл", "Адміністратор", "Модератор"]
        found_roles = []
        for r_name in roles_to_mention:
            r = discord.utils.get(guild.roles, name=r_name)
            if r:
                found_roles.append(r)
                overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
        
        # Створення каналу
        try:
            ticket_channel = await guild.create_text_channel(name=ticket_name, overwrites=overwrites)
            
            embed = discord.Embed(
                title="🎫 Новий Тікет",
                description="Цей канал створено для того, аби ви могли звернутись до підтримки з адмінами.\nБудь ласка, детально опишіть вашу проблему або запитання нижче.",
                color=0x3498DB
            )
            
            mention_text = f"{interaction.user.mention}"
            for r in found_roles:
                mention_text += f" {r.mention}"

            view = TicketCloseView()
            await ticket_channel.send(content=mention_text, embed=embed, view=view)
            
            await interaction.followup.send(f"Ваш тікет створено: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Помилка створення тікету: {e}", ephemeral=True)

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Закрити тікет", style=discord.ButtonStyle.danger, custom_id="ticket_close_btn", emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Тікет буде закрито через 5 секунд...")
        import asyncio
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except:
            pass

class TicketsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(TicketView())
        self.bot.add_view(TicketCloseView())

    @app_commands.command(name="ticket_setup", description="[Адмін] Встановити меню створення тікетів у поточному каналі")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_setup(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📞 Служба підтримки / Зв'язок з Адміністрацією",
            description="Потрібна допомога? Маєте питання, скаргу чи пропозицію?\n\nНатисніть кнопку нижче, щоб створити приватний канал (тікет) для спілкування з адміністрацією.",
            color=0x2ECC71
        )
        embed.set_footer(text="Будь ласка, не створюйте тікети без причини.")
        
        await interaction.channel.send(embed=embed, view=TicketView())
        await interaction.response.send_message("Меню тікетів встановлено!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TicketsCog(bot))
    print("Loaded extension: tickets")
