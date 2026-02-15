from random import random
from datetime import datetime

import sys

import logging
import os
import signal
import time
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Bot,
    Update,
    Message,
)
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from botlistbot import appglobals
from botlistbot import captions
from botlistbot import const
from botlistbot import mdformat
from botlistbot import settings
from botlistbot import util
from botlistbot.components import help
from botlistbot.components.botlist import new_channel_post
from botlistbot.components.search import search_handler, search_query
from botlistbot.dialog import messages
from botlistbot.helpers import try_delete_after
from botlistbot.models import Category, User
from botlistbot.models.statistic import Statistic, track_activity
from botlistbot.util import track_groups

log = logging.getLogger(__name__)


@track_activity("command", "start")
@track_groups
async def start(update, context):
    tg_user = update.message.from_user
    chat_id = tg_user.id

    # Get or create the user from/in database
    User.from_telegram_object(tg_user)

    if isinstance(context.args, list) and len(context.args) > 0:
        # CATEGORY BY ID
        try:
            cat = Category.get(Category.id == context.args[0])
            from botlistbot.components.explore import send_category

            return await send_category(update, context, cat)
        except (ValueError, Category.DoesNotExist):
            pass

        query = " ".join(context.args).lower()

        # SPECIFIC DEEP-LINKED QUERIES
        if query == const.DeepLinkingActions.CONTRIBUTING:
            return await help.contributing(update, context, quote=False)
        elif query == const.DeepLinkingActions.EXAMPLES:
            return await help.examples(update, context, quote=False)
        elif query == const.DeepLinkingActions.RULES:
            return await help.rules(update, context, quote=False)
        elif query == const.DeepLinkingActions.SEARCH:
            return await search_handler(update, context)

        # SEARCH QUERY
        await search_query(update, context, query)

    else:
        await context.bot.send_sticker(
            chat_id,
            open(
                os.path.join(
                    appglobals.ROOT_DIR, "assets", "sticker", "greetings-humanoids.webp"
                ),
                "rb",
            ),
        )
        await help.help(update, context)
        await util.wait(update, context)
        if util.is_private_message(update):
            await main_menu(update, context)
        return ConversationHandler.END


def main_menu_buttons(admin=False):
    buttons = [
        [
            KeyboardButton(captions.CATEGORIES),
            KeyboardButton(captions.EXPLORE),
            KeyboardButton(captions.FAVORITES),
        ],
        [KeyboardButton(captions.NEW_BOTS), KeyboardButton(captions.SEARCH)],
        [KeyboardButton(captions.HELP)],
    ]
    if admin:
        buttons.insert(1, [KeyboardButton(captions.ADMIN_MENU)])
    return buttons


@track_activity("menu", "main menu", Statistic.ANALYSIS)
async def main_menu(update, context):
    chat_id = update.effective_chat.id
    is_admin = chat_id in settings.MODERATORS
    reply_markup = (
        ReplyKeyboardMarkup(
            main_menu_buttons(is_admin), resize_keyboard=True, one_time_keyboard=True
        )
        if util.is_private_message(update)
        else ReplyKeyboardRemove()
    )

    await context.bot.send_message(
        chat_id,
        mdformat.action_hint("What would you like to do?"),
        reply_markup=reply_markup,
    )


@util.restricted
async def restart(update, context):
    chat_id = util.uid_from_update(update)
    os.kill(os.getpid(), signal.SIGINT)
    await context.bot.formatter.send_success(chat_id, "Bot is restarting...")
    time.sleep(0.3)
    os.execl(sys.executable, sys.executable, *sys.argv)


async def error(update, context):
    log.error(context.error)


@track_activity("remove", "keyboard")
async def remove_keyboard(update, context):
    await update.message.reply_text("Keyboard removed.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def delete_botlistchat_promotions(update, context):
    """
    TODO: don't think we need this anymore, it never worked. Nice idea, but no way to achieve it...
    """
    return
    cid = update.effective_chat.id

    if context.chat_data.get("delete_promotion_retries") >= 3:
        return

    if messages.PROMOTION_MESSAGE not in update.effective_message.text_markdown:
        return

    if update.effective_chat.id != settings.BOTLISTCHAT_ID:
        return

    sent_inlinequery = context.chat_data.get("sent_inlinequery")
    if sent_inlinequery:
        text = sent_inlinequery.text
        text = text.replace(messages.PROMOTION_MESSAGE, "")
        await context.bot.edit_message_text(text, cid, sent_inlinequery)
        del context.chat_data["sent_inlinequery"]
    else:
        context.chat_data["delete_promotion_retries"] += 1
        time.sleep(2)  # TODO


async def plaintext_group(update, context):
    # Handle channel posts (e.g. from @BotList channel) to sync bot data
    if update.channel_post:
        try:
            return await new_channel_post(update, context)
        except Exception as e:
            log.error(f"Error processing channel post: {e}")
            return

    msg: Message = update.effective_message
    if not msg or not msg.text:
        return


async def cancel(update, context):
    return ConversationHandler.END


def thank_you_markup(count=0):
    assert isinstance(count, int)
    count_caption = "" if count == 0 else mdformat.number_as_emoji(count)
    button = InlineKeyboardButton(
        "{} {}".format(messages.rand_thank_you_slang(), count_caption),
        callback_data=util.callback_for_action(
            const.CallbackActions.COUNT_THANK_YOU, {"count": count + 1}
        ),
    )
    return InlineKeyboardMarkup([[button]])


async def count_thank_you(update, context, count=0):
    assert isinstance(count, int)
    await update.effective_message.edit_reply_markup(reply_markup=thank_you_markup(count))


async def add_thank_you_button(update, context, cid, mid):
    await context.bot.edit_message_reply_markup(cid, mid, reply_markup=thank_you_markup(0))


async def ping(update, context):
    msg: Message = update.effective_message
    sent = await msg.reply_text("🏓 Pong!", quote=True)
    del_timeout = 4

    async def delete_msgs(ctx):
        await sent.delete()
        try:
            await msg.delete()
        except:
            pass

    context.job_queue.run_once(delete_msgs, del_timeout, name="delete ping pong messages")


@track_groups
async def all_handler(update, context):
    if update.message and update.message.new_chat_members:
        if int(settings.SELF_BOT_ID) in [x.id for x in update.message.new_chat_members]:
            # bot was added to a group
            await start(update, context)
    return ConversationHandler.END


def register(dp):
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", main_menu))
    dp.add_handler(MessageHandler(filters.Regex(captions.EXIT), main_menu))
    dp.add_handler(CommandHandler("r", restart))
    dp.add_error_handler(error)
    dp.add_handler(
        MessageHandler(
            filters.TEXT,
            plaintext_group,
        )
    )
    dp.add_handler(CommandHandler("removekeyboard", remove_keyboard))
    dp.add_handler(CommandHandler("ping", ping))
