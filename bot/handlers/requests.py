import logging
import httpx
from pyrogram import filters, Client
from pyrogram.types import Message, CallbackQuery, InputMediaPhoto
from pyrogram.enums import ParseMode

from bot import app
from config import settings
from bot.services.http_clients import http_client, jellyseerr_headers
from bot.services.database import get_linked_user
from bot.helpers.formatting import format_request_item
from bot.helpers.markup import create_requests_pagination_markup
from bot.i18n import t

log = logging.getLogger(__name__)

# Кэш запросов (как в оригинале, но через app)
if not hasattr(app, "request_cache"):
    app.request_cache = {}


# =========================
# /requests
# =========================
@app.on_message(filters.command("requests", prefixes="/") & filters.private)
async def my_requests_cmd(_: Client, message: Message):
    log.info(f"/requests from user {message.from_user.id}")

    sent_message = await message.reply(t("fetching_requests"))

    user_id = str(message.from_user.id)
    linked_user = await get_linked_user(user_id)

    if not linked_user or not linked_user[0]:
        await sent_message.edit(t("request_callback_need_link"))
        return

    jellyseerr_user_id = linked_user[0]

    try:
        request_api_url = f"{settings.JELLYSEERR_URL}/api/v1/request"
        params = {
            "take": 100,
            "skip": 0,
            "sort": "added",
            "filter": "all",
            "requestedBy": jellyseerr_user_id,
        }

        response = await http_client.get(
            request_api_url,
            headers=jellyseerr_headers,
            params=params,
        )
        response.raise_for_status()
        user_requests_data = response.json().get("results", [])

    except httpx.RequestError as e:
        log.error(f"Failed to fetch requests: {e}")
        await sent_message.edit(t("generic_network_error"))
        return

    if not user_requests_data:
        await sent_message.edit(t("no_requests"))
        return

    # Сортируем как в оригинале
    user_requests_data.sort(key=lambda r: r.get("createdAt", ""), reverse=True)

    # Кладём в кэш
    app.request_cache[user_id] = user_requests_data

    text, photo_url = await format_request_item(
        user_requests_data[0], 0, len(user_requests_data)
    )
    markup = create_requests_pagination_markup(
        int(user_id), 0, len(user_requests_data)
    )

    if photo_url:
        await message.reply_photo(
            photo=photo_url,
            caption=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
        await sent_message.delete()
    else:
        await sent_message.edit(
            text, reply_markup=markup, parse_mode=ParseMode.HTML
        )


# =========================
# Pagination callbacks
# =========================
@app.on_callback_query(filters.regex(r"req_nav:(prev|next):(\d+):(\d+)"))
async def requests_pagination_handler(_: Client, cq: CallbackQuery):
    match = cq.matches[0]
    direction, current_index_str, user_id_str = match.groups()

    current_index = int(current_index_str)
    user_id = str(user_id_str)

    # Защита: кнопка не от этого пользователя
    if str(cq.from_user.id) != user_id:
        await cq.answer(t("requests_not_yours"), show_alert=True)
        return

    user_requests_data = app.request_cache.get(user_id)

    # Если кэша нет — догружаем (как в оригинале)
    if not user_requests_data:
        linked_user = await get_linked_user(user_id)
        if not linked_user:
            await cq.answer(t("request_callback_need_link"), show_alert=True)
            return

        try:
            response = await http_client.get(
                f"{settings.JELLYSEERR_URL}/api/v1/request",
                headers=jellyseerr_headers,
                params={
                    "take": 100,
                    "skip": 0,
                    "sort": "added",
                    "filter": "all",
                    "requestedBy": linked_user[0],
                },
            )
            response.raise_for_status()
            user_requests_data = response.json().get("results", [])
            user_requests_data.sort(
                key=lambda r: r.get("createdAt", ""), reverse=True
            )
            app.request_cache[user_id] = user_requests_data

        except Exception as e:
            log.error(f"Error re-fetching requests: {e}")
            await cq.answer(t("generic_network_error"), show_alert=True)
            return

    if not user_requests_data:
        await cq.answer(t("no_requests"), show_alert=True)
        return

    new_index = current_index + (1 if direction == "next" else -1)

    if not (0 <= new_index < len(user_requests_data)):
        await cq.answer(t("end_of_list"))
        return

    item = user_requests_data[new_index]
    text, photo_url = await format_request_item(
        item, new_index, len(user_requests_data)
    )
    markup = create_requests_pagination_markup(
        int(user_id), new_index, len(user_requests_data)
    )

    try:
        if photo_url:
            await cq.edit_message_media(
                media=InputMediaPhoto(
                    media=photo_url,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=markup,
            )
        else:
            await cq.edit_message_caption(
                caption=text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        log.warning(f"Fallback edit caption: {e}")
        await cq.edit_message_caption(
            caption=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )

    await cq.answer()
