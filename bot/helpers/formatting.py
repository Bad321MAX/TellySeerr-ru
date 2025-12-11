# bot/helpers/formatting.py
import html

from config import settings
from bot.services.http_clients import http_client, jellyseerr_headers
from bot.i18n import t

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def format_media_item(item: dict, current_index: int, total_results: int) -> tuple[str, str]:
    title = html.escape(
        item.get("title")
        or item.get("name")
        or item.get("seriesName")
        or item.get("series_name")
        or "Неизвестно"
    )
    year = (
        item.get("releaseDate")
        or item.get("firstAirDate")
        or item.get("firstAired")
        or ""
    )
    year = year[:4] if year else "—"

    media_type = item.get("mediaType", "unknown")
    if media_type == "movie":
        media_type = "Фильм"
    elif media_type == "tv":
        media_type = "Сериал"
    else:
        media_type = media_type.capitalize()

    overview = html.escape(item.get("overview") or "")
    if not overview:
        overview = t("no_overview")

    text = t(
        "result_header",
        title=title,
        year=year,
        type=media_type,
        overview=overview,
        current=current_index + 1,
        total=total_results,
    )

    poster = (
        item.get("posterPath")
        or item.get("thumbnail")
        or item.get("image")
        or ""
    )
    if poster and not poster.startswith("http"):
        photo_url = f"{TMDB_IMAGE_BASE}{poster}"
    elif poster:
        photo_url = poster
    else:
        photo_url = ""

    return text, photo_url


def get_status_emoji(status_id: int) -> str:
    return {
        1: t("status_pending"),
        2: t("status_approved"),
        3: t("status_processing"),
        4: t("status_partially"),
        5: t("status_available"),
    }.get(status_id, t("status_unknown"))


async def format_request_item(
    request: dict, current_index: int, total_results: int
) -> tuple[str, str]:
    media = request.get("media", {})
    media_type = media.get("mediaType", "unknown")
    tmdb_id = media.get("tmdbId")

    if not tmdb_id:
        return "<b>Ошибка:</b> нет TMDB ID", ""

    try:
        endpoint = "tv" if media_type == "tv" else "movie"
        url = f"{settings.JELLYSEERR_URL}/api/v1/{endpoint}/{tmdb_id}"
        resp = await http_client.get(url, headers=jellyseerr_headers)
        resp.raise_for_status()
        info = resp.json()
    except Exception:
        return "<b>Ошибка загрузки деталей</b>", ""

    if media_type == "tv":
        title = info.get("name", "Неизвестный сериал")
        year = (info.get("firstAirDate") or "")[:4]
    else:
        title = info.get("title", "Неизвестный фильм")
        year = (info.get("releaseDate") or "")[:4]

    year = year or "—"
    status = get_status_emoji(request.get("status", 0))
    requested_date = (request.get("createdAt") or "—")[:10]

    text = (
        f"<b>{html.escape(title)} ({year})</b>\n\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Тип:</b> {'Сериал' if media_type == 'tv' else 'Фильм'}\n"
        f"<b>Запрошено:</b> {requested_date}\n\n"
        f"Запрос {current_index + 1} из {total_results}"
    )

    poster = info.get("posterPath")
    photo_url = f"{TMDB_IMAGE_BASE}{poster}" if poster else ""
    return text, photo_url
