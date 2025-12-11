# bot/handlers/media.py
import httpx
import logging
from urllib.parse import urlencode, quote
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ParseMode

from bot import app
from config import settings
from bot.services.http_clients import http_client, jellyseerr_headers
from bot.services.database import get_linked_user
from bot.helpers.formatting import format_media_item
from bot.helpers.markup import (
    create_media_pagination_markup,
    create_season_selection_markup,
)
from bot.i18n import t

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600  # 1 час


async def _search_jellyseerr(query: str):
    if not hasattr(http_client, "search_cache"):
        http_client.search_cache = {}

    if query in http_client.search_cache:
        results, timestamp = http_client.search_cache[query]
        if (datetime.utcnow() - timestamp).total_seconds() < CACHE_TTL_SECONDS:
            return results

    search_url = f"{settings.JELLYSEERR_URL}/api/v1/search"
    params = urlencode({"query": query}, quote_via=quote)
    try:
        response = await http_client.get(
            f"{search_url}?{params}", headers=jellyseerr_headers
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        http_client.search_cache[query] = (results, datetime.utcnow())
        return results
    except httpx.RequestError as e:
        logger.error(f"Error searching Jellyseerr: {e}")
        return []


async def _discover_jellyseerr():
    if hasattr(http_client, "discover_cache"):
        results, timestamp = http_client.discover_cache
        if (datetime.utcnow() - timestamp).total_seconds() < CACHE_TTL_SECONDS:
            return results

    try:
        movies_url = f"{settings.JELLYSEERR_URL}/api/v1/discover/movies"
        tv_url = f"{settings.JELLYSEERR_URL}/api/v1/discover/tv"
        movie_response = await http_client.get(
            movies_url, headers=jellyseerr_headers
        )
        tv_response = await http_client.get(tv_url, headers=jellyseerr_headers)
        movie_response.raise_for_status()
        tv_response.raise_for_status()
        results = (
            movie_response.json().get("results", [])
            + tv_response.json().get("results", [])
        )
        http_client.discover_cache = (results, datetime.utcnow())
        return results
    except httpx.RequestError as e:
        logger.error(f"Error discovering media: {e}")
        return []


async def _search_tvdb_ru(query: str):
    try:
        url = "https://api4.thetvdb.com/v4/search"
        params = {"query": query, "type": "series", "language": "ru"}
        # Предполагается, что на уровне http_client настроен токен,
        # здесь используем API-ключ как fallback.
        headers = {
            "apikey": settings.TVDB_API_KEY,
        }
        r = await http_client.get(
            url, headers=headers, params=params, timeout=10
        )
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
                    "is_tvdb": True,
                }
            )
        return results
    except Exception as e:
        logger.error(f"TheTVDB search failed: {e}")
        return []


@app.on_message(filters.command("request", prefixes="/"))
async def request_cmd(client: Client, message: Message):
    try:
        query = message.text.split(maxsplit=1)[1]
    except IndexError:
        await message.reply(
            "Пожалуйста, укажите запрос. Использование: /request <название>"
        )
        return

    sent = await message.reply(t("searching"))
    results = await _search_jellyseerr(query)
    if not results:
        await sent.edit(t("no_results"))
        return

    item = results[0]
    text, photo_url = format_media_item(item, 0, len(results))
    markup = create_media_pagination_markup(
        query, 0, len(results), item.get("mediaType", "unknown"), item.get("id")
    )

    if photo_url:
        await client.send_photo(
            chat_id=message.chat.id,
            photo=photo_url,
            caption=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
        await sent.delete()
    else:
        await sent.edit(text, reply_markup=markup, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("discover", prefixes="/"))
async def discover_cmd(client: Client, message: Message):
    sent = await message.reply("Ищу популярные тайтлы...")
    results = await _discover_jellyseerr()
    if not results:
        await sent.edit("Нет популярных тайтлов для отображения.")
        return

    query = "discover"
    item = results[0]
    text, photo_url = format_media_item(item, 0, len(results))
    markup = create_media_pagination_markup(
        query, 0, len(results), item.get("mediaType", "unknown"), item.get("id")
    )

    if photo_url:
        await client.send_photo(
            chat_id=message.chat.id,
            photo=photo_url,
            caption=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
        await sent.delete()
    else:
        await sent.edit(text, reply_markup=markup, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("series", prefixes="/"))
async def series_cmd(client: Client, message: Message):
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

    item = results[0]
    text, photo = format_media_item(item, 0, len(results))

    if not hasattr(http_client, "tvdb_results_cache"):
        http_client.tvdb_results_cache = {}
    cache_key = f"tvdb_{message.from_user.id}_{hash(query)}"
    http_client.tvdb_results_cache[cache_key] = results

    markup = create_media_pagination_markup(
        cache_key, 0, len(results), "tv", item["id"]
    )
    if photo and photo.startswith("http"):
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
    direction, idx_str, key_or_query = callback_query.matches[0].groups()
    idx = int(idx_str)

    # TVDB-поиск по cache_key
    if key_or_query.startswith("tvdb_"):
        cache = getattr(http_client, "tvdb_results_cache", {})
        results = cache.get(key_or_query, [])
        if not results:
            await callback_query.answer(
                t("search_cache_expired"), show_alert=True
            )
            return
    else:
        # Обычный поиск/ discover
        if key_or_query == "discover":
            results = await _discover_jellyseerr()
        else:
            results = await _search_jellyseerr(key_or_query)

    if not results:
        await callback_query.answer(
            t("search_cache_expired"), show_alert=True
        )
        return

    if direction == "next" and idx < len(results) - 1:
        idx += 1
    elif direction == "prev" and idx > 0:
        idx -= 1

    item = results[idx]
    text, photo = format_media_item(item, idx, len(results))
    media_type = item.get("mediaType", "tv")
    tmdb_or_tvdb_id = item.get("id")

    markup = create_media_pagination_markup(
        key_or_query, idx, len(results), media_type, tmdb_or_tvdb_id
    )

    try:
        if photo:
            await callback_query.edit_message_media(
                media={
                    "type": "photo",
                    "media": photo,
                    "caption": text,
                    "parse_mode": ParseMode.HTML,
                },
                reply_markup=markup,
            )
        else:
            await callback_query.edit_message_caption(
                caption=text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
    except Exception:
        await callback_query.edit_message_caption(
            caption=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )

    await callback_query.answer()


@app.on_callback_query(filters.regex(r"media_req:(\w+):(\d+)"))
async def media_request_handler(client: Client, callback_query: CallbackQuery):
    media_type, raw_id = callback_query.matches[0].groups()
    raw_id = int(raw_id)

    # Для фильмов поведение старое: сразу запрос
    if media_type != "tv":
        user_id = str(callback_query.from_user.id)
        linked = await get_linked_user(user_id)
        if not linked or not linked[0]:
            await callback_query.answer(
                t("request_callback_need_link"), show_alert=True
            )
            return

        payload = {
            "mediaType": "movie",
            "mediaId": raw_id,
            "userId": int(linked[0]),
        }
        try:
            await http_client.post(
                f"{settings.JELLYSEERR_URL}/api/v1/request",
                headers=jellyseerr_headers,
                json=payload,
            )
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
                    t("generic_network_error", error=str(e)),
                    show_alert=True,
                )
        except httpx.RequestError as e:
            await callback_query.answer(
                t("generic_network_error", error=str(e)), show_alert=True
            )
        return

    # Для сериалов сначала выбор сезонов через TMDB
    try:
        url = f"https://api.themoviedb.org/3/tv/{raw_id}"
        params = {
            "api_key": settings.TMDB_API_KEY,
            "language": "ru-RU",
        }
        r = await http_client.get(url, params=params)
        r.raise_for_status()
        seasons = [
            s
            for s in r.json().get("seasons", [])
            if s.get("season_number", 0) > 0
        ]
        if len(seasons) <= 1:
            linked = await get_linked_user(str(callback_query.from_user.id))
            payload = {
                "mediaType": "tv",
                "mediaId": raw_id,
                "seasons": "all",
                "userId": int(linked[0]),
            }
            await http_client.post(
                f"{settings.JELLYSEERR_URL}/api/v1/request",
                headers=jellyseerr_headers,
                json=payload,
            )
            await callback_query.answer(
                t("season_all_requested"), show_alert=True
            )
            return

        markup = create_season_selection_markup(raw_id, len(seasons))
        await callback_query.edit_message_reply_markup(reply_markup=markup)
        await callback_query.answer(t("season_choose"))
    except Exception:
        await callback_query.answer(
            "Ошибка получения сезонов", show_alert=True
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

    payload = {"mediaType": "tv", "mediaId": tmdb_id, "userId": int(linked[0])}
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
