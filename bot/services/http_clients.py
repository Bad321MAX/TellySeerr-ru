import httpx
from config import settings

http_client = httpx.AsyncClient(timeout=15.0)

jellyseerr_headers = {
    "X-Api-Key": settings.JELLYSEERR_API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",  # ← Важно для Jellyseerr
}

jellyfin_headers = {
    "X-Emby-Token": settings.JELLYFIN_API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

async def close_http_client():
    await http_client.aclose()
