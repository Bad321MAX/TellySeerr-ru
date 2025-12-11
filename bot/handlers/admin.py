# bot/handlers/admin.py
import httpx
import re
import secrets
import logging
import html
import asyncio
from datetime import datetime, timedelta

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from bot import app
from config import settings
from bot.services.http_clients import http_client, jellyfin_headers, jellyseerr_headers
from bot.services.database import (
    store_linked_user,
    delete_linked_user,
    get_user_by_username,
)
from bot.i18n import t

logger = logging.getLogger(__name__)
ADMIN_USER_IDS = settings.ADMIN_USER_IDS


async def _create_user(
    app_client: Client,
    reply_message: Message,
    telegram_user_id: int,
    telegram_username: str,
    duration_days: int | None = None,
    role_name_to_assign: str | None = None,
):
    jellyfin_url = settings.JELLYFIN_URL
    jellyseerr_url = settings.JELLYSEERR_URL

    username = re.sub(r"[^a-zA-Z0-9.-]", "", telegram_username)
    if not username:
        username = f"tg_user_{telegram_user_id}"

    temp_password = secrets.token_urlsafe(12)
    jellyfin_user_id = None
    jellyfin_user_created = False

    # Проверяем, что пользователя ещё нет в Jellyfin
    try:
        users_response = await http_client.get(
            f"{jellyfin_url}/Users", headers=jellyfin_headers, timeout=10
        )
        users_response.raise_for_status()
        existing_user = next(
            (
                u
                for u in users_response.json()
                if u.get("Name", "").lower() == username.lower()
            ),
            None,
        )

        if existing_user:
            await reply_message.edit(
                t(
                    "user_already_exists",
                    username=html.escape(username),
                    id=existing_user.get("Id"),
                )
            )
            return
    except Exception as e:
        await reply_message.edit(t("generic_network_error", error=str(e)))
        return

    # Создание пользователя в Jellyfin
    try:
        payload = {
            "Name": username,
            "Password": temp_password,
            "Policy": {
                "IsAdministrator": False,
                "EnableUserPreferenceAccess": True,
                "EnableMediaPlayback": True,
                "EnableLiveTvAccess": False,
                "EnableLiveTvManagement": False,
            },
        }
        resp = await http_client.post(
            f"{jellyfin_url}/Users", headers=jellyfin_headers, json=payload
        )
        resp.raise_for_status()
        jellyfin_user_id = resp.json().get("Id")
        jellyfin_user_created = True
    except Exception as e:
        await reply_message.edit(t("create_user_failed", error=str(e)))
        return

    # Импорт в Jellyseerr
    try:
        await http_client.post(
            f"{jellyseerr_url}/api/v1/user/import-from-jellyfin",
            headers=jellyseerr_headers,
            json={"jellyfinUserIds": [jellyfin_user_id]},
        )
    except Exception as e:
        logger.warning(f"Auto-import to Jellyseerr failed: {e}")
        await asyncio.sleep(2)

    # Пытаемся найти пользователя в Jellyseerr
    jellyseerr_user_id = None
    try:
        resp = await http_client.get(
            f"{jellyseerr_url}/api/v1/user?take=1000", headers=jellyseerr_headers
        )
        resp.raise_for_status()
        seerr_users = resp.json().get("results", [])
        seerr_user = next(
            (
                u
                for u in seerr_users
                if str(u.get("jellyfinUserId")) == str(jellyfin_user_id)
            ),
            None,
        )
        if seerr_user:
            jellyseerr_user_id = seerr_user.get("id")
        else:
            raise Exception("User not found in Jellyseerr after import.")
    except Exception as e:
        logger.error(f"Failed to find user in Jellyseerr: {e}")
        if jellyfin_user_created and jellyfin_user_id:
            try:
                await http_client.delete(
                    f"{jellyfin_url}/Users/{jellyfin_user_id}",
                    headers=jellyfin_headers,
                )
            except Exception:
                pass
        await reply_message.edit(
            t("generic_exception", error="Failed to import user to Jellyseerr")
        )
        return

    # Сохраняем связь в БД
    expires_at = (
        (datetime.utcnow() + timedelta(days=duration_days)).isoformat()
        if duration_days
        else None
    )
    await store_linked_user(
        telegram_id=str(telegram_user_id),
        jellyseerr_user_id=str(jellyseerr_user_id) if jellyseerr_user_id else None,
        jellyfin_user_id=str(jellyfin_user_id),
        username=username,
        expires_at=expires_at,
        role_name=role_name_to_assign,
    )

    # Отправляем данные в ЛС
    try:
        dm_text = (
            "Ваш аккаунт создан!\n\n"
            f"Логин: `{username}`\n"
            f"Пароль: `{temp_password}`\n\n"
            "После входа смените пароль!\n\n"
            f"Jellyfin: {jellyfin_url}\n"
            f"Jellyseerr: {jellyseerr_url}"
        )
        if duration_days:
            dm_text += f"\nАккаунт истекает через {duration_days} дней"
        await app_client.send_message(
            chat_id=telegram_user_id,
            text=dm_text,
            parse_mode=ParseMode.MARKDOWN,
        )
        await reply_message.edit(t("create_user_success_dm"))
    except Exception as e:
        logger.warning(
            f"Не удалось отправить ЛС пользователю {telegram_user_id}: {e}"
        )
        await reply_message.edit(
            "Аккаунт создан, но не удалось отправить данные в ЛС.\n"
            f"Логин: `{username}`\n"
            f"Пароль: `{temp_password}`"
        )


@app.on_message(filters.command("invite", prefixes="/"))
async def invite_cmd(client: Client, message: Message):
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply(t("admin_not_authorized"))
        return
    if not message.reply_to_message:
        await message.reply(t("invite_reply_required"))
        return
    target = message.reply_to_message.from_user
    sent = await message.reply(t("creating_user_processing"))
    await _create_user(
        client,
        sent,
        target.id,
        target.username or f"tg_{target.id}",
        None,
        None,
    )


@app.on_message(filters.command("trial", prefixes="/"))
async def trial_cmd(client: Client, message: Message):
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply(t("admin_not_authorized"))
        return
    if not message.reply_to_message:
        await message.reply(t("trial_reply_required"))
        return
    target = message.reply_to_message.from_user
    sent = await message.reply(t("creating_user_processing"))
    await _create_user(
        client,
        sent,
        target.id,
        target.username or f"tg_{target.id}",
        7,
        "Trial",
    )


@app.on_message(filters.command("vip", prefixes="/"))
async def vip_cmd(client: Client, message: Message):
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply(t("admin_not_authorized"))
        return
    if not message.reply_to_message:
        await message.reply(t("vip_reply_required"))
        return
    target = message.reply_to_message.from_user
    sent = await message.reply(t("creating_user_processing"))
    await _create_user(
        client,
        sent,
        target.id,
        target.username or f"tg_{target.id}",
        30,
        "VIP",
    )


@app.on_message(filters.command("listusers", prefixes="/") & filters.private)
async def list_users_cmd(client: Client, message: Message):
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply(t("admin_not_authorized"))
        return

    sent = await message.reply(t("listusers_fetching"))

    try:
        resp = await http_client.get(
            f"{settings.JELLYFIN_URL}/Users", headers=jellyfin_headers
        )
        resp.raise_for_status()
        users = resp.json()

        if not users:
            await sent.edit(t("listusers_no_users"))
            return

        text = "<b>Пользователи Jellyfin:</b>\n\n"
        for u in users:
            name = html.escape(u.get("Name", "Unknown"))
            tag = (
                " (Админ)"
                if u.get("Policy", {}).get("IsAdministrator")
                else ""
            )
            text += f"• <code>{name}</code>{tag}\n"
        await sent.edit(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        await sent.edit(t("generic_network_error", error=str(e)))


@app.on_message(filters.command("deleteuser", prefixes="/") & filters.private)
async def delete_user_cmd(client: Client, message: Message):
    if message.from_user.id not in ADMIN_USER_IDS:
        await message.reply(t("admin_not_authorized"))
        return

    try:
        username = message.text.split(maxsplit=1)[1]
    except IndexError:
        await message.reply("Использование: /deleteuser <username>")
        return

    sent = await message.reply(
        t("deleteuser_searching", username=html.escape(username))
    )

    user_data = await get_user_by_username(username)
    jf_id = None
    js_id = None

    if user_data:
        _, js_id, jf_id = user_data

    if not jf_id:
        try:
            resp = await http_client.get(
                f"{settings.JELLYFIN_URL}/Users", headers=jellyfin_headers
            )
            resp.raise_for_status()
            found = next(
                (
                    u
                    for u in resp.json()
                    if u.get("Name", "").lower() == username.lower()
                ),
                None,
            )
            if found:
                jf_id = found["Id"]
        except Exception:
            pass

    if not jf_id:
        await sent.edit(
            t("deleteuser_not_found", username=html.escape(username))
        )
        return

    try:
        await http_client.delete(
            f"{settings.JELLYFIN_URL}/Users/{jf_id}", headers=jellyfin_headers
        )
    except Exception:
        pass

    if js_id:
        try:
            await http_client.delete(
                f"{settings.JELLYSEERR_URL}/api/v1/user/{js_id}",
                headers=jellyseerr_headers,
            )
        except Exception:
            pass

    if user_data:
        await delete_linked_user(user_data[0])

    await sent.edit(
        t("deleteuser_success", username=html.escape(username))
    )
