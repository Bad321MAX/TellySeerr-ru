import logging
import html
from pyrogram import filters, Client
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from bot import app
from config import settings
from bot.services.http_clients import http_client, jellyfin_headers
from bot.services.database import get_linked_user
from bot.i18n import t

log = logging.getLogger(__name__)


@app.on_message(filters.command("watch", prefixes="/") & filters.private)
async def watch_stats_cmd(_: Client, m: Message):
    log.info(f"User {m.from_user.id} called /watch")

    sent_message = await m.reply(t("fetching_watch"))

    # ─────────────────────────────────────────────
    # Проверка привязки аккаунта
    # ─────────────────────────────────────────────
    linked_user = await get_linked_user(str(m.from_user.id))
    if not linked_user:
        await sent_message.edit(t("watch_no_link"))
        log.warning(f"No linked account for user {m.from_user.id}")
        return

    _, jellyfin_user_id, _ = linked_user[:3]
    if not jellyfin_user_id:
        await sent_message.edit(t("watch_no_userid"))
        log.warning(f"No Jellyfin user ID for user {m.from_user.id}")
        return

    # ─────────────────────────────────────────────
    # Получаем просмотренные элементы пользователя
    # Используем официальный Jellyfin API
    # ─────────────────────────────────────────────
    items_url = f"{settings.JELLYFIN_URL}/Users/{jellyfin_user_id}/Items"
    params = {
        "Recursive": "true",
        "IncludeItemTypes": "Movie,Episode",
        "Filters": "IsPlayed",
        "Fields": "UserData,SeriesName",
    }

    try:
        response = await http_client.get(
            items_url,
            headers=jellyfin_headers,
            params=params,
        )
        log.info(f"/watch API response: {response.status_code}")
        response.raise_for_status()
        items = response.json().get("Items", [])
    except Exception as e:
        await sent_message.edit(t("generic_network_error"))
        log.error(f"Error fetching watch stats: {e}")
        return

    # ─────────────────────────────────────────────
    # Количество просмотренных элементов
    # ─────────────────────────────────────────────
    watched_count = len(items)

    # ─────────────────────────────────────────────
    # Последний просмотренный тайтл
    # (по LastPlayedDate)
    # ─────────────────────────────────────────────
    last_watched_title = t("no_last_watched")

    if items:
        items.sort(
            key=lambda x: x.get("UserData", {}).get("LastPlayedDate", ""),
            reverse=True,
        )
        item = items[0]
        title = item.get("Name", "Unknown")

        if item.get("Type") == "Episode":
            series = item.get("SeriesName")
            if series:
                title = f"{series} — {title}"

        last_watched_title = html.escape(title)

    # ─────────────────────────────────────────────
    # Формирование ответа
    # ─────────────────────────────────────────────
    username_html = html.escape(m.from_user.first_name or "Пользователь")

    text = (
        f"📊 <b>{username_html}'s Watch Statistics</b>\n\n"
        f"<b>📺 Total Watched Items:</b> {watched_count}\n"
        f"<b>👀 Last Watched:</b> {last_watched_title}\n\n"
        f"<i>Полное время просмотра недоступно без user token</i>"
    )

    await sent_message.edit(text, parse_mode=ParseMode.HTML)
