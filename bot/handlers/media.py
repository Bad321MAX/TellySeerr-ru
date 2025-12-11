import httpx
import logging
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ParseMode

from bot import app
from config import settings
from bot.services.http_clients import http_client, jellyseerr_headers, tvdb_headers
from bot.services.database import get_linked_user
from bot.helpers.formatting import format_media_item
from bot.helpers.markup import (
    create_media_pagination_markup,
    create_season_selection_markup,
)
from bot.i18n import t

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 3600


async def _search_jellyseerr(query: str):
    if not hasattr(http_client, "search_cache"):
        http_client.search_cache = {}

    if query in http_client.search_cache:
        results, ts = http_client.search_cache[query]
        if (datetime.utcnow() - ts).total_seconds() < CACHE_TTL_SECONDS:
            return results

    try:
        url = f"{settings.JELLYSEERR_URL}/api/v1/search"
        r = await http_client.get(url, headers=jellyseerr_headers, params={"query": query})
        r.raise_for_status()
        results = r.json().get("results", [])
        http_client.search_cache[query] = (results, datetime.utcnow())
        return results
    except Exception as e:
        logger.error(f"Jellyseerr search error: {e}")
        return []


async def _search_tvdb_ru(query: str):
    """
    Поиск сериалов по русскому названию через TheTVDB v4.
    Возвращает список сериалов с полем tvdbId.
    """
    try:
        url = "https://api4.thetvdb.com/v4/search"
        headers = dict(tvdb_headers)

        # Если используешь динамический токен в http_client.tvdb_token — добавим его
        if hasattr(http_client, "tvdb_token"):
            headers["Authorization"] = f"Bearer {http_client.tvdb_token}"

        params = {"query": query, "type": "series", "language": "ru"}
        r = await http_client.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json().get("data", [])
        results = []
        for s in data:
            results.append(
                {
                    "id": s["id"],
                    "name": s.get("name") or s.get("seriesName"),
                    "overview": s.get("overview") or "",
                    "firstAired": (s.get("firstAired") or "")[:4],
                    "posterPath": s.get("image"),
                    "mediaType": "tv",
                    "tvdbId": s["id"],  # важно для Jellyseerr/Sonarr
                }
            )
        return results
    except Exception as e:
        logger.error(f"TheTVDB error: {e}")
        return []


@app.on_message(filters.command("request", prefixes="/"))
async def request_cmd(client: Client, message: Message):
    try:
        query = message.text.split(maxsplit=1)[1]
    except IndexError:
        await message.reply("Использование: /request <название>")
        return

    sent = await message.reply(t("searching"))
    results = await _search_jellyseerr(query)
    if not results:
        await sent.edit(t("no_results"))
        return

    item = results[0]
    text, photo = format_media_item(item, 0, len(results))

    # Кэшируем результаты по query (как в оригинале)
    if not hasattr(http_client, "search_cache"):
        http_client.search_cache = {}
    http_client.search_cache[query] = (results, datetime.utcnow())

    markup = create_media_pagination_markup(
        query=query,
        current_index=0,
        total_results=len(results),
        media_type=item.get("mediaType"),
        tmdb_id=item.get("id"),
    )

    if photo:
        await client.send_photo(
            message.chat.id,
            photo,
            caption=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
        await sent.delete()
    else:
        await sent.edit(text, reply_markup=markup, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("discover", prefixes="/"))
async def discover_cmd(client: Client, message: Message):
    sent = await message.reply("Discovering popular items...")

    results = []
    if hasattr(http_client, "discover_cache"):
        results, ts = http_client.discover_cache
        if (datetime.utcnow() - ts).total_seconds() >= CACHE_TTL_SECONDS:
            results = []

    if not results:
        try:
            movies_url = f"{settings.JELLYSEERR_URL}/api/v1/discover/movies"
            tv_url = f"{settings.JELLYSEERR_URL}/api/v1/discover/tv"

            rm = await http_client.get(movies_url, headers=jellyseerr_headers)
            rt = await http_client.get(tv_url, headers=jellyseerr_headers)
            rm.raise_for_status()
            rt.raise_for_status()

            results = rm.json().get("results", []) + rt.json().get("results", [])
            http_client.discover_cache = (results, datetime.utcnow())
        except Exception as e:
            await sent.edit(t("generic_network_error", error=str(e)))
            return

    if not results:
        await sent.edit(t("no_results"))
        return

    query = "discover"
    item = results[0]
    text, photo = format_media_item(item, 0, len(results))

    markup = create_media_pagination_markup(
        query=query,
        current_index=0,
        total_results=len(results),
        media_type=item.get("mediaType"),
        tmdb_id=item.get("id"),
    )

    if photo:
        await client.send_photo(
            message.chat.id,
            photo,
            caption=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
        await sent.delete()
    else:
        await sent.edit(text, reply_markup=markup, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("series", prefixes="/"))
async def series_cmd(client: Client, message: Message):
    """
    Поиск сериалов по TheTVDB (русские названия), с последующей привязкой по tvdbId.
    """
    try:
        query = message.text.split(maxsplit=1)[1]
    except IndexError:
        await message.reply("Использование: /series <название>")
        return

    sent = await message.reply(t("searching"))
    results = await _search_tvdb_ru(query)
    if not results:
        await sent.edit(t("no_results"))
        return

    # помечаем, что это результаты TheTVDB
    for r in results:
        r["source"] = "tvdb"

    item = results[0]
    text, photo = format_media_item(item, 0, len(results))

    cache_key = f"tvdb_{message.from_user.id}_{hash(query)}"
    if not hasattr(http_client, "tvdb_cache"):
        http_client.tvdb_cache = {}
    http_client.tvdb_cache[cache_key] = results

    # В callback передаём media_type tvdb, чтобы потом понимать, что это TheTVDB
    markup = create_media_pagination_markup(
        query=cache_key,
        current_index=0,
        total_results=len(results),
        media_type="tvdb",
        tmdb_id=item["id"],
    )

    if photo:
        await client.send_photo(
            message.chat.id,
            photo,
            caption=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
        await sent.delete()
    else:
        await sent.edit(text, reply_markup=markup, parse_mode=ParseMode.HTML)


@app.on_callback_query(filters.regex(r"media_nav:(prev|next):(\d+):(.+)"))
async def media_pagination_handler(client: Client, callback_query: CallbackQuery):
    direction, idx_str, query = callback_query.matches[0].groups()
    idx = int(idx_str)

    results = []

    if query == "discover":
        cached = getattr(http_client, "discover_cache", None)
        if cached:
            results, _ = cached
    elif query.startswith("tvdb_"):
        cache = getattr(http_client, "tvdb_cache", {})
        results = cache.get(query, [])
    else:
        cache = getattr(http_client, "search_cache", {})
        cached = cache.get(query)
        if cached:
            results, _ = cached

    if not results:
        await callback_query.answer(
            t("search_cache_expired"), show_alert=True
        )
        await callback_query.message.delete()
        return

    if direction == "next" and idx < len(results) - 1:
        idx += 1
    elif direction == "prev" and idx > 0:
        idx -= 1

    item = results[idx]
    text, photo = format_media_item(item, idx, len(results))

    # media_type: tvdb → особая обработка; иначе берём из item
    media_type = item.get("mediaType", "movie")
    if item.get("source") == "tvdb":
        media_type = "tvdb"

    tmdb_or_tvdb_id = item.get("id")

    markup = create_media_pagination_markup(
        query=query,
        current_index=idx,
        total_results=len(results),
        media_type=media_type,
        tmdb_id=tmdb_or_tvdb_id,
    )

    try:
        await callback_query.edit_message_media(
            media={
                "type": "photo",
                "media": photo or "",
                "caption": text,
                "parse_mode": ParseMode.HTML,
            },
            reply_markup=markup,
        )
    except Exception:
        await callback_query.edit_message_caption(
            caption=text, reply_markup=markup, parse_mode=ParseMode.HTML
        )

    await callback_query.answer()


@app.on_callback_query(filters.regex(r"media_req:(\w+):(\d+)"))
async def media_request_handler(client: Client, callback_query: CallbackQuery):
    media_type, raw_id = callback_query.matches[0].groups()
    media_id = int(raw_id)

    linked = await get_linked_user(str(callback_query.from_user.id))
    if not linked or not linked[0]:
        await callback_query.answer(
            t("request_callback_need_link"), show_alert=True
        )
        return

    jellyseerr_user_id = int(linked[0])

    payload = {
        "mediaType": "tv" if media_type == "tvdb" else media_type,
        "userId": jellyseerr_user_id,
    }

    # tvdb: отправляем и mediaId, и tvdbId
    if media_type == "tvdb":
        payload["tvdbId"] = media_id
        payload["mediaId"] = media_id  # Jellyseerr требует mediaId всегда
        payload["seasons"] = "all"     # по умолчанию все сезоны, если не выбрали
    else:
        payload["mediaId"] = media_id
        if media_type == "tv":
            payload["seasons"] = "all"

    try:
        resp = await http_client.post(
            f"{settings.JELLYSEERR_URL}/api/v1/request",
            headers=jellyseerr_headers,
            json=payload,
        )
        resp.raise_for_status()
        await callback_query.answer(
            t("request_success"), show_alert=True
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            await callback_query.answer(
                t("request_already"), show_alert=True
            )
        else:
            await callback_query.answer(
                f"Ошибка {e.response.status_code}", show_alert=True
            )
    except httpx.RequestError as e:
        await callback_query.answer(
            t("generic_network_error", error=str(e)), show_alert=True
        )


@app.on_callback_query(filters.regex(r"season_req:(\d+):(\w+)"))
async def season_request_handler(client: Client, callback_query: CallbackQuery):
    tmdb_id_str, choice = callback_query.matches[0].groups()
    tmdb_id = int(tmdb_id_str)

    linked = await get_linked_user(str(callback_query.from_user.id))
    if not linked or not linked[0]:
        await callback_query.answer(
            t("request_callback_need_link"), show_alert=True
        )
        return

    payload = {
        "mediaType": "tv",
        "mediaId": tmdb_id,
        "userId": int(linked[0]),
    }

    if choice == "all":
        payload["seasons"] = "all"
        text = t("season_all_requested")
    else:
        payload["seasons"] = [int(choice)]
        text = t("season_requested", season=choice)

    await http_client.post(
        f"{settings.JELLYSEERR_URL}/api/v1/request",
        headers=jellyseerr_headers,
        json=payload,
    )
    await callback_query.answer(text, show_alert=True)
    await callback_query.edit_message_reply_markup(reply_markup=None)
