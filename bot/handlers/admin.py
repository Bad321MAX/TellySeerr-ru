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
    get_all_linked_users,
    get_user_by_username,
    delete_user,
    activate_trial,
    set_vip,
)
from bot.services.user_state import user_states, UserState
from bot.i18n import t

logger = logging.getLogger(__name__)
ADMIN_IDS = settings.ADMIN_USER_IDS


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def _create_user(
    app_client: Client,
    reply_message: Message,
    telegram_user_id: int,
    telegram_username: str,
    duration_days: int = None,
    role_name_to_assign: str = None,
):
    jellyfin_url = settings.JELLYFIN_URL
    jellyseerr_url = settings.JELLYSEERR_URL

    username = re.sub(r"[^a-zA-Z0-9.-]", "", telegram_username)
    if not username:
        username = f"tg_user_{telegram_user_id}"

    temp_password = secrets.token_urlsafe(12)
    jellyfin_user_id = None
    jellyfin_user_created = False

    try:
        users_url = f"{jellyfin_url}/Users"
        users_response = await http_client.get(users_url, headers=jellyfin_headers, timeout=10)
        users_response.raise_for_status()
        jellyfin_users = users_response.json()
        existing_user = next(
            (u for u in jellyfin_users if u.get("Name", "").lower() == username.lower()),
            None
        )
        if existing_user:
            await reply_message.edit(t("user_already_exists", username=username, id=existing_user.get("Id")))
            return
    except httpx.HTTPStatusError as e:
        await reply_message.edit(t("create_user_failed", error=e.response.text))
        return
    except httpx.RequestError as e:
        await reply_message.edit(t("create_user_failed", error=str(e)))
        return

    try:
        jellyfin_user_payload = {
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
        response_fin = await http_client.post(
            f"{jellyfin_url}/Users/New",
            headers=jellyfin_headers,
            json=jellyfin_user_payload
        )
        response_fin.raise_for_status()
        jellyfin_user_id = response_fin.json().get("Id")
        jellyfin_user_created = True
    except httpx.HTTPStatusError as e:
        await reply_message.edit(t("create_user_failed", error=e.response.text))
        return
    except httpx.RequestError as e:
        await reply_message.edit(t("create_user_failed", error=str(e)))
        return

    if not jellyfin_user_id:
        await reply_message.edit(t("create_user_failed", error="No ID"))
        return

    jellyseerr_user = None
    try:
        response_seerr_import = await http_client.post(
            f"{jellyseerr_url}/api/v1/user/import-from-jellyfin",
            headers=jellyseerr_headers,
            json={"jellyfinUserIds": [jellyfin_user_id]}
        )
        response_seerr_import.raise_for_status()
        jellyseerr_user = response_seerr_import.json()[0]
    except Exception as e:
        logger.warning(f"Failed to auto-import {username} to Jellyseerr: {e}. Trying to find...")
        await asyncio.sleep(2)
        try:
            seerr_users_url = f"{jellyseerr_url}/api/v1/user?take=1000"
            seerr_response = await http_client.get(seerr_users_url, headers=jellyseerr_headers)
            seerr_response.raise_for_status()
            seerr_users = seerr_response.json().get("results", [])
            jellyseerr_user = next(
                (u for u in seerr_users if str(u.get("jellyfinUserId")) == str(jellyfin_user_id)),
                None
            )
            if not jellyseerr_user:
                raise Exception("User not found in Jellyseerr.")
        except Exception as search_e:
            logger.error(f"Failed to find user in Jellyseerr: {search_e}")
            if jellyfin_user_created:
                await http_client.delete(f"{jellyfin_url}/Users/{jellyfin_user_id}", headers=jellyfin_headers)
            await reply_message.edit(t("create_user_failed", error=str(search_e)))
            return

    if role_name_to_assign:
        logger.info(f"Assigned role '{role_name_to_assign}' to {username}.")

    expires_at = (datetime.utcnow() + timedelta(days=duration_days)).isoformat() if duration_days else None

    await store_linked_user(
        telegram_id=str(telegram_user_id),
        jellyseerr_user_id=str(jellyseerr_user.get("id")),
        jellyfin_user_id=str(jellyfin_user_id),
        username=username,
        expires_at=expires_at,
        role_name=role_name_to_assign,
    )

    try:
        dm_message = t("dm_welcome_header") + "\n\n"
        dm_message += t("dm_login") + f": `{username}`\n"
        dm_message += t("dm_password") + f": `{temp_password}`\n\n"
        dm_message += t("dm_change_password") + "\n\n"
        if duration_days:
            dm_message += t("dm_expires_in", days=duration_days)

        await app_client.send_message(
            chat_id=telegram_user_id,
            text=dm_message,
            parse_mode=ParseMode.MARKDOWN
        )
        await reply_message.edit(t("create_user_success_dm"))
    except Exception as e:
        logger.warning(f"Failed to DM {telegram_user_id}: {e}")
        await reply_message.edit(t("create_user_success_no_dm"))


# === Новые удобные команды с ожиданием ответа ===

@app.on_message(filters.command("invite") & filters.private)
async def invite_cmd(_, m: Message):
    if not is_admin(m.from_user.id):
        await m.reply("❌ Вы не администратор.")
        return
    user_states.set(m.from_user.id, UserState.ADMIN_INVITE)
    await m.reply("Ответьте на любое сообщение пользователя, которому хотите создать **постоянный аккаунт**.")


@app.on_message(filters.command("trial") & filters.private)
async def trial_cmd(_, m: Message):
    if not is_admin(m.from_user.id):
        await m.reply("❌ Вы не администратор.")
        return
    user_states.set(m.from_user.id, UserState.ADMIN_TRIAL)
    await m.reply("Ответьте на любое сообщение пользователя, которому хотите выдать **пробный доступ на 7 дней**.")


@app.on_message(filters.command("vip") & filters.private)
async def vip_cmd(_, m: Message):
    if not is_admin(m.from_user.id):
        await m.reply("❌ Вы не администратор.")
        return
    user_states.set(m.from_user.id, UserState.ADMIN_VIP)
    await m.reply("Ответьте на любое сообщение пользователя, которому хотите выдать **VIP-доступ на 30 дней**.")


# Универсальный обработчик — срабатывает при ответе на сообщение
@app.on_message(filters.reply & filters.private)
async def admin_reply_handler(_, m: Message):
    state = user_states.get(m.from_user.id)

    if state not in (UserState.ADMIN_INVITE, UserState.ADMIN_TRIAL, UserState.ADMIN_VIP):
        return

    if not m.reply_to_message or not m.reply_to_message.from_user:
        await m.reply("Ошибка: ответьте на сообщение реального пользователя.")
        user_states.clear(m.from_user.id)
        return

    target_user = m.reply_to_message.from_user
    target_id = target_user.id
    target_username = target_user.username or f"tg_user_{target_id}"

    sent = await m.reply(t("creating_user_processing"))

    if state == UserState.ADMIN_INVITE:
        await _create_user(app, sent, target_id, target_username, None, None)
    elif state == UserState.ADMIN_TRIAL:
        await _create_user(app, sent, target_id, target_username, 7, "Trial")
        await activate_trial(str(target_id), 7)
    elif state == UserState.ADMIN_VIP:
        await _create_user(app, sent, target_id, target_username, 30, "VIP")
        await set_vip(str(target_id), 30)

    user_states.clear(m.from_user.id)


@app.on_message(filters.command("listusers") & filters.private)
async def listusers_cmd(_, m: Message):
    if not is_admin(m.from_user.id):
        await m.reply("Доступ запрещён.")
        return

    sent = await m.reply(t("listusers_fetching"))
    users = await get_all_linked_users()
    if not users:
        await sent.edit(t("listusers_no_users"))
        return

    text = t("listusers_title") + "\n\n"
    for telegram_id, username, role_name, expires_at in users:
        text += f"👤 <b>@{username or 'без имени'}</b>\n"
        text += f"🆔 <code>{telegram_id}</code>\n"
        if role_name:
            text += f"🎭 <b>Роль:</b> {role_name}\n"
        if expires_at:
            exp_date = datetime.fromisoformat(expires_at)
            days_left = (exp_date - datetime.now()).days
            text += f"⏰ <b>Истекает через:</b> {days_left} дней\n"
        text += "━━━━━━━━━━━━━━━━\n"

    await sent.edit(text, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("deleteuser") & filters.private)
async def deleteuser_cmd(_, m: Message):
    if not is_admin(m.from_user.id):
        await m.reply("Доступ запрещён.")
        return

    parts = m.text.split(maxsplit=1)
    if len(parts) != 2:
        await m.reply(t("deleteuser_usage"))
        return

    username = parts[1]
    sent = await m.reply(t("deleteuser_searching", username=username))

    user_data = await get_user_by_username(username)
    if not user_data:
        await sent.edit(t("deleteuser_not_found", username=username))
        return

    telegram_id, jellyseerr_id, jellyfin_id = user_data

    try:
        if jellyfin_id:
            await http_client.delete(f"{settings.JELLYFIN_URL}/Users/{jellyfin_id}", headers=jellyfin_headers)
        if jellyseerr_id:
            await http_client.delete(f"{settings.JELLYSEERR_URL}/api/v1/user/{jellyseerr_id}", headers=jellyseerr_headers)
        await delete_user(telegram_id)
        await sent.edit(t("deleteuser_success", username=username))
    except Exception as e:
        logger.error(f"Error deleting user {username}: {e}")
        await sent.edit(t("generic_exception"))
