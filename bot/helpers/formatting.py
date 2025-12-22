import html
import logging
logger = logging.getLogger(__name__)

from config import settings
from bot.services.http_clients import http_client, jellyseerr_headers
from bot.i18n import t

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

def format_media_item(item: dict, current_index: int, total_results: int) -> tuple[str, str]:
    logger.info(f"Formatting item: {item.get('name', 'No name')} | Source: {item.get('source', 'unknown')}")

    title = html.escape(
        item.get("title")
        or item.get("name")
        or item.get("seriesName")
        or item.get("series_name")
        or "Без названия"
    )
    year = (
        item.get("releaseDate")
        or item.get("firstAirDate")
        or item.get("firstAired")
        or ""
    )[:4] or "—"

    media_type = item.get("mediaType", "unknown")
    if media_type == "movie":
        media_type_str = t("movie")
    elif media_type == "tv":
        media_type_str = t("tv")
    else:
        media_type_str = media_type.capitalize()

    overview = html.escape(item.get("overview") or "")
    if not overview:
        overview = "Описание отсутствует ℹ️"

    text = (
        f"<b>{title} ({year})</b>\n"
        f"<i>{media_type_str}</i>\n\n"
        f"{overview}\n\n"
        f"Результат {current_index + 1} из {total_results}"
    )

    photo_url = ""
    poster = item.get("posterPath") or ""
    logger.info(f"Raw poster: '{poster}'")
    if poster:
        if poster.startswith("http"):
            photo_url = poster
        else:
            photo_url = f"{TMDB_IMAGE_BASE}{poster}"
    logger.info(f"Final photo URL: '{photo_url}'")
    return text, photo_url

async def format_request_item(request: dict, current_index: int, total_results: int) -> tuple[str, str]:
    media = request.get("media", {})
    media_type = media.get("mediaType", "unknown")
    tmdb_id = media.get("tmdbId")
    if not tmdb_id:
        return "<b>Ошибка: нет TMDB ID</b>", ""

    try:
        endpoint = "tv" if media_type == "tv" else "movie"
        url = f"{settings.JELLYSEERR_URL}/api/v1/{endpoint}/{tmdb_id}"
        resp = await http_client.get(url, headers=jellyseerr_headers)
        resp.raise_for_status()
        info = resp.json()
    except Exception:
        return "<b>Ошибка загрузки деталей</b>", ""

    title = info.get("name") or info.get("title") or "Неизвестно"
    year = (info.get("firstAirDate") or info.get("releaseDate") or "")[:4] or "—"
    status = request.get("status", 0)
    status_text = {
        1: "Ожидает ⏳",
        2: "Одобрено ✅",
        3: "Обрабатывается ⚙️",
        4: "Частично доступно 📦",
        5: "Доступно 🎬",
    }.get(status, "Неизвестно ❓")
    date = (request.get("createdAt") or "")[:10]

    text = (
        f"<b>{html.escape(title)} ({year})</b>\n\n"
        f"<b>Статус:</b> {status_text}\n"
        f"<b>Тип:</b> {t('tv') if media_type == 'tv' else t('movie')}\n"
        f"<b>Запрошено:</b> {date}\n\n"
        f"Запрос {current_index + 1} из {total_results}"
    )
    poster = info.get("posterPath")
    photo_url = f"{TMDB_IMAGE_BASE}{poster}" if poster else ""
    return text, photo_url
formatting.py
