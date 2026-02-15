import asyncio
import logging
import re
from typing import List, Union

import arrow
from logzero import logger as log
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.constants import ParseMode

from botlistbot import captions
from botlistbot import settings
from botlistbot import util
from botlistbot.custom_botlistbot import BotListBot
from botlistbot.dialog import messages
from botlistbot.settings import SELF_CHANNEL_USERNAME


def slang_datetime(dt) -> str:
    return arrow.get(dt).humanize()


def find_bots_in_text(text: str, first=False):
    matches = re.findall(settings.REGEX_BOT_ONLY, text)
    if not matches:
        return None

    try:
        return matches[0] if first else matches
    except:
        return None


def format_name(entity):
    res = entity.first_name or ""
    if entity.first_name and entity.last_name:
        res += " " + entity.last_name
    elif entity.last_name:
        res = entity.last_name
    return res


def validate_username(username: str):
    if len(username) < 3:
        return False
    if username[0] != "@":
        username = "@" + username
    match = re.match(settings.REGEX_BOT_ONLY, username)
    return username if match else False


def get_commands():
    commands = ""
    try:
        with open("files/commands.txt", "rb") as file:
            for command in file.readlines():
                commands += "/" + command.decode("utf-8")
        return commands
    except FileNotFoundError:
        log.error("File could not be opened.")


def get_channel():
    from botlistbot.models import Channel

    try:
        return Channel.get(Channel.username == SELF_CHANNEL_USERNAME)
    except Channel.DoesNotExist:
        return False


def botlist_url_for_category(category):
    return "http://t.me/{}/{}".format(
        get_channel().username, category.current_message_id
    )


def format_keyword(kw):
    kw = kw[1:] if kw[0] == "#" else kw
    kw = kw.replace(" ", "_")
    kw = kw.replace("-", "_")
    kw = kw.replace("'", "_")
    kw = kw.lower()
    return kw


async def reroute_private_chat(
    update, context, quote, action, message, redirect_message=None, reply_markup=None
):
    cid = update.effective_chat.id
    mid = util.mid_from_update(update)
    if redirect_message is None:
        redirect_message = messages.REROUTE_PRIVATE_CHAT

    if util.is_group_message(update):
        await update.message.reply_text(
            redirect_message,
            quote=quote,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            captions.SWITCH_PRIVATE,
                            url="https://t.me/{}?start={}".format(
                                settings.SELF_BOT_NAME, action
                            ),
                        ),
                        InlineKeyboardButton(
                            "\U0001f50e Switch to inline", switch_inline_query=action
                        ),
                    ]
                ]
            ),
        )
    else:
        if mid:
            await context.bot.formatter.send_or_edit(cid, message, mid, reply_markup=reply_markup)
        else:
            await update.message.reply_text(
                message,
                quote=quote,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
            )


def make_sticker(filename, out_file, max_height=512, transparent=True):
    return  # TODO: fix


async def try_delete_after(context, messages: Union[List[Union[Message, int]], Union[Message, int]], delay: Union[float, int]):
    if isinstance(messages, (Message, int)):
        _messages = [messages]
    else:
        _messages = messages

    async def delete_messages(ctx):
        bot: BotListBot = ctx.bot
        for m in _messages:
            await bot.delete_message(m.chat_id, m.message_id, safe=True)

    context.job_queue.run_once(delete_messages, delay, name="try_delete_after")
