from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.i18n import t


def create_media_pagination_markup(
    query: str, current_index: int, total_results: int, media_type: str, tmdb_id: int
) -> InlineKeyboardMarkup:
    nav = []
    if current_index > 0:
        nav.append(
            InlineKeyboardButton(
                t("button_prev"),
                callback_data=f"media_nav:prev:{current_index}:{query}",
            )
        )
    else:
        nav.append(InlineKeyboardButton(t("noop_button"), callback_data="noop"))

    if current_index < total_results - 1:
        nav.append(
            InlineKeyboardButton(
                t("button_next"),
                callback_data=f"media_nav:next:{current_index}:{query}",
            )
        )
    else:
        nav.append(InlineKeyboardButton(t("noop_button"), callback_data="noop"))

    return InlineKeyboardMarkup(
        [
            nav,
            [
                InlineKeyboardButton(
                    t("button_request"),
                    callback_data=f"media_req:{media_type}:{tmdb_id}",
                )
            ],
        ]
    )


def create_season_selection_markup(tmdb_id: int, seasons_count: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                t("season_all"),
                callback_data=f"season_req:{tmdb_id}:all",
            )
        ]
    ]
    row = []
    for s in range(1, seasons_count + 1):
        row.append(
            InlineKeyboardButton(
                str(s), callback_data=f"season_req:{tmdb_id}:{s}"
            )
        )
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def create_requests_pagination_markup(
    user_id: int, current_index: int, total_results: int
) -> InlineKeyboardMarkup:
    nav = []
    if current_index > 0:
        nav.append(
            InlineKeyboardButton(
                t("button_prev"),
                callback_data=f"req_nav:prev:{current_index}:{user_id}",
            )
        )
    else:
        nav.append(InlineKeyboardButton(t("noop_button"), callback_data="noop"))

    if current_index < total_results - 1:
        nav.append(
            InlineKeyboardButton(
                t("button_next"),
                callback_data=f"req_nav:next:{current_index}:{user_id}",
            )
        )
    else:
        nav.append(InlineKeyboardButton(t("noop_button"), callback_data="noop"))

    return InlineKeyboardMarkup([nav])
