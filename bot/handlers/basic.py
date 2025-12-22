from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from bot import app
from bot.i18n import t

HELP_TEXT = t("help")

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(_: Client, message: Message):
    await message.reply(t("start"), parse_mode=ParseMode.HTML)

@app.on_message(filters.command("help"))
async def help_cmd(_: Client, message: Message):
    await message.reply(HELP_TEXT, parse_mode=ParseMode.HTML)
