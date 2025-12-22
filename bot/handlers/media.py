import logging
from pyrogram import filters
from pyrogram.types import Message, CallbackQuery, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from bot import app
from config import settings
from bot.services.http_clients import http_client, jellyseerr_headers
from bot.services.database import get_linked_user
from bot.helpers.formatting import format_media_item
from bot.helpers.markup import create_media_pagination_markup
from bot.services.user_state import user_states, UserState
from bot.i18n import t

# Импорт для /link
from bot.handlers.user import _handle_link_credentials

log = logging.getLogger(__name__)
_cache = {}

async def _search(q: str):
    try:
        # Убрали quote — httpx сам закодирует
        r = await http_client.get(
            f"{settings.JELLYSEERR_URL}/api/v1/search",
            params={"query": q},
            headers=jellyseerr_headers,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        _cache[q] = results
        return results
    except Exception as e:
        log.error(f"Error searching for '{q}': {e}")
        return []

async def _discover():
    try:
        movies = await http_client.get(f"{settings.JELLYSEERR_URL}/api/v1/discover/movies", headers=jellyseerr_headers)
        tv = await http_client.get(f"{settings.JELLYSEERR_URL}/api/v1/discover/tv", headers=jellyseerr_headers)
        movies.raise_for_status()
        tv.raise_for_status()
        return movies.json().get("results", []) + tv.json().get("results", [])
    except Exception as e:
        log.error(f"Error fetching discover: {e}")
        return []

@app.on_message(filters.command("request") & filters.private)
async def request_cmd(_, m: Message):
    user_states.set(m.from_user.id, UserState.REQUEST_SEARCH)
    await m.reply(t("enter_movie_series_name"), parse_mode=ParseMode.HTML)

@app.on_message(filters.command("discover") & filters.private)
async def discover_cmd(_, m: Message):
    wait = await m.reply(t("discover_searching"))
    res = await _discover()
    if not res:
        await wait.edit(t("no_results"))
        return
    item = res[0]
    text, poster = format_media_item(item, 0, len(res))
    kb = create_media_pagination_markup("discover", 0, len(res), item.get("mediaType"), item.get("id"))
    await wait.delete()
    await m.reply_photo(poster, caption=text, reply_markup=kb, parse_mode=ParseMode.HTML)

# Исключаем все команды из обработки текста — теперь /requests и /watch проходят дальше!
@app.on_message(filters.text & ~filters.command(["request", "discover", "link", "requests", "watch", "start", "help", "unlink"]) & filters.private)
async def text_router(_, m: Message):
    st = user_states.get(m.from_user.id)
    if st == UserState.REQUEST_SEARCH:
        user_states.clear(m.from_user.id)
        wait = await m.reply(t("searching"))
        res = await _search(m.text)
        if not res:
            await wait.edit(t("no_results"))
            return
        item = res[0]
        text, poster = format_media_item(item, 0, len(res))
        kb = create_media_pagination_markup(m.text, 0, len(res), item.get("mediaType"), item.get("id"))
        await wait.delete()
        await m.reply_photo(poster, caption=text, reply_markup=kb, parse_mode=ParseMode.HTML)

    elif st == UserState.LINK_CREDENTIALS:
        user_states.clear(m.from_user.id)  # ← Добавили очистку состояния
        await _handle_link_credentials(m)

# Остальные callback'и без изменений
@app.on_callback_query(filters.regex(r"^media_nav:"))
async def media_nav(_, cq: CallbackQuery):
    _, dir_, idx, query = cq.data.split(":", 3)
    idx = int(idx) + (-1 if dir_ == "prev" else 1)
    res = await _search(query) if query != "discover" else await _discover()
    if 0 <= idx < len(res):
        item = res[idx]
        text, poster = format_media_item(item, idx, len(res))
        kb = create_media_pagination_markup(query, idx, len(res), item.get("mediaType"), item.get("id"))
        current_photo = cq.message.photo
        if current_photo and poster == current_photo.file_id:
            await cq.edit_message_caption(caption=text, reply_markup=kb, parse_mode=ParseMode.HTML)
        else:
            await cq.edit_message_media(
                media=InputMediaPhoto(media=poster, caption=text, parse_mode=ParseMode.HTML),
                reply_markup=kb
            )
    await cq.answer()

@app.on_callback_query(filters.regex(r"^media_req:"))
async def media_req(_, cq: CallbackQuery):
    _, media_type, tmdb_id = cq.data.split(":", 2)
    tmdb_id = int(tmdb_id)
    linked = await get_linked_user(str(cq.from_user.id))
    if not linked:
        await cq.answer(t("request_callback_need_link"), show_alert=True)
        return

    if media_type == "tv":
        r = await http_client.get(f"{settings.JELLYSEERR_URL}/api/v1/tv/{tmdb_id}", headers=jellyseerr_headers)
        r.raise_for_status()
        seasons = [s.get("seasonNumber") for s in r.json().get("seasons", []) if s.get("seasonNumber", 0) > 0]
        if not seasons:
            await cq.answer(t("seasons_not_found"), show_alert=True)
            return
        buttons = []
        for s in sorted(seasons):
            buttons.append([InlineKeyboardButton(f"Сезон {s}", callback_data=f"season_req:{tmdb_id}:{s}")])
        buttons.append([InlineKeyboardButton("Все сезоны", callback_data=f"season_req:{tmdb_id}:all")])
        await cq.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
        await cq.answer(t("select_seasons"))
        return

    payload = {"mediaType": "movie", "mediaId": tmdb_id, "userId": int(linked[0])}
    log.info(f"Sending movie request: {payload}")
    try:
        response = await http_client.post(f"{settings.JELLYSEERR_URL}/api/v1/request", json=payload, headers=jellyseerr_headers)
        log.info(f"Jellyseerr response: {response.status_code} {response.text}")
        if response.status_code == 409:
            await cq.answer("Уже запрошено или доступно", show_alert=True)
        elif response.status_code in (201, 202):
            await cq.answer("Запрос принят!", show_alert=True)
        else:
            await cq.answer(f"Ошибка {response.status_code}", show_alert=True)
    except Exception as e:
        log.error(f"Error sending request: {e}")
        await cq.answer(t("request_error"), show_alert=True)

@app.on_callback_query(filters.regex(r"^season_req:"))
async def season_req(_, cq: CallbackQuery):
    _, tmdb_id, season = cq.data.split(":", 2)
    tmdb_id = int(tmdb_id)
    linked = await get_linked_user(str(cq.from_user.id))
    payload = {"mediaType": "tv", "mediaId": tmdb_id, "userId": int(linked[0])}
    if season != "all":
        payload["seasons"] = [int(season)]
    log.info(f"Sending TV request: {payload}")
    try:
        response = await http_client.post(f"{settings.JELLYSEERR_URL}/api/v1/request", json=payload, headers=jellyseerr_headers)
        log.info(f"Jellyseerr response: {response.status_code} {response.text}")
        if response.status_code == 409:
            await cq.answer("Уже запрошено или доступно", show_alert=True)
        elif response.status_code in (201, 202):
            await cq.answer(t("request_success_season" if season != "all" else "request_success", season=season), show_alert=True)
        else:
            await cq.answer(f"Ошибка {response.status_code}", show_alert=True)
    except Exception as e:
        log.error(f"Error sending season request: {e}")
        await cq.answer(t("request_error"), show_alert=True)
    await cq.message.edit_reply_markup(reply_markup=None)
