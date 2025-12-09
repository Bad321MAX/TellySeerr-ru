from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from bot import app


@app.on_message(filters.command("start", prefixes="/") & filters.private)
async def start_cmd(client: Client, message: Message):
    await message.reply(
            "👋 Добро пожаловать в JellyRequest Bot!\n\n"        "You can use me to request media for your Jellyfin server.\n"
            "Я помогу тебе запрашивать медиа для сервера Jellyfin.\n"        "Type `/help` to see all available commands.",
            "Чтобы начать, свяжи свой аккаунт командой `/link`.\n\n"
            "Напиши `/help`, чтобы увидеть все команды.",
            parse_mode=None,    )


HELP_TEXT = """
++Помощь JellyRequest Bot++
++Команды пользователя:++
• `/help`: Показать этот сообщение помощи.
• `/link <имя_пользователя> <пассворд>`: Привязать твой аккаунт Telegram к Jellyfin/Jellyseerr.
• `/unlink`: Отвязать аккаунт.
• `/request <название>`: Поиск и запрос фильма или сериала.
• `/discover`: Обзор популярного и трендового.
• `/requests`: Просмотр твоих запросов.
• `/watch`: Статистика просмотров.

++Админские команды:++
• `/invite` (ответить пользователю): Создать постоянный аккаунт.
• `/trial` (ответить пользователю): Пробный аккаунт на 7 дней.
• `/vip` (ответить пользователю): VIP-аккаунт на 30 дней.
• `/listusers`: Приветствие все пользователей.
• `/deleteuser <имя>`: Удалить пользователя.• `/deleteuser <username>`: Delete a user from Jellyfin, Jellyseerr, and the bot.
"""


@app.on_message(filters.command("help", prefixes="/"))
async def help_cmd(client: Client, message: Message):
    await message.reply(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)
