import os
# pyrefly: ignore [missing-import]
import aiohttp
import asyncio
from dotenv import load_dotenv

# Завантажуємо .env
if os.path.exists('.env'):
    load_dotenv('.env')
elif os.path.exists('../.env'):
    load_dotenv('../.env')

API_KEY = os.getenv("PUBG_API_KEY")
BASE_URL = "https://api.pubg.com/shards/steam"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/vnd.api+json",
    "Cache-Control": "no-cache"
}

if not API_KEY or API_KEY == 'YOUR_PUBG_API_KEY_HERE':
    print("[WARNING] PUBG API key is not configured.")
    API_KEY = None

class RateLimiter:
    """Обмежувач частоти запитів (Token Bucket) з лінивою ініціалізацією та захистом від імпульсів."""
    def __init__(self, max_calls, period, min_delay=1.5):
        self.max_calls = max_calls
        self.period = period
        self.min_delay = min_delay
        self.tokens = max_calls
        self.last_refill = None
        self.last_call = 0
        self.lock = None

    async def acquire(self):
        if self.lock is None:
            self.lock = asyncio.Lock()
        
        while True:
            wait_time = 0
            async with self.lock:
                loop = asyncio.get_event_loop()
                now = loop.time()
                
                if self.last_refill is None:
                    self.last_refill = now
                
                # Захист від занадто частих запитів (Burst Protection)
                time_since_last = now - self.last_call
                if time_since_last < self.min_delay:
                    wait_time = self.min_delay - time_since_last
                else:
                    elapsed = now - self.last_refill
                    # Додаємо токени пропорційно часу
                    refill = elapsed * (self.max_calls / self.period)
                    if refill > 0:
                        self.tokens = min(self.max_calls, self.tokens + refill)
                        self.last_refill = now
                    
                    if self.tokens >= 1:
                        self.tokens -= 1
                        self.last_call = loop.time()
                        return
                    else:
                        # Чекаємо поки з'явиться хоча б 1 токен
                        wait_time = (1 - self.tokens) / (self.max_calls / self.period)
            
            if wait_time > 0:
                await asyncio.sleep(wait_time)

# Глобальний лімітер: 5 запитів на 60 секунд (знижено для уникнення 429)
# Додано min_delay=2.0 для уникнення 429 при серійних запитах
_limiter = RateLimiter(max_calls=5, period=60, min_delay=2.0)

_session = None

async def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(headers=HEADERS)
    return _session

async def close_api():
    global _session
    if _session and not _session.closed:
        await _session.close()

async def fetch(url):
    if not API_KEY:
        raise ValueError("PUBG API key is not configured.")
    
    for attempt in range(3):
        # Чекаємо черги (Rate Limit)
        await _limiter.acquire()
        
        session = await get_session()
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            elif response.status == 404:
                return None
            elif response.status == 429:
                print(f"[PUBG API] 429 Too Many Requests, retrying in 5 seconds (Attempt {attempt+1}/3)...")
                await asyncio.sleep(5)
                continue
            else:
                text = await response.text()
                raise Exception(f"API Error {response.status}: {text}")
                
    raise Exception("API Error 429: Too Many Requests (Retries exhausted)")

async def get_player(nickname: str):
    """Отримує гравця за нікнеймом."""
    url = f"{BASE_URL}/players?filter[playerNames]={nickname}"
    try:
        data = await fetch(url)
        if data and "data" in data and len(data["data"]) > 0:
            return data["data"][0]
        return None
    except Exception as e:
        print(f"Error fetching player '{nickname}': {e}")
        return None

async def get_players_batch(nicknames: list):
    """Отримує дані для групи гравців (до 10 осіб одним запитом)."""
    if not nicknames:
        return []
        
    names_str = ",".join(nicknames[:10])
    url = f"{BASE_URL}/players?filter[playerNames]={names_str}"
    try:
        data = await fetch(url)
        if data and "data" in data:
            return data["data"] # Повертає список об'єктів гравців
        return []
    except Exception as e:
        print(f"Error fetching players batch {nicknames[:10]}: {e}")
        return []

async def get_player_season_stats(player_id: str, season_id: str = "lifetime"):
    """Отримує статистику сезону гравця."""
    url = f"{BASE_URL}/players/{player_id}/seasons/{season_id}"
    try:
        data = await fetch(url)
        if data and "data" in data:
            return data["data"]
        return None
    except Exception as e:
        print(f"Error fetching season stats: {e}")
        return None

async def get_player_ranked_stats(player_id: str, season_id: str):
    """Отримує рангову статистику гравця за сезон."""
    url = f"{BASE_URL}/players/{player_id}/seasons/{season_id}/ranked"
    try:
        data = await fetch(url)
        if data and "data" in data:
            return data["data"]
        return None
    except Exception as e:
        print(f"Error fetching ranked stats: {e}")
        return None

async def get_seasons():
    """Отримує список усіх сезонів."""
    url = f"{BASE_URL}/seasons"
    try:
        data = await fetch(url)
        if data and "data" in data:
            return data["data"]
        return []
    except Exception as e:
        print(f"Error fetching seasons: {e}")
        return []

async def get_current_season_id():
    """Отримує ID поточного сезону."""
    seasons = await get_seasons()
    for s in seasons:
        if s.get("attributes", {}).get("isCurrentSeason"):
            return s["id"]
    # Fallback: останній сезон у списку, якщо не знайшли прапорець
    if seasons:
        return seasons[-1]["id"]
    return None

async def get_match(match_id: str):
    """Отримує деталі матчу."""
    url = f"{BASE_URL}/matches/{match_id}"
    try:
        # Чекаємо черги (Rate Limit)
        await _limiter.acquire()
        
        session = await get_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status == 200:
                return await response.json()
            return None
    except Exception as e:
        print(f"Error fetching match: {e}")
        return None

async def get_latest_match_date(player_data):
    """Отримує дату останнього матчу гравця."""
    try:
        relationships = player_data.get("relationships", {})
        matches = relationships.get("matches", {}).get("data", [])
        if not matches:
            return None
        
        last_match_id = matches[0].get("id")
        if not last_match_id:
            return None
            
        match_data = await get_match(last_match_id)
        if match_data and "data" in match_data:
            return match_data["data"]["attributes"]["createdAt"]
        return None
    except Exception as e:
        print(f"Error fetching latest match date: {e}")
        return None

async def get_matches(match_ids: list):
    """Отримує кілька матчів за їхніми ID (ліміт 5)."""
    ids = match_ids[:5]
    try:
        tasks = [get_match(mid) for mid in ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [res for res in results if isinstance(res, dict) and res is not None]
    except Exception as e:
        print(f"Error fetching matches: {e}")
        return []

async def get_match_telemetry(telemetry_url: str):
    """Отримує телеметрію матчу за URL."""
    if not telemetry_url:
        return None
    try:
        # Телометрія не потребує авторизації зазвичай
        session = await get_session()
        async with session.get(telemetry_url, headers={"Accept": "application/vnd.api+json"}, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status == 200:
                return await response.json()
            raise Exception(f"Telemetry fetch failed: {response.status} {response.reason}")
    except Exception as e:
        print(f"Error fetching telemetry: {e}")
        return None

async def get_clan(clan_id: str):
    """Отримує дані клану за його ID."""
    url = f"{BASE_URL}/clans/{clan_id}"
    try:
        data = await fetch(url)
        if data and "data" in data:
            return data["data"]
        return None
    except Exception as e:
        print(f"Error fetching clan '{clan_id}': {e}")
        return None

async def search_clan(clan_name: str):
    """Шукає клан за його назвою (точним збігом)."""
    # Шард steam вимагає точну назву для фільтрації
    url = f"{BASE_URL}/clans?filter[clanName]={clan_name}"
    try:
        data = await fetch(url)
        if data and "data" in data and len(data["data"]) > 0:
            return data["data"][0]
        return None
    except Exception as e:
        print(f"Error searching clan '{clan_name}': {e}")
        return None
