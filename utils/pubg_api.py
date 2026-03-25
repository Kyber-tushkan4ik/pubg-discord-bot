import os
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
    "Accept": "application/vnd.api+json"
}

if not API_KEY or API_KEY == 'YOUR_PUBG_API_KEY_HERE':
    print("[WARNING] PUBG API key is not configured.")
    API_KEY = None

class RateLimiter:
    """Обмежувач частоти запитів (Token Bucket) з лінивою ініціалізацією."""
    def __init__(self, max_calls, period):
        self.max_calls = max_calls
        self.period = period
        self.tokens = max_calls
        self.last_refill = None
        self.lock = None

    async def acquire(self):
        if self.lock is None:
            self.lock = asyncio.Lock()
        
        async with self.lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            
            if self.last_refill is None:
                self.last_refill = now
                
            while True:
                now = loop.time()
                elapsed = now - self.last_refill
                # Додаємо токени пропорційно часу
                refill = elapsed * (self.max_calls / self.period)
                if refill > 0:
                    self.tokens = min(self.max_calls, self.tokens + refill)
                    self.last_refill = now
                
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                else:
                    # Чекаємо поки з'явиться хоча б 1 токен
                    wait_time = (1 - self.tokens) / (self.max_calls / self.period)
                    await asyncio.sleep(wait_time)

# Глобальний лімітер: 10 запитів на 60 секунд (з запасом для надійності)
_limiter = RateLimiter(max_calls=9, period=60)

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
    
    # Чекаємо черги (Rate Limit)
    await _limiter.acquire()
    
    session = await get_session()
    async with session.get(url) as response:
        if response.status == 200:
            return await response.json()
        elif response.status == 404:
            return None
        else:
            text = await response.text()
            raise Exception(f"API Error {response.status}: {text}")

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
