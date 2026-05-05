import discord
from discord.ext import commands
from discord import app_commands
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

# Беремо назви карт з конфігу (тільки унікальні значення)
MAP_NAMES = list(set(CONFIG.get("MAP_NAMES", {}).values()))
if not MAP_NAMES:
    MAP_NAMES = ["Ерангель", "Мірамар", "Санок", "Вікенді", "Таего", "Дестон", "Рондо", "Парамо", "Каракін"]

class RoleSelect(discord.ui.Select):
    def __init__(self):
        options = []
        for map_name in MAP_NAMES[:25]: # Discord limit is 25
            options.append(discord.SelectOption(label=map_name, description=f"Грати на карті {map_name}"))
            
        super().__init__(
            placeholder="Оберіть улюблені карти...",
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id="role_select_maps"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        
        added_roles = []
        removed_roles = []
        
        # Обробляємо вибір
        for opt in self.options:
            role_name = opt.label
            role = discord.utils.get(guild.roles, name=role_name)
            
            # Створюємо роль, якщо її немає
            if not role:
                try:
                    role = await guild.create_role(name=role_name, mentionable=True)
                except:
                    continue
            
            if role_name in self.values:
                if role not in member.roles:
                    await member.add_roles(role)
                    added_roles.append(role_name)
            else:
                if role in member.roles:
                    await member.remove_roles(role)
                    removed_roles.append(role_name)
                    
        response_msg = "✅ **Ваші ролі оновлено!**\n"
        if added_roles:
            response_msg += f"➕ Додано: {', '.join(added_roles)}\n"
        if removed_roles:
            response_msg += f"➖ Видалено: {', '.join(removed_roles)}\n"
        if not added_roles and not removed_roles:
            response_msg += "Змін не відбулося."
            
        await interaction.followup.send(response_msg, ephemeral=True)


class RoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoleSelect())

class RolesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(RoleView())

    @app_commands.command(name="roles_setup", description="[Адмін] Встановити меню вибору ролей")
    @app_commands.checks.has_permissions(administrator=True)
    async def roles_setup(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🗺️ Вибір улюблених карт",
            description="Виберіть зі списку нижче карти, на яких ви любите грати.\nЦе видасть вам відповідну роль, і інші гравці зможуть вас тегати, коли збиратимуть паті на цю карту!",
            color=0xE67E22
        )
        await interaction.channel.send(embed=embed, view=RoleView())
        await interaction.response.send_message("Меню ролей встановлено!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RolesCog(bot))
    print("Loaded extension: roles")
