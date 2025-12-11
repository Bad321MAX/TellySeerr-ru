# bot/handlers/starts.py
import html

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from bot import app
from config import settings
from bot.services.http_clients import http_client, jellyfin_headers
from bot.services.database import get_linked_user
from bot.i18n import t


@app.on_message(filters.command("watch", prefixes="/"))
async def watch_stats_cmd(client: Client, message: Message):
    sent = await message.reply(t("fetching_watch"))

    linked = await get_linked_user(str(message.from_user.id))
    if not linked:
        await sent.edit(t("watch_no_link"))
        return

    _, jf_id, _ = linked[:3]
    if not jf_id:
        await sent.edit(t("watch_no_userid"))
        return

    try:
        resp = await http_client.get(
            f"{settings.JELLYFIN_URL}/Users/{jf_id}/Items",
            headers=jellyfin_headers,
            params={
                "Recursive": "true",
                "IncludeItemTypes": "Movie,Episode",
                "Filters": "IsPlayed",
                "Fields": "RunTimeTicks,UserData,SeriesName",
            },
        )
        resp.raise_for_status()
        items = resp.json().get("Items", [])
    except Exception as e:
        await sent.edit(t("generic_network_error", error=str(e)))
        return

    count = len(items)
    total_ticks = sum(
        i.get("RunTimeTicks", 0) for i in items if i.get("RunTimeTicks")
    )
    total_seconds = total_ticks / 10_000_000
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    last_title = t("no_last_watched")
    if items:
        played = [
            i
            for i in items
            if i.get("UserData", {}).get("LastPlayedDate")
        ]
        if played:
            last = max(
                played,
                key=lambda x: x["UserData"]["LastPlayedDate"],
            )
            name = last.get("Name") or ""
            if last.get("Type") == "Episode" and last.get("SeriesName"):
                name = f"{last['SeriesName']} — {name}"
            last_title = html.escape(name)

    text = t(
        "watch_stats_title",
        name=html.escape(message.from_user.first_name or "Пользователь"),
    )
    text += "\n" + t("watch_total_items", count=count)
    text += "\n" + t(
        "watch_total_time",
        days=int(days),
        hours=int(hours),
        minutes=int(minutes),
    )
    text += "\n" + t("watch_last_watched", title=last_title)

    await sent.edit(text, parse_mode=ParseMode.HTML)
