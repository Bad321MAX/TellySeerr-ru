from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bot.i18n import t


def create_media_pagination_markup(query, current_index, total_results, media_type, tmdb_id):
    buttons = []
    nav = []

    # Кнопки навигации ← →
    nav.append(
        InlineKeyboardButton("⬅️", callback_data=f"media_nav:prev:{current_index}:{query}")
        if current_index > 0
        else InlineKeyboardButton(" ", callback_data="noop")
    )
    nav.append(
        InlineKeyboardButton("➡️", callback_data=f"media_nav:next:{current_index}:{query}")
        if current_index < total_results - 1
        else InlineKeyboardButton(" ", callback_data="noop")
    )
    buttons.append(nav)

    # Кнопка запроса медиа
    if media_type == "tv":
        request_text = "📺 Запросить сериал"
    else:
        request_text = "🎬 Запросить фильм"

    buttons.append([
        InlineKeyboardButton(request_text, callback_data=f"media_req:{media_type}:{tmdb_id}")
    ])

    return InlineKeyboardMarkup(buttons)


def create_requests_pagination_markup(user_id: int, current_index: int, total: int):
    nav = []

    if current_index > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"req_nav:prev:{current_index}:{user_id}"))
    else:
        nav.append(InlineKeyboardButton(" ", callback_data="noop"))

    if current_index < total - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"req_nav:next:{current_index}:{user_id}"))
    else:
        nav.append(InlineKeyboardButton(" ", callback_data="noop"))

    return InlineKeyboardMarkup([nav])
