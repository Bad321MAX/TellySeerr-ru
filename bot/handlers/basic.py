# bot/handlers/basic.py
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from bot import app
from bot.i18n import t


@app.on_message(filters.command("start", prefixes="/") & filters.private)
async def start_cmd(client: Client, message: Message):
    await message.reply(t("start_welcome"), parse_mode=None)


@app.on_message(filters.command("help", prefixes="/"))
async def help_cmd(client: Client, message: Message):
    await message.reply(t("help_text"), parse_mode=ParseMode.MARKDOWN)
