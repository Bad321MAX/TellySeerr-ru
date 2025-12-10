from bot.i18n import t

def bold(t_): return f"<b>{t_}</b>"
def italic(t_): return f"<i>{t_}</i>"
def code(t_): return f"<code>{t_}</code>"

def format_request_item(item):
    return t(
        "request_item",
        title=item.get("title"),
        year=item.get("year", ""),
        status=t(f"status_{item.get('status')}")
    )

def format_discover_item(item):
    return t(
        "discover_item",
        title=item.get("title"),
        overview=item.get("overview", "")
    )

def format_user_stats(stats):
    return t(
        "user_stats",
        watched=stats.get("watched", 0),
        movies=stats.get("movies", 0),
        shows=stats.get("shows", 0),
    )
