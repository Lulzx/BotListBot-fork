from botlistbot import captions
from botlistbot import const
from botlistbot import helpers
from botlistbot import settings
from botlistbot import util
from botlistbot.dialog import messages
from botlistbot.helpers import reroute_private_chat
from telegram import InlineKeyboardButton
from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ConversationHandler

from botlistbot.models import track_activity
from botlistbot.util import track_groups


async def available_commands(update, context):
    await update.message.reply_text('*Available commands:*\n' + helpers.get_commands(), parse_mode=ParseMode.MARKDOWN)


@track_groups
@track_activity('command', 'help')
async def help(update, context):
    mid = util.mid_from_update(update)
    cid = update.effective_chat.id
    await context.bot.formatter.send_or_edit(cid, messages.HELP_MESSAGE_ENGLISH, to_edit=mid, reply_markup=_help_markup())
    return ConversationHandler.END


@track_activity('command', 'contributing')
async def contributing(update, context, quote=True):
    mid = util.mid_from_update(update)
    cid = update.effective_chat.id
    await context.bot.formatter.send_or_edit(cid, messages.CONTRIBUTING, to_edit=mid, reply_markup=_help_markup())
    return ConversationHandler.END


@track_activity('command', 'examples')
async def examples(update, context, quote=True):
    mid = util.mid_from_update(update)
    cid = update.effective_chat.id
    await context.bot.formatter.send_or_edit(cid, messages.EXAMPLES, to_edit=mid, reply_markup=_help_markup())
    return ConversationHandler.END


@track_activity('command', 'rules')
async def rules(update, context, quote=True):
    chat_id = update.effective_chat.id
    if chat_id == settings.BOTLISTCHAT_ID or util.is_private_message(update):
        await reroute_private_chat(update, context, quote, const.DeepLinkingActions.RULES, messages.BOTLISTCHAT_RULES)
    else:
        await update.message.reply_text("Sorry, but I don't know the rules in this group 👻\n\n" + messages.PROMOTION_MESSAGE,
                                  parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


def _help_markup():
    buttons = [[
        InlineKeyboardButton(captions.HELP, callback_data=util.callback_for_action(const.CallbackActions.HELP)),
        InlineKeyboardButton(captions.CONTRIBUTING,
                             callback_data=util.callback_for_action(const.CallbackActions.CONTRIBUTING)),
        InlineKeyboardButton(captions.EXAMPLES, callback_data=util.callback_for_action(const.CallbackActions.EXAMPLES)),
    ], [
        InlineKeyboardButton('Try me inline!', switch_inline_query_current_chat='')
    ]]
    return InlineKeyboardMarkup(buttons)
