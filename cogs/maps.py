import discord
from discord import app_commands
from discord.ext import commands
import random
import os

MAPS_DATA = {
    "erangel": {
        "name": "Erangel",
        "hot": ["Pochinki", "School", "Sosnovka Military Base", "Georgopol", "Mylta Power", "Rozhok"],
        "safe": ["Zharki", "Severny", "Kameshki", "Lipovka", "Gatka", "Primorsk", "Ferry Pier"]
    },
    "miramar": {
        "name": "Miramar",
        "hot": ["Pecado", "Hacienda del Patron", "Los Leones", "San Martin", "El Pozo"],
        "safe": ["Campo Militar", "Tierra Bronca", "Cruz del Valle", "Puerto Paraiso", "Valle del Mar"]
    },
    "sanhok": {
        "name": "Sanhok",
        "hot": ["Bootcamp", "Paradise Resort", "Ruins", "Pai Nan", "Camp Alpha"],
        "safe": ["Mongnai", "Khao", "Na Kham", "Tambang", "Kampong", "Docks"]
    },
    "vikendi": {
        "name": "Vikendi",
        "hot": ["Castle", "Cosmodrome", "Volnova", "Goroka", "Dino Park"],
        "safe": ["Port", "Trevno", "Vihar", "Zabar", "Cantra", "Milnar"]
    },
    "taego": {
        "name": "Taego",
        "hot": ["Terminal", "Ho San", "Go Dok", "Camp Studio"],
        "safe": ["Yong Cheon", "Wol Song", "Song Am", "Buk San"]
    },
    "deston": {
        "name": "Deston",
        "hot": ["Ripton", "Arena", "Concert", "Hydroelectric Dam"],
        "safe": ["Wind Farm", "Swamp", "Holston Meadows", "Buxley"]
    },
    "rondo": {
        "name": "Rondo",
        "hot": ["Jadena City", "NEOX Factory", "Stadium", "Mey Ran"],
        "safe": ["Yu Lin", "Tin Long Garden", "Lan Bi", "Dan Bin"]
    }
}

class MapsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="drop", description="Випадковий вибір локації для стрибка")
    @app_commands.describe(
        map_name="Назва мапи", 
        drop_type="Тип гри (Hot Drop або Safe Zone)"
    )
    @app_commands.choices(map_name=[
        app_commands.Choice(name=m['name'], value=k) for k, m in MAPS_DATA.items()
    ])
    @app_commands.choices(drop_type=[
        app_commands.Choice(name="🔥 Гаряча точка (Hot Drop)", value="hot"),
        app_commands.Choice(name="🛡️ Безпечна зона (Safe)", value="safe"),
        app_commands.Choice(name="🎲 Будь-куди (Random)", value="random")
    ])
    async def drop(self, interaction: discord.Interaction, map_name: app_commands.Choice[str], drop_type: app_commands.Choice[str] = None):
        map_key = map_name.value
        map_info = MAPS_DATA.get(map_key)
        
        dtype = drop_type.value if drop_type else "random"
        
        if dtype == "hot":
            choice = random.choice(map_info["hot"])
            desc = "Готуйтеся до інтенсивного бою!"
            color = 0xe74c3c
            icon = "🔥"
        elif dtype == "safe":
            choice = random.choice(map_info["safe"])
            desc = "Спокійний лут на старті."
            color = 0x2ecc71
            icon = "🛡️"
        else:
            all_locs = map_info["hot"] + map_info["safe"]
            choice = random.choice(all_locs)
            is_hot = choice in map_info["hot"]
            desc = "Готуйтеся до інтенсивного бою!" if is_hot else "Спокійний лут на старті."
            color = 0xe74c3c if is_hot else 0x2ecc71
            icon = "🔥" if is_hot else "🛡️"

        embed = discord.Embed(
            title=f"🪂 Точка висадки: {map_info['name']}",
            description=f"Найкраще місце для вас:\n\n# {icon} **{choice}**\n\n*{desc}*",
            color=color
        )
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="map", description="Показати мапу спавнів (транспорт, лут)")
    @app_commands.describe(
        map_name="Назва мапи",
        spawn_type="Що саме показати на мапі?"
    )
    @app_commands.choices(map_name=[
        app_commands.Choice(name=m['name'], value=k) for k, m in MAPS_DATA.items()
    ])
    @app_commands.choices(spawn_type=[
        app_commands.Choice(name="🚗 Автомобілі (Vehicles)", value="vehicles"),
        app_commands.Choice(name="🚤 Човни (Boats)", value="boats"),
        app_commands.Choice(name="🪂 Планери (Gliders)", value="gliders"),
        app_commands.Choice(name="🎒 Звичайний вид (Default)", value="base")
    ])
    async def show_map(self, interaction: discord.Interaction, map_name: app_commands.Choice[str], spawn_type: app_commands.Choice[str]):
        await interaction.response.defer()
        
        m_key = map_name.value
        s_type = spawn_type.value
        
        file_path = os.path.join(os.path.dirname(__file__), f"../assets/maps/{m_key}_{s_type}.png")
        base_file_path = os.path.join(os.path.dirname(__file__), f"../assets/maps/{m_key}_base.png")
        
        # Намагаємося завантажити згенерований файл або базову мапу
        target_path = file_path if os.path.exists(file_path) else base_file_path
        
        if os.path.exists(target_path):
            file = discord.File(target_path, filename="map.png")
            embed = discord.Embed(title=f"🗺️ Мапа {map_name.name} ({spawn_type.name})", color=0x3498db)
            embed.set_image(url="attachment://map.png")
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send(f"❌ Мапу **{map_name.name}** для спавну **{spawn_type.name}** поки не завантажено на сервер. Додайте зображення в `assets/maps/{m_key}_{s_type}.png`.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(MapsCog(bot))
    print("Loaded extension: maps")
