import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import time
import random
import sqlite3
import asyncio

from datetime import datetime, timedelta
from utils.data_handler import get_data, get_settings
from utils.pubg_api import (
    get_player, get_player_season_stats, get_matches, 
    get_latest_match_date, get_match, get_player_ranked_stats, get_current_season_id,
    get_clan, search_clan
)
from utils.helpers import find_record, translate_map

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

DB_FILE = os.path.join(os.path.dirname(__file__), '../database.sqlite')

cooldowns = {}

class LeaderboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    def create_embed(self, period="weekly"):
        from utils.data_handler import get_data
        user_data = get_data()
        prefix = "weekly" if period == "weekly" else "monthly"
        
        players = [p for p in user_data.values() if p.get("pubgNickname") and (p.get(f"{prefix}Wins", 0) > 0 or p.get(f"{prefix}Kills", 0) > 0)]
        players.sort(key=lambda x: (x.get(f"{prefix}Wins", 0), x.get(f"{prefix}Kills", 0)), reverse=True)
        
        title = "🔍 Таблиця лідерів"
        desc_header = "🍗 **Підсумки тижня:**\nХто тут з'їв найбільше курки?\n\n" if period == "weekly" else "🦖 **Підсумки місяця:**\nОсь список пасажирів-чемпіонів:\n\n"
        color = 0xFFA500 if period == "weekly" else 0x3498DB
        
        embed = discord.Embed(title=title, description=desc_header, color=color)
        
        if not players:
            embed.description += "*Дані відсутні для цього періоду.*"
            return embed
            
        table = "```\n#  Гравець          🏆  💀\n"
        table += "----------------------------\n"
        for i, p in enumerate(players[:15]):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
            nick = p['pubgNickname'][:14].ljust(14)
            wins = str(p.get(f"{prefix}Wins", 0)).rjust(2)
            kills = str(p.get(f"{prefix}Kills", 0)).rjust(3)
            table += f"{medal.ljust(2)} {nick} {wins} {kills}\n"
        table += "```"
        
        embed.description += table
        footer_text = "Оновлюється автоматично. Обирайте період кнопками нижче."
        embed.set_footer(text=footer_text)
        return embed

    @discord.ui.button(label="Тиждень 🍗", style=discord.ButtonStyle.primary)
    async def weekly_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.create_embed("weekly"), view=self)

    @discord.ui.button(label="Місяць 🦖", style=discord.ButtonStyle.secondary)
    async def monthly_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.create_embed("monthly"), view=self)

class StatsView(discord.ui.View):
    def __init__(self, nickname, player_id, lifetime_stats, season_stats, ranked_stats, last_match_embed_field=None, footer_text=""):
        super().__init__(timeout=180)
        self.nickname = nickname
        self.player_id = player_id
        self.lifetime_stats = lifetime_stats
        self.season_stats = season_stats
        self.ranked_stats = ranked_stats
        self.last_match_embed_field = last_match_embed_field
        self.footer_text = footer_text
        self.current_mode = "season" # Default to current season normal

    def create_embed(self, mode="season"):
        self.current_mode = mode
        if mode == "lifetime":
            title = f"🌐 Статистика PUBG: {self.nickname} (За весь час)"
            color = 0x95A5A6
            data = self.lifetime_stats
        elif mode == "season":
            title = f"📅 Статистика PUBG: {self.nickname} (Поточний сезон)"
            color = 0x2ECC71
            data = self.season_stats
        else:
            title = f"🔥 Рангова статистика: {self.nickname}"
            color = 0xE74C3C
            data = self.ranked_stats

        embed = discord.Embed(title=title, color=color)
        
        if mode in ["lifetime", "season"]:
            all_stats = data.get("attributes", {}).get("gameModeStats", {})
            modes = ['squad-fpp', 'squad', 'duo-fpp', 'duo', 'solo-fpp', 'solo']
            best_mode = None
            best_stats = None
            max_rounds = -1
            
            for m in modes:
                s = all_stats.get(m)
                if s and s.get("roundsPlayed", 0) > max_rounds:
                    max_rounds = s.get("roundsPlayed", 0)
                    best_stats = s
                    best_mode = m
            
            if not best_stats or max_rounds == 0:
                embed.description = "Статистика за цей період відсутня (0 матчів)."
            else:
                mode_map = {
                    "squad": "Команди TPP", "squad-fpp": "Команди FPP",
                    "duo": "Дуо TPP", "duo-fpp": "Дуо FPP",
                    "solo": "Соло TPP", "solo-fpp": "Соло FPP"
                }
                nice_mode = mode_map.get(best_mode, best_mode.upper())
                embed.add_field(name="Найкращий режим", value=f"`{nice_mode}`", inline=True)
                embed.add_field(name="Матчі", value=best_stats.get("roundsPlayed", 0), inline=True)
                embed.add_field(name="Перемоги", value=best_stats.get("wins", 0), inline=True)
                embed.add_field(name="Вбивства", value=best_stats.get("kills", 0), inline=True)
                
                deaths = max(best_stats.get("losses", 0), 1)
                kd = best_stats.get("kills", 0) / deaths
                embed.add_field(name="K/D Ratio", value=f"**{kd:.2f}**", inline=True)
                embed.add_field(name="Сер. шкода", value=f"{round(best_stats.get('damageDealt', 0) / max_rounds)}", inline=True)
        else:
            # Ranked Stats
            ranked_attr = data.get("attributes", {}) if data else {}
            gm_stats = ranked_attr.get("rankedGameModeStats", {})
            r_stats = gm_stats.get("squad-fpp") or gm_stats.get("squad")
            
            if not r_stats:
                embed.description = "Рангова статистика за поточний сезон відсутня."
            else:
                tier = r_stats.get("currentTier", {}).get("tier", "Unranked")
                sub_tier = r_stats.get("currentTier", {}).get("subTier", "")
                points = r_stats.get("currentRankPoint", 0)
                
                embed.add_field(name="Ранг", value=f"**{tier} {sub_tier}** ({points} RP)", inline=True)
                embed.add_field(name="Матчі", value=r_stats.get("roundsPlayed", 0), inline=True)
                embed.add_field(name="Топ-10", value=r_stats.get("top10s", 0), inline=True)
                
                k = r_stats.get("kills", 0)
                d = max(r_stats.get("deaths", 0), 1)
                rkd = k / d
                embed.add_field(name="Ranked K/D", value=f"**{rkd:.2f}**", inline=True)
                
                avg_dmg = r_stats.get("damageDealt", 0) / max(r_stats.get("roundsPlayed", 1), 1)
                embed.add_field(name="Сер. шкода", value=f"{round(avg_dmg)}", inline=True)
                embed.add_field(name="Асисти", value=r_stats.get("assists", 0), inline=True)

        if self.last_match_embed_field:
            embed.add_field(
                name=self.last_match_embed_field['name'],
                value=self.last_match_embed_field['value'],
                inline=False
            )
        
        if self.footer_text:
            embed.set_footer(text=self.footer_text)
            
        return embed

    @discord.ui.button(label="Сезон 📅", style=discord.ButtonStyle.success)
    async def season_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.create_embed("season"), view=self)

    @discord.ui.button(label="Рангова 🔥", style=discord.ButtonStyle.danger)
    async def ranked_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.create_embed("ranked"), view=self)

    @discord.ui.button(label="За весь час 🌐", style=discord.ButtonStyle.secondary)
    async def lifetime_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.create_embed("lifetime"), view=self)

class PubgCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="p_stats", description="Переглянути статистику гравця PUBG")
    @app_commands.describe(nickname="Нікнейм гравця в PUBG (опціонально)")
    async def p_stats(self, interaction: discord.Interaction, nickname: str = None):
        user_id = str(interaction.user.id)
        cd_time = CONFIG.get("COOLDOWN_P_STATS", 30000)
        
        if user_id in cooldowns:
            exp_time = cooldowns[user_id] + cd_time
            now = int(time.time() * 1000)
            if now < exp_time:
                rem = (exp_time - now) // 1000
                await interaction.response.send_message(f"⏳ Зачекайте ще **{rem}** сек.", ephemeral=True)
                return
                
        if not nickname:
            user_data = get_data()
            guild_id = str(interaction.guild.id) if interaction.guild else ""
            record = find_record(user_data, user_id, guild_id)
            if not record:
                # Якщо команда викликана в ПП, шукаємо просто по userId
                record = next((v for v in user_data.values() if v.get("userId") == user_id), None)
            
            if record and record.get("pubgNickname"):
                nickname = record.get("pubgNickname")
            else:
                await interaction.response.send_message("❌ Ви не вказали нікнейм і у вас немає прив'язаного профілю.", ephemeral=True)
                return
                
        await interaction.response.defer()
        
        try:
            player = await get_player(nickname)
            if not player:
                await interaction.followup.send(f"Гравця з нікнеймом **{nickname}** не знайдено.")
                return
            
            # Паралельно отримуємо різні типи статистики
            current_season_id = await get_current_season_id()
            
            tasks = [
                get_player_season_stats(player["id"], 'lifetime'),
            ]
            if current_season_id:
                tasks.append(get_player_season_stats(player["id"], current_season_id))
                tasks.append(get_player_ranked_stats(player["id"], current_season_id))
            
            results = await asyncio.gather(*tasks)
            lifetime_stats = results[0]
            season_stats = results[1] if len(results) > 1 else None
            ranked_stats = results[2] if len(results) > 2 else None
            
            if not lifetime_stats:
                await interaction.followup.send(f"Не вдалося отримати статистику для гравця **{nickname}**.")
                return

            # Отримання даних останнього матчу для відображення в обох режимах
            last_match_field = None
            footer_text = ""
            last_match_date = await get_latest_match_date(player)
            
            mode_map = {
                "squad": "Команди TPP", "squad-fpp": "Команди FPP",
                "duo": "Дуо TPP", "duo-fpp": "Дуо FPP",
                "solo": "Соло TPP", "solo-fpp": "Соло FPP"
            }

            if last_match_date:
                try:
                    rel_matches = player.get("relationships", {}).get("matches", {}).get("data", [])
                    if rel_matches:
                        last_mid = rel_matches[0]["id"]
                        m_data = await get_match(last_mid)
                        if m_data and "data" in m_data:
                            attr = m_data["data"]["attributes"]
                            m_mode = mode_map.get(attr.get("gameMode"), attr.get("gameMode", "").upper())
                            m_type = attr.get("matchType", "official")
                            m_type_str = "Ранговий" if m_type == "competitive" else "Звичайний"
                            
                            m_stats = None
                            for inc in m_data.get("included", []):
                                if inc["type"] == 'participant' and inc.get("attributes", {}).get("stats", {}).get("playerId") == player["id"]:
                                    m_stats = inc["attributes"]["stats"]
                                    break
                            
                            if m_stats:
                                m_place = m_stats.get("winPlace")
                                m_kills = m_stats.get("kills")
                                m_dmg = round(m_stats.get("damageDealt", 0))
                                emoji = "🏆" if m_place == 1 else "💀"
                                
                                last_match_field = {
                                    "name": "🕒 Останній матч",
                                    "value": (f"**Тип:** `{m_type_str}` | **Режим:** `{m_mode}`\n"
                                             f"**Місце:** {emoji} `{m_place}`\n"
                                             f"**Вбивства:** `💀 {m_kills}` | **Шкода:** `🎯 {m_dmg}`")
                                }
                    
                    dt = datetime.fromisoformat(last_match_date.replace('Z', '+00:00'))
                    footer_text = f"Остання гра була {dt.strftime('%d.%m.%Y %H:%M')} (UTC)"
                except Exception as e:
                    print(f"Error parsing last match: {e}")

            view = StatsView(nickname, player["id"], lifetime_stats, season_stats, ranked_stats, last_match_field, footer_text)
            embed = view.create_embed("season") # Тепер починаємо з поточного сезону
            
            cooldowns[user_id] = int(time.time() * 1000)
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            print(f"Помилка p_stats: {e}")
            await interaction.followup.send("Сталася помилка при отриманні даних PUBG API.", ephemeral=True)

    @app_commands.command(name="clan_status", description="Перевірити активність клану (хто скільки не грав)")
    async def clan_status(self, interaction: discord.Interaction):
        bot_settings = get_settings()
        if bot_settings.get("disableClanTracking"):
            await interaction.response.send_message("⭕ Відстеження активності клану наразі ВИМКНЕНО.", ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Цю команду можна використовувати лише на сервері клану.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        now = int(time.time() * 1000)
        user_data = get_data()
        
        clan_role = discord.utils.get(guild.roles, name=CONFIG.get("ROLE_SUCCESS"))
        if not clan_role:
            await interaction.followup.send("Роль клану не знайдено.")
            return
            
        clan_members = [m for m in guild.members if clan_role in m.roles]
        stats = []
        
        for m in clan_members:
            record = find_record(user_data, str(m.id), str(guild.id))
            if record and record.get("untracked"):
                continue
                
            is_playing = any(a.name == CONFIG.get("GAME_NAME") for a in m.activities)
            last_seen = record.get("lastPubgSeen", 0) if record else 0
            
            if is_playing:
                last_seen = now
                if record:
                    record["lastPubgSeen"] = now
                    
            stats.append({
                "tag": str(m),
                "diff": now - last_seen,
                "lastSeen": last_seen,
                "isPlaying": is_playing,
                "isExternal": False
            })
            
        for key, ext in user_data.items():
            if ext.get("isExternal") and ext.get("guildId") == str(guild.id):
                last_seen = ext.get("lastPubgSeen", 0)
                stats.append({
                    "tag": ext.get("username"),
                    "diff": now - last_seen,
                    "lastSeen": last_seen,
                    "isPlaying": False,
                    "isExternal": True
                })
                
        stats.sort(key=lambda x: x["diff"], reverse=True)
        
        embed = discord.Embed(title='📊 Статус активності клану', color=0xF2A900)
        
        desc = ""
        for s in stats:
            name = f"{s['tag']} (Ext)" if s["isExternal"] else s["tag"]
            
            if s["isPlaying"]:
                line = f"🟢 **{name}**: Грає зараз\n"
            elif s["lastSeen"] == 0:
                line = f"⚪ **{name}**: Немає даних\n"
            else:
                diff_ms = s["diff"]
                days = diff_ms // 86400000
                hours = (diff_ms % 86400000) // 3600000
                emoji = '🟡' if days < 3 else '🔴'
                line = f"{emoji} **{name}**: {days}д {hours}год тому\n"
                
            if len(desc) + len(line) > 4000:
                break
            desc += line
            
        embed.description = desc or "Гравців не знайдено"
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="compare_players", description="Порівняти статистику з іншим гравцем (VS Mode)")
    @app_commands.describe(target="Гравець для порівняння", mode="Режим гри (Squad/Duo/Solo)")
    @app_commands.choices(mode=[
        app_commands.Choice(name='Squad FPP', value='squad-fpp'),
        app_commands.Choice(name='Squad TPP', value='squad'),
        app_commands.Choice(name='Duo FPP', value='duo-fpp'),
        app_commands.Choice(name='Duo TPP', value='duo'),
        app_commands.Choice(name='Solo FPP', value='solo-fpp'),
        app_commands.Choice(name='Solo TPP', value='solo')
    ])
    async def compare_players(self, interaction: discord.Interaction, target: discord.User, mode: app_commands.Choice[str] = None):
        mode_value = mode.value if mode else 'squad-fpp'
        user_data = get_data()
        
        guild_id = str(interaction.guild.id) if interaction.guild else ""
        author_record = find_record(user_data, str(interaction.user.id), guild_id)
        if not author_record:
            author_record = next((v for v in user_data.values() if v.get("userId") == str(interaction.user.id)), None)
            
        if not author_record or not author_record.get("pubgNickname"):
            await interaction.response.send_message("❌ Ви не прив'язали свій PUBG профіль.", ephemeral=True)
            return
            
        target_record = find_record(user_data, str(target.id), guild_id)
        if not target_record:
            target_record = next((v for v in user_data.values() if v.get("userId") == str(target.id)), None)
        if not target_record or not target_record.get("pubgNickname"):
            await interaction.response.send_message(f"❌ Гравець {target.mention} не прив'язав свій PUBG профіль.", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        try:
            p1, p2 = await asyncio.gather(
                get_player(author_record["pubgNickname"]),
                get_player(target_record["pubgNickname"])
            )
            
            if not p1 or not p2:
                await interaction.followup.send('Помилка пошуку профілів в PUBG API.')
                return
                
            s1, s2 = await asyncio.gather(
                get_player_season_stats(p1["id"], 'lifetime'),
                get_player_season_stats(p2["id"], 'lifetime')
            )
            
            stats1 = s1.get("attributes", {}).get("gameModeStats", {}).get(mode_value) if s1 else None
            stats2 = s2.get("attributes", {}).get("gameModeStats", {}).get(mode_value) if s2 else None
            
            if not stats1 or not stats2:
                await interaction.followup.send(f"Немає достатньо даних для режиму **{mode_value}** у одного з гравців.")
                return
                
            embed = discord.Embed(title=f"⚔️ {author_record['pubgNickname']} VS {target_record['pubgNickname']}", color=0xE74C3C)
            embed.description = f"**Режим:** {mode_value.upper()}"
            
            def safe_div(a, b): return a / b if b else 0
            
            kd1 = safe_div(stats1.get('kills', 0), stats1.get('losses', 1))
            kd2 = safe_div(stats2.get('kills', 0), stats2.get('losses', 1))
            
            embed.add_field(name="Матчі", value=f"{stats1.get('roundsPlayed', 0)} vs {stats2.get('roundsPlayed', 0)}", inline=False)
            embed.add_field(name="Перемоги", value=f"{stats1.get('wins', 0)} vs {stats2.get('wins', 0)}", inline=False)
            embed.add_field(name="Вбивства", value=f"{stats1.get('kills', 0)} vs {stats2.get('kills', 0)}", inline=False)
            embed.add_field(name="K/D Ratio", value=f"{kd1:.2f} vs {kd2:.2f}", inline=False)
            
            avg_dmg1 = safe_div(stats1.get('damageDealt', 0), stats1.get('roundsPlayed', 1))
            avg_dmg2 = safe_div(stats2.get('damageDealt', 0), stats2.get('roundsPlayed', 1))
            embed.add_field(name="Середня Шкода", value=f"{avg_dmg1:.0f} vs {avg_dmg2:.0f}", inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Помилка порівняння: {e}")
            await interaction.followup.send("Сталася помилка під час порівняння.")

    @app_commands.command(name="leaderboard", description="Переглянути глобальний рейтинг гравців")
    @app_commands.describe(metric="Критерій сортування")
    @app_commands.choices(metric=[
        app_commands.Choice(name='K/D Ratio', value='kd'),
        app_commands.Choice(name='Wins', value='wins'),
        app_commands.Choice(name='Average Damage', value='avgDamage'),
        app_commands.Choice(name='Total Kills', value='totalKills')
    ])
    async def leaderboard(self, interaction: discord.Interaction, metric: app_commands.Choice[str]):
        user_data = get_data()
        players = [p for p in user_data.values() if p.get("pubgNickname")]
        
        if not players:
            await interaction.response.send_message("Ще немає даних для рейтингу.", ephemeral=True)
            return
            
        metric_key = metric.value
        players.sort(key=lambda x: float(x.get(metric_key, 0) or 0), reverse=True)
        top10 = players[:10]
        
        titles = {
            'kd': '💀 K/D Ratio',
            'wins': '🏆 Wins',
            'avgDamage': '🔥 Average Damage',
            'totalKills': '🔫 Total Kills'
        }
        
        embed = discord.Embed(title=f"🏆 Глобальний Рейтинг: {titles[metric_key]}", description="Топ-10 гравців серверу за весь час (Lifetime Squad)\n", color=0xFFD700)
        
        desc = ""
        for i, p in enumerate(top10):
            val = p.get(metric_key, 0) or 0
            if metric_key == 'avgDamage': val = round(float(val))
            elif metric_key == 'kd': val = f"{float(val):.2f}"
                
            medal = '🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else f"**{i+1}.**"
            desc += f"{medal} **{p['pubgNickname']}** — {val}\n"
            
        embed.description += (desc or "Дані оновлюються...")
        embed.set_footer(text='Оновлюється щогодини')
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="matches", description="Показати історію останніх матчів")
    @app_commands.describe(nickname="Нікнейм гравця")
    async def matches(self, interaction: discord.Interaction, nickname: str = None):
        if not nickname:
            user_data = get_data()
            guild_id = str(interaction.guild.id) if interaction.guild else ""
            record = find_record(user_data, str(interaction.user.id), guild_id)
            if not record:
                record = next((v for v in user_data.values() if v.get("userId") == str(interaction.user.id)), None)
            if record and record.get("pubgNickname"):
                nickname = record.get("pubgNickname")
                
        if not nickname:
            await interaction.response.send_message("❌ Вкажіть нікнейм або прив'яжіть профіль.", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        try:
            player = await get_player(nickname)
            if not player:
                await interaction.followup.send(f"❌ Гравця **{nickname}** не знайдено.")
                return
                
            matches_rels = player.get("relationships", {}).get("matches", {}).get("data", [])
            if not matches_rels:
                matches_rels = player.get("relationships", {}).get("matches", [])
                if isinstance(matches_rels, dict) and "data" in matches_rels:
                    matches_rels = matches_rels["data"]
            
            match_ids = [m["id"] for m in matches_rels][:5]
            if not match_ids:
                await interaction.followup.send('Матчів не знайдено.')
                return
                
            matches_data = await get_matches(match_ids)
            
            embed = discord.Embed(title=f"📜 Історія матчів: {player.get('attributes', {}).get('name', nickname)}", color=0xF2A900)
            
            for i, match in enumerate(matches_data):
                if not match or "included" not in match: continue
                
                attr = match.get("data", {}).get("attributes", {})
                mode = attr.get("gameMode", "").upper()
                m_type = attr.get("matchType", "official")
                match_type_str = "Ранговий" if m_type == "competitive" else "Звичайний" if m_type == "official" else m_type.capitalize()
                map_n = translate_map(attr.get("mapName", ""))
                duration = f"{int(attr.get('duration', 0) // 60)}m"
                
                participant = next((inc for inc in match["included"] if inc.get("type") == "participant" and inc.get("attributes", {}).get("stats", {}).get("playerId") == player["id"]), None)
                
                if participant:
                    s = participant["attributes"]["stats"]
                    place = s.get("winPlace", 0)
                    kills = s.get("kills", 0)
                    dmg = round(s.get("damageDealt", 0))
                    
                    emoji = '🏆' if place == 1 else ('🥈' if place <= 10 else '💀')
                    
                    embed.add_field(name=f"{emoji} Match {i+1} - {mode} ({map_n})", value=f"**Тип:** `{match_type_str}` | Top **{place}** | Kills: **{kills}** | Dmg: **{dmg}** \n Тривалість: {duration}", inline=False)
                    
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Помилка матчів: {e}")
            await interaction.followup.send("Помилка отримання матчів.")

    @app_commands.command(name="records", description="Переглянути Залу Слави клану (Рекорди)")
    async def records(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM records").fetchall()
            conn.close()
            
            embed = discord.Embed(
                title='🏆 Зала Слави (Hall of Fame)', 
                description='Абсолютні рекорди нашого клану за весь час!', 
                color=0xFFD700
            )
            embed.set_thumbnail(url='https://i.imgur.com/qg9b9dE.png')
            
            if not rows:
                embed.add_field(name='Пусто...', value='Поки що ніхто не встановив рекордів. Грайте матчі!')
            else:
                record_titles = {
                    'max_kills': '💀 Найбільше вбивств (матч)',
                    'max_damage': '💥 Найбільше шкоди (матч)',
                    'longest_kill': '🎯 Найдовший постріл',
                    'max_time': '⏱️ Найдовше виживання',
                    'max_heal': '💊 Найбільше лікування'
                }
                keys = ['max_kills', 'max_damage', 'longest_kill', 'max_heal']
                
                for key in keys:
                    record = next((r for r in rows if r['id'] == key), None)
                    title = record_titles.get(key, key)
                    if record:
                        val = record['value']
                        if key == 'longest_kill': val = f"{val:.1f} м"
                        elif key == 'max_damage': val = round(val)
                        
                        embed.add_field(name=title, value=f"**{val}** — {record['holderName']} (<t:{int(record['date'] / 1000)}:R>)", inline=False)
                    else:
                        embed.add_field(name=title, value='---', inline=False)
                        
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Помилка отримання рекордів: {e}")
            await interaction.followup.send("❌ Помилка отримання рекордів.")

    @app_commands.command(name="strat", description="Отримати випадковий челендж для матчу (Strat Roulette)")
    @app_commands.describe(difficulty="Складність")
    @app_commands.choices(difficulty=[
        app_commands.Choice(name='Easy (Легко)', value='easy'),
        app_commands.Choice(name='Hard (Важко)', value='hard'),
        app_commands.Choice(name='Troll (Весело)', value='troll'),
        app_commands.Choice(name='Random (Випадково)', value='random')
    ])
    async def strat(self, interaction: discord.Interaction, difficulty: app_commands.Choice[str] = None):
        challenges_easy = [
            "🔫 **Pistol Only:** Можна використовувати лише пістолети.",
            "🔇 **Silence:** Заборонено говорити в грі до першого вбивства сквадом.",
            "🚗 **Drive-by:** Вбивати можна тільки з машини.",
            "🎒 **No Backpack:** Заборонено піднімати рюкзаки (тільки жилет).",
            "💣 **Grenadier:** Кожен має носити мінімум 5 гранат.",
            "🏥 **Medic:** Один гравець тільки лікує і носить припаси, але не стріляє."
        ]
        challenges_hard = [
            "😈 **No Helmet:** Заборонено носити шоломи.",
            "🦶 **Shoes Off:** Граємо босоніж (персонажі).",
            "🏠 **Camper:** Весь матч сидіти в одній будівлі (після луту).",
            "🔭 **No Scope:** Заборонено використовувати приціли вище Red Dot / Holo.",
            "🔥 **Molotov Only:** Намагатися вбити останнього ворога коктейлем Молотова."
        ]
        challenges_troll = [
            "🤡 **Follow the Leader:** Всі ходять «змійкою» за лідером і повторюють його рухи.",
            "🚕 **Taxi Driver:** Знайти машину і пропонувати ворогам підвезти їх (в загальний чат).",
            "👊 **Fist Fight:** Фінального ворога вбити кулаками/сковорідкою.",
            "🗳️ **Democracy:** Перед кожним пострілом сквад має проголосувати «Стріляти чи ні?»."
        ]
        
        diff_val = difficulty.value if difficulty else 'random'
        
        if diff_val == 'random':
            pool = challenges_easy + challenges_hard + challenges_troll
        elif diff_val == 'easy':
            pool = challenges_easy
        elif diff_val == 'hard':
            pool = challenges_hard
        else:
            pool = challenges_troll
            
        challenge = random.choice(pool)
        
        embed = discord.Embed(
            title='🎰 Strat Roulette',
            description=challenge,
            color=0xe67e22
        )
        embed.set_footer(text='Удачі! Вона вам знадобиться...')
        
        await interaction.response.send_message(embed=embed)
        
    @app_commands.command(name="p_weekly", description="Переглянути тижневу статистику клану (Пн-Нд)")
    @app_commands.describe(sort_by="Критерій сортування")
    @app_commands.choices(sort_by=[
        app_commands.Choice(name='Перемоги (Wins)', value='wins'),
        app_commands.Choice(name='Вбивства (Kills)', value='kills')
    ])
    async def p_weekly(self, interaction: discord.Interaction, sort_by: app_commands.Choice[str] = None):
        user_data = get_data()
        # Фільтруємо гравців, які мають тижневіWins або тижневіKills > 0
        players = [p for p in user_data.values() if p.get("pubgNickname") and (p.get("weeklyWins", 0) > 0 or p.get("weeklyKills", 0) > 0)]
        
        if not players:
            await interaction.response.send_message("За цей тиждень ще немає зіграних матчів з результатом.", ephemeral=True)
            return
            
        sort_key = sort_by.value if sort_by else 'wins'
        if sort_key == 'wins':
            players.sort(key=lambda x: (x.get("weeklyWins", 0), x.get("weeklyKills", 0)), reverse=True)
        else:
            players.sort(key=lambda x: (x.get("weeklyKills", 0), x.get("weeklyWins", 0)), reverse=True)
            
        embed = discord.Embed(title="📅 Тижневі підсумки (Monday - Sunday)", color=0x2ECC71)
        today = datetime.now()
        # Розраховуємо початок і кінець тижня для відображення
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        embed.description = f"Період: `{start_of_week.strftime('%d.%m')}` — `{end_of_week.strftime('%d.%m')}`\n\n"
        
        # Будуємо таблицю
        desc = "```\n#  Гравець          🏆  💀\n"
        desc += "----------------------------\n"
        for i, p in enumerate(players[:15]): # Топ 15 гравців
            nick = p['pubgNickname'][:14].ljust(14)
            wins = str(p.get("weeklyWins", 0)).rjust(2)
            kills = str(p.get("weeklyKills", 0)).rjust(3)
            desc += f"{str(i+1).ljust(2)} {nick} {wins} {kills}\n"
        desc += "```"
        
        embed.description += desc
        embed.set_footer(text="Оновлюється після кожного матчу. Скидання щопонеділка.")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="p_monthly", description="Переглянути місячну статистику клану")
    @app_commands.describe(sort_by="Критерій сортування")
    @app_commands.choices(sort_by=[
        app_commands.Choice(name='Перемоги (Wins)', value='wins'),
        app_commands.Choice(name='Вбивства (Kills)', value='kills')
    ])
    async def p_monthly(self, interaction: discord.Interaction, sort_by: app_commands.Choice[str] = None):
        user_data = get_data()
        # Фільтруємо гравців, які мають місячніWins або місячніKills > 0
        players = [p for p in user_data.values() if p.get("pubgNickname") and (p.get("monthlyWins", 0) > 0 or p.get("monthlyKills", 0) > 0)]
        
        if not players:
            await interaction.response.send_message("За цей місяць ще немає зіграних матчів з результатом.", ephemeral=True)
            return
            
        sort_key = sort_by.value if sort_by else 'wins'
        if sort_key == 'wins':
            players.sort(key=lambda x: (x.get("monthlyWins", 0), x.get("monthlyKills", 0)), reverse=True)
        else:
            players.sort(key=lambda x: (x.get("monthlyKills", 0), x.get("monthlyWins", 0)), reverse=True)
            
        embed = discord.Embed(title="📅 Місячні підсумки", color=0x3498DB)
        today = datetime.now()
        
        embed.description = f"Період: `{today.strftime('%B %Y')}`\n\n"
        
        # Будуємо таблицю
        desc = "```\n#  Гравець          🏆  💀\n"
        desc += "----------------------------\n"
        for i, p in enumerate(players[:15]): # Топ 15 гравців
            nick = p['pubgNickname'][:14].ljust(14)
            wins = str(p.get("monthlyWins", 0)).rjust(2)
            kills = str(p.get("monthlyKills", 0)).rjust(3)
            desc += f"{str(i+1).ljust(2)} {nick} {wins} {kills}\n"
        desc += "```"
        
        embed.description += desc
        embed.set_footer(text="Оновлюється після кожного матчу. Скидання першого числа місяця.")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clan_leaderboard", description="Переглянути таблицю лідерів клану")
    async def clan_leaderboard(self, interaction: discord.Interaction):
        view = LeaderboardView()
        embed = view.create_embed("weekly")

    @app_commands.command(name="clan_set", description="Встановити клан для автоматичного відстеження (Admin only)")
    @app_commands.describe(clan_id_or_player="ID клану (починається з 'clan.') або нікнейм гравця з цього клану (наприклад, лідера)")
    async def clan_set(self, interaction: discord.Interaction, clan_id_or_player: str):
        # Перевірка прав (тільки адміни з конфігу)
        is_admin = False
        if interaction.guild:
            admin_roles = CONFIG.get("ROLES_ADMIN", [])
            is_admin = any(r.name in admin_roles for r in interaction.user.roles)
        
        if not is_admin and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ У вас немає прав для використання цієї команди.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        try:
            clan_id = None
            if clan_id_or_player.strip().startswith("clan."):
                clan_id = clan_id_or_player.strip()
            else:
                player = await get_player(clan_id_or_player.strip())
                if not player:
                    await interaction.followup.send(f"❌ Гравця **{clan_id_or_player}** не знайдено в PUBG API. Перевірте правильність написання нікнейму.")
                    return
                
                clan_id = player.get("attributes", {}).get("clanId")
                if not clan_id:
                    await interaction.followup.send(f"❌ Гравець **{clan_id_or_player}** не перебуває в жодному клані.")
                    return

            clan_data = await get_clan(clan_id)
            if not clan_data:
                await interaction.followup.send(f"❌ Не вдалося отримати дані клану за ID: `{clan_id}`.")
                return
            
            clan_name = clan_data.get("attributes", {}).get("name", "Unknown")
            clan_tag = clan_data.get("attributes", {}).get("tag", "")
            
            from utils.data_handler import get_settings, save_settings
            settings = get_settings()
            settings["clanId"] = clan_id
            settings["clanName"] = clan_name
            settings["clanTag"] = clan_tag
            await save_settings()
            
            await interaction.followup.send(f"✅ Клан **[{clan_tag}] {clan_name}** встановлено для відстеження.\nID: `{clan_id}`\n\nТепер ви можете запустити синхронізацію командою `/clan_sync`.")
            
        except Exception as e:
            print(f"Error in clan_set: {e}")
            await interaction.followup.send(f"❌ Сталася помилка при спробі встановити клан: {e}")

    @app_commands.command(name="clan_sync", description="Синхронізувати список учасників клану з PUBG API (Admin only)")
    async def clan_sync(self, interaction: discord.Interaction):
        # Перевірка прав
        is_admin = False
        if interaction.guild:
            admin_roles = CONFIG.get("ROLES_ADMIN", [])
            is_admin = any(r.name in admin_roles for r in interaction.user.roles)
        
        if not is_admin and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ У вас немає прав для використання цієї команди.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        from utils.data_handler import get_settings, get_data, save_data, mark_dirty
        settings = get_settings()
        clan_id = settings.get("clanId")
        
        if not clan_id:
            await interaction.followup.send("❌ Клан не встановлено. Використайте спочатку `/clan_set`.")
            return
            
        try:
            # Оновлюємо інформацію про клан
            clan_info = await get_clan(clan_id)
            if not clan_info or "data" not in clan_info:
                await interaction.followup.send("❌ Не вдалося отримати дані клану з PUBG API.")
                return
                
            clan_name = clan_info["data"].get("attributes", {}).get("clanName", "Unknown")
            clan_tag = clan_info["data"].get("attributes", {}).get("clanTag", "")
            
            settings["clanName"] = clan_name
            settings["clanTag"] = clan_tag
            await save_settings()
            
            await interaction.followup.send(
                f"ℹ️ **Примітка:** Офіційний PUBG API не надає готового списку всіх учасників клану.\n"
                f"Бот розпочинає **автоматичний пошук** нових членів клану [{clan_tag}] {clan_name} шляхом сканування останніх матчів ваших гравців...\n"
                f"Це може зайняти деякий час."
            )
            
            # Запускаємо синхронізацію через матчі
            from utils.scheduler import sync_clan_members
            before_count = len([k for k, v in get_data().items() if v.get("isExternal")])
            
            await sync_clan_members(self.bot)
            
            after_count = len([k for k, v in get_data().items() if v.get("isExternal")])
            added_count = after_count - before_count
            
            total_tracked = len([k for k, v in get_data().items() if v.get("pubgNickname")])
            
            await interaction.followup.send(
                f"✅ **Синхронізація (сканування матчів) завершена!**\n"
                f"• Знайдено та додано нових гравців: **{added_count}**\n"
                f"• Всього гравців у базі для відстеження: **{total_tracked}**\n\n"
                f"💡 Щоб швидко додати всіх інших гравців списком, скористайтеся новою командою:\n"
                f"`/clan_add_players nicknames_list: нік1, нік2, нік3`"
            )
            
        except Exception as e:
            print(f"Error in clan_sync: {e}")
            await interaction.followup.send(f"❌ Сталася помилка під час синхронізації: {e}")

    @app_commands.command(name="clan_add_players", description="Додати список гравців клану вручну (Admin only)")
    @app_commands.describe(nicknames_list="Список нікнеймів через кому або пробіл")
    async def clan_add_players(self, interaction: discord.Interaction, nicknames_list: str):
        # Перевірка прав (тільки адміни з конфігу)
        is_admin = False
        if interaction.guild:
            admin_roles = CONFIG.get("ROLES_ADMIN", [])
            is_admin = any(r.name in admin_roles for r in interaction.user.roles)
        
        if not is_admin and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ У вас немає прав для використання цієї команди.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        from utils.data_handler import get_settings, get_data, save_data, mark_dirty
        settings = get_settings()
        clan_id = settings.get("clanId")
        clan_name = settings.get("clanName", "Unknown")
        clan_tag = settings.get("clanTag", "")
        
        if not clan_id:
            await interaction.followup.send("❌ Клан не встановлено. Спочатку виконайте `/clan_set`.")
            return

        # Парсимо список нікнеймів
        import re
        raw_nicks = re.split(r'[,\s\n\r]+', nicknames_list)
        nicknames = list(set([n.strip() for n in raw_nicks if n.strip()]))
        
        if not nicknames:
            await interaction.followup.send("❌ Не знайдено жодного нікнейму у списку.")
            return
            
        await interaction.followup.send(f"⏳ Перевіряю та додаю {len(nicknames)} гравців через PUBG API...")
        
        user_data = get_data()
        added = []
        already_tracked = []
        not_found = []
        wrong_clan = []
        
        # Запитуємо пакетами по 10 гравців
        for i in range(0, len(nicknames), 10):
            batch = nicknames[i:i+10]
            profiles = await get_players_batch(batch)
            found_nicks = []
            
            for p_profile in profiles:
                p_nick = p_profile["attributes"]["name"]
                found_nicks.append(p_nick.lower())
                p_clan_id = p_profile.get("attributes", {}).get("clanId")
                
                # Перевіряємо чи правильний клан
                if p_clan_id != clan_id:
                    wrong_clan.append(p_nick)
                    continue
                
                # Перевіряємо чи є вже в базі
                exists = False
                for key, val in user_data.items():
                    if val.get("pubgNickname", "").lower() == p_nick.lower():
                        exists = True
                        break
                
                if exists:
                    already_tracked.append(p_nick)
                else:
                    p_id = p_profile["id"]
                    new_key = f"ext_{p_id}"
                    g_id = settings.get("guildId")
                    if not g_id and interaction.guild:
                        g_id = str(interaction.guild.id)
                        
                    user_data[new_key] = {
                        "pubgNickname": p_nick,
                        "isExternal": True,
                        "guildId": g_id,
                        "username": p_nick,
                        "addedViaClanSync": True
                    }
                    mark_dirty(new_key)
                    added.append(p_nick)
            
            # Визначаємо кого взагалі не знайдено в API
            for n in batch:
                if n.lower() not in found_nicks:
                    not_found.append(n)
                    
        if added:
            await save_data()
            
        report = [f"✅ **Результати імпорту гравців клану:**"]
        report.append(f"• Успішно додано для відстеження: **{len(added)}**")
        if added:
            report.append(f"  *({', '.join(added[:15])}{'...' if len(added) > 15 else ''})*")
        
        if already_tracked:
            report.append(f"• Вже відстежуються: **{len(already_tracked)}**")
            
        if wrong_clan:
            report.append(f"• Належать до іншого клану (або без клану): **{len(wrong_clan)}**")
            report.append(f"  *({', '.join(wrong_clan[:10])}{'...' if len(wrong_clan) > 10 else ''})*")
            
        if not_found:
            report.append(f"• Не знайдено гравців в PUBG API: **{len(not_found)}**")
            report.append(f"  *({', '.join(not_found[:10])}{'...' if len(not_found) > 10 else ''})*")
            
        await interaction.followup.send("\n".join(report))

async def setup(bot):
    await bot.add_cog(PubgCog(bot))
    print("Loaded extension: pubg")
