# bot/handlers/requests.py
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ParseMode

from bot import app
from config import settings
from bot.services.http_clients import http_client, jellyseerr_headers
from bot.services.database import get_linked_user
from bot.helpers.formatting import format_request_item
from bot.helpers.markup import create_requests_pagination_markup
from bot.i18n import t


@app.on_message(filters.command("requests", prefixes="/"))
async def my_requests_cmd(client: Client, message: Message):
    sent = await message.reply(t("fetching_requests"))

    linked = await get_linked_user(str(message.from_user.id))
    if not linked or not linked[0]:
        await sent.edit(t("request_callback_need_link"))
        return

    try:
        resp = await http_client.get(
            f"{settings.JELLYSEERR_URL}/api/v1/request?take=1000&requestedBy={linked[0]}",
            headers=jellyseerr_headers,
        )
        resp.raise_for_status()
        requests = resp.json().get("results", [])
    except Exception as e:
        await sent.edit(t("generic_network_error", error=str(e)))
        return

    if not requests:
        await sent.edit(t("no_requests"))
        return

    if not hasattr(http_client, "user_requests_cache"):
        http_client.user_requests_cache = {}
    cache_key = str(message.from_user.id)
    http_client.user_requests_cache[cache_key] = requests

    item = requests[0]
    text, photo = await format_request_item(item, 0, len(requests))
    markup = create_requests_pagination_markup(
        message.from_user.id, 0, len(requests)
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


@app.on_callback_query(filters.regex(r"req_nav:(prev|next):(\d+):(\d+)"))
async def requests_pagination_handler(client: Client, callback_query: CallbackQuery):
    direction, idx_str, user_id_str = callback_query.matches[0].groups()
    idx = int(idx_str)
    user_id = int(user_id_str)

    if user_id != callback_query.from_user.id:
        await callback_query.answer("Это не ваши запросы!", show_alert=True)
        return

    cache = getattr(http_client, "user_requests_cache", {})
    requests = cache.get(str(user_id), [])
    if not requests:
        await callback_query.answer(
            t("search_cache_expired"), show_alert=True
        )
        return

    if direction == "next" and idx < len(requests) - 1:
        idx += 1
    elif direction == "prev" and idx > 0:
        idx -= 1

    item = requests[idx]
    text, photo = await format_request_item(item, idx, len(requests))
    markup = create_requests_pagination_markup(user_id, idx, len(requests))

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
