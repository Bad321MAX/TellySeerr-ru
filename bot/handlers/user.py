# bot/handlers/user.py
import httpx
from pyrogram import Client, filters
from pyrogram.types import Message

from bot import app
from config import settings
from bot.services.http_clients import http_client, jellyfin_headers, jellyseerr_headers
from bot.services.database import store_linked_user, get_linked_user, delete_linked_user
from bot.i18n import t


@app.on_message(filters.command("link", prefixes="/") & filters.private)
async def link_cmd(client: Client, message: Message):
    try:
        _, jellyfin_username, password = message.text.split(maxsplit=2)
    except ValueError:
        await message.reply(t("usage_link"), parse_mode=None)
        return

    sent = await message.reply(t("linking"))

    try:
        auth = await http_client.post(
            f"{settings.JELLYFIN_URL}/Users/AuthenticateByName",
            json={"Username": jellyfin_username, "Pw": password},
            headers=jellyfin_headers,
        )
        if auth.status_code == 401:
            await sent.edit(t("auth_failed"))
            return
        auth.raise_for_status()
        jf_id = auth.json()["User"]["Id"]
    except httpx.RequestError as e:
        await sent.edit(t("auth_error", error=str(e)))
        return

    try:
        resp = await http_client.get(
            f"{settings.JELLYSEERR_URL}/api/v1/user?take=1000",
            headers=jellyseerr_headers,
        )
        resp.raise_for_status()
        user = next(
            (
                u
                for u in resp.json().get("results", [])
                if str(u.get("jellyfinUserId")) == str(jf_id)
            ),
            None,
        )
        if not user:
            await sent.edit(t("link_not_found_in_jellyseerr"))
            return

        await store_linked_user(
            telegram_id=str(message.from_user.id),
            jellyseerr_user_id=str(user["id"]),
            jellyfin_user_id=str(jf_id),
            username=user.get("username") or jellyfin_username,
        )
        await sent.edit(
            t(
                "link_success",
                username=user.get("username") or jellyfin_username,
            )
        )
    except httpx.RequestError as e:
        await sent.edit(t("generic_network_error", error=str(e)))

    await message.delete()


@app.on_message(filters.command("unlink", prefixes="/") & filters.private)
async def unlink_cmd(client: Client, message: Message):
    if not await get_linked_user(str(message.from_user.id)):
        await message.reply(t("unlink_no_link"))
        return
    await delete_linked_user(str(message.from_user.id))
    await message.reply(t("unlink_success"))
