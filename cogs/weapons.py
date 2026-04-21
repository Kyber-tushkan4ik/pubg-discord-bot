import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import os
import asyncio
from utils.data_handler import DB_FILE
from utils.helpers import is_admin

class WeaponsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_weapon(self, search_str):
        def _get():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM weapons WHERE id = ? OR name LIKE ?", (search_str.lower(), f"%{search_str}%"))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    "id": row[0], "name": row[1], "damage": row[2], 
                    "velocity": row[3], "fireRate": row[4], 
                    "reloadTime": row[5], "btk": row[6]
                }
            return None
        return await asyncio.to_thread(_get)

    @app_commands.command(name="compare", description="Порівняти дві зброї")
    @app_commands.describe(weapon1="Перша зброя (наприклад: m416)", weapon2="Друга зброя (наприклад: beryl)")
    async def compare(self, interaction: discord.Interaction, weapon1: str, weapon2: str):
        w1_data = await self.get_weapon(weapon1)
        w2_data = await self.get_weapon(weapon2)
        
        if not w1_data:
            await interaction.response.send_message(f"❌ Зброю **{weapon1}** не знайдено.", ephemeral=True)
            return
        if not w2_data:
            await interaction.response.send_message(f"❌ Зброю **{weapon2}** не знайдено.", ephemeral=True)
            return

        # Розрахунок TTK: (60 / Означений RPM або просто FireRate) * (Bullets to kill - 1)
        # У нас fireRate - це час між пострілами в секундах. Тому TTK = fireRate * (btk - 1)
        ttk1 = w1_data["fireRate"] * (w1_data["btk"] - 1)
        ttk2 = w2_data["fireRate"] * (w2_data["btk"] - 1)

        embed = discord.Embed(title=f"⚖️ Порівняння: {w1_data['name']} vs {w2_data['name']}", color=0x9b59b6)
        
        def compare_values(v1, v2, reverse=False):
            if v1 == v2: return "➖", "➖"
            win = "🟩"
            loss = "🟥"
            if reverse:
                return (win, loss) if v1 < v2 else (loss, win)
            return (win, loss) if v1 > v2 else (loss, win)

        d1_icon, d2_icon = compare_values(w1_data['damage'], w2_data['damage'])
        v1_icon, v2_icon = compare_values(w1_data['velocity'], w2_data['velocity'])
        fr1_icon, fr2_icon = compare_values(w1_data['fireRate'], w2_data['fireRate'], reverse=True)
        t1_icon, t2_icon = compare_values(ttk1, ttk2, reverse=True)
        
        embed.add_field(name=w1_data['name'], value=(
            f"**Damage:** {w1_data['damage']} {d1_icon}\n"
            f"**Velocity:** {w1_data['velocity']} m/s {v1_icon}\n"
            f"**Fire Rate:** {w1_data['fireRate']}s {fr1_icon}\n"
            f"**TTK (Lvl 2):** {ttk1:.3f}s {t1_icon}\n"
            f"**Reload:** {w1_data['reloadTime']}s"
        ), inline=True)
        
        embed.add_field(name="vs", value="\n\n\n\n", inline=True)
        
        embed.add_field(name=w2_data['name'], value=(
            f"**Damage:** {w2_data['damage']} {d2_icon}\n"
            f"**Velocity:** {w2_data['velocity']} m/s {v2_icon}\n"
            f"**Fire Rate:** {w2_data['fireRate']}s {fr2_icon}\n"
            f"**TTK (Lvl 2):** {ttk2:.3f}s {t2_icon}\n"
            f"**Reload:** {w2_data['reloadTime']}s"
        ), inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="attach", description="Розрахувати вплив модулів на зброю")
    @app_commands.describe(
        weapon="Зброя", 
        attachment="Тип модуля або хвата"
    )
    @app_commands.choices(attachment=[
        app_commands.Choice(name="Vertical Foregrip (-15% Vert)", value="vertical"),
        app_commands.Choice(name="Half Grip (-8% Vert, -8% Horiz, +Recoil Recov)", value="half"),
        app_commands.Choice(name="Angled Foregrip (-15% Horiz, +10% ADS)", value="angled"),
        app_commands.Choice(name="Compensator (AR: -15% Vert, -10% Horiz)", value="comp")
    ])
    async def attach(self, interaction: discord.Interaction, weapon: str, attachment: app_commands.Choice[str]):
        w_data = await self.get_weapon(weapon)
        if not w_data:
            await interaction.response.send_message(f"❌ Зброю **{weapon}** не знайдено.", ephemeral=True)
            return
            
        att = attachment.value
        desc = ""
        if att == "vertical":
            desc = "🛡️ **Vertical Foregrip**\nІдеально підходить для зброї з високою вертикальною віддачею (як Beryl чи AKM).\n- Зменшує вертикальну віддачу на **15%**."
        elif att == "half":
            desc = "⚖️ **Half Grip**\nНайкращий баланс для спрею на середні дистанції.\n- Зменшує вертикальну і горизонтальну віддачу на **8%**.\n- Покращує відновлення прицілу."
        elif att == "angled":
            desc = "📐 **Angled Foregrip**\nПідходить для зброї (наприклад M416), яку сильно хитає по горизонталі.\n- Зменшує горизонтальну віддачу на **15%**.\n- Збільшує швидкість ADS на **10%**."
        elif att == "comp":
            desc = "💥 **Compensator**\nУніверсальний компенсатор для контролю.\n- Зменшує вертикальну (-15%) та горизонтальну (-10%) віддачу."
            
        embed = discord.Embed(
            title=f"🔧 Модулі для {w_data['name']}: {attachment.name}",
            description=desc,
            color=0xf1c40f
        )
        await interaction.response.send_message(embed=embed)

    # --- ADMIN COMMANDS FOR WEAPONS ---
    
    @app_commands.command(name="add_weapon", description="Додати нову зброю до бази (Адмін)")
    @is_admin()
    async def add_weapon(self, interaction: discord.Interaction, w_id: str, name: str, damage: float, velocity: float, fire_rate: float, reload_time: float, btk: int = 4):
        try:
            def _add():
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO weapons (id, name, damage, velocity, fireRate, reloadTime, btk)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (w_id.lower(), name, damage, velocity, fire_rate, reload_time, btk))
                conn.commit()
                conn.close()
            await asyncio.to_thread(_add)
            await interaction.response.send_message(f"✅ Зброю **{name}** успішно додано!", ephemeral=True)
        except sqlite3.IntegrityError:
            await interaction.response.send_message(f"❌ Зброя з ID `{w_id}` вже існує. Використайте `/edit_weapon`.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Помилка: {e}", ephemeral=True)
            
    @app_commands.command(name="edit_weapon", description="Обновити ТТХ зброї (Адмін)")
    @is_admin()
    async def edit_weapon(self, interaction: discord.Interaction, w_id: str, param: str, value: float):
        valid_params = ["damage", "velocity", "fireRate", "reloadTime", "btk"]
        if param not in valid_params:
            await interaction.response.send_message(f"❌ Невідомий параметр. Допустимі: {', '.join(valid_params)}", ephemeral=True)
            return
            
        try:
            def _edit():
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                query = f"UPDATE weapons SET {param} = ? WHERE id = ?"
                cursor.execute(query, (value, w_id.lower()))
                rowcount = cursor.rowcount
                conn.commit()
                conn.close()
                return rowcount
                
            rc = await asyncio.to_thread(_edit)
            if rc == 0:
                await interaction.response.send_message(f"❌ Зброю з ID `{w_id}` не знайдено.", ephemeral=True)
            else:
                await interaction.response.send_message(f"✅ Для **{w_id}** оновлено `{param}` = {value}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Помилка: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(WeaponsCog(bot))
    print("Loaded extension: weapons")
