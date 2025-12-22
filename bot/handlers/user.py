import logging
from pyrogram import filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from bot import app
from config import settings
from bot.services.http_clients import http_client, jellyfin_headers, jellyseerr_headers
from bot.services.database import store_linked_user, get_linked_user, delete_linked_user
from bot.services.user_state import user_states, UserState
from bot.i18n import t

log = logging.getLogger(__name__)

@app.on_message(filters.command("link") & filters.private)
async def link_cmd(_, m: Message):
    user_states.set(m.from_user.id, UserState.LINK_CREDENTIALS)
    await m.reply(
        "🔗 <b>Привязка аккаунта Jellyfin</b>\n\n"
        "📝 Отправьте следующим сообщением:\n"
        "<code>логин пароль</code>\n\n"
        "<i>Пример:</i>\n"
        "<code>user123 mysecretpass</code>",
        parse_mode=ParseMode.HTML
    )

async def _handle_link_credentials(m: Message):
    current_state = user_states.get(m.from_user.id)
    if current_state != UserState.LINK_CREDENTIALS:
        log.debug(f"Unexpected call to _handle_link_credentials for user {m.from_user.id}, state: {current_state}")
        return

    # Теперь очищаем состояние
    user_states.clear(m.from_user.id)

    text = m.text.strip()
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        await m.reply("❌ Неверный формат. Нужно: <code>логин пароль</code>", parse_mode=ParseMode.HTML)
        return

    username, password = parts
    log.info(f"User {m.from_user.id} attempting to link with username: {username}")

    status_msg = await m.reply("🔄 <i>Проверяю логин и пароль...</i>", parse_mode=ParseMode.HTML)

    try:
        auth_response = await http_client.post(
            f"{settings.JELLYFIN_URL}/Users/AuthenticateByName",
            json={"Username": username, "Pw": password},
            headers=jellyfin_headers
        )
        log.info(f"Jellyfin auth response: {auth_response.status_code}")

        if auth_response.status_code == 401:
            await status_msg.edit("❌ <b>Неверный логин или пароль от Jellyfin</b>")
            log.warning(f"Auth failed (401) for username {username}")
            return

        auth_response.raise_for_status()
        jellyfin_user_id = auth_response.json()["User"]["Id"]
        log.info(f"Authenticated Jellyfin user ID: {jellyfin_user_id}")

        users_response = await http_client.get(
            f"{settings.JELLYSEERR_URL}/api/v1/user?take=1000",
            headers=jellyseerr_headers
        )
        users_response.raise_for_status()
        users = users_response.json().get("results", [])
        jellyseerr_user = next(
            (u for u in users if str(u.get("jellyfinUserId")) == str(jellyfin_user_id)),
            None
        )

        if not jellyseerr_user:
            await status_msg.edit(
                "❌ <b>Аккаунт найден в Jellyfin, но не импортирован в Jellyseerr</b>\n"
                "Обратитесь к администратору."
            )
            log.warning(f"Jellyseerr user not found for Jellyfin ID {jellyfin_user_id}")
            return

        await store_linked_user(
            telegram_id=str(m.from_user.id),
            jellyseerr_user_id=str(jellyseerr_user["id"]),
            jellyfin_user_id=str(jellyfin_user_id),
            username=jellyseerr_user.get("username") or username
        )

        await status_msg.edit(
            "✅ <b>Аккаунт успешно привязан!</b>\n\n"
            "Теперь вы можете запрашивать медиа, смотреть запросы и статистику.",
            parse_mode=ParseMode.HTML
        )
        log.info(f"Successfully linked user {m.from_user.id} to Jellyseerr ID {jellyseerr_user['id']}")

    except Exception as e:
        log.error(f"Link error for user {m.from_user.id}: {str(e)}", exc_info=True)
        await status_msg.edit("❌ <b>Ошибка при привязке</b>\nПопробуйте позже или проверьте данные.")

@app.on_message(filters.command("unlink") & filters.private)
async def unlink_cmd(_, m: Message):
    linked = await get_linked_user(str(m.from_user.id))
    if not linked:
        await m.reply(t("unlink_no_link"))
        return
    await delete_linked_user(str(m.from_user.id))
    await m.reply(t("unlink_success"))
