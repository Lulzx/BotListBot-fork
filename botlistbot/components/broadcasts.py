import re
from pprint import pprint

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler

from botlistbot import captions
from botlistbot import const
from botlistbot import mdformat
from botlistbot import settings
from botlistbot import util
from botlistbot.components import errors
from botlistbot.components.botlistchat import BROADCAST_REPLACEMENTS, _delete_multiple_delayed
from botlistbot.const import BotStates
from botlistbot.models import User
from botlistbot.util import restricted


@restricted
async def pin_message(update, context, message_id):
    cid = update.effective_chat.id
    try:
        await context.bot.pin_chat_message(cid, message_id, False)
    except:
        await errors.no_library_support(update, context)


@restricted
async def broadcast(update, context):
    cid = update.effective_chat.id
    uid = update.effective_user.id
    mid = util.mid_from_update(update)
    user = User.from_update(update)
    text = ''

    if cid == settings.BOTLISTCHAT_ID:
        replied_to = update.message.reply_to_message
        if replied_to:
            context.user_data['broadcast'] = dict(context.user_data.get('broadcast', dict()), reply_to_message_id=replied_to.message_id)
            if replied_to.from_user.username.lower() == settings.SELF_BOT_NAME:
                # editing
                text += '*You are editing one of my messages*\n\n'
                context.user_data['broadcast']['mode'] = 'editing'
            else:
                # replying
                text += '*You are replying to a message of {}.*\n\n'.format(
                    update.message.reply_to_message.from_user.first_name
                )
                context.user_data['broadcast']['mode'] = 'replying'
        # answer and clean
        msg = await context.bot.send_message(cid, "k")
        await _delete_multiple_delayed(context.bot, cid, delayed=[msg.message_id], immediately=[update.message.message_id])

    to_text = "  _to_  "
    text += "Send me the text to broadcast to @BotListChat.\n"
    text += "_You can use the following words and they will replaced:_\n\n"

    text += '\n'.join(['"{}"{}{}'.format(k, to_text, v) for k, v in BROADCAST_REPLACEMENTS.items()])

    await context.bot.formatter.send_or_edit(uid, mdformat.action_hint(text), mid)
    return BotStates.BROADCASTING


@restricted
async def broadcast_preview(update, context):
    uid = update.effective_user.id

    formatted_text = update.message.text_markdown
    for k, v in BROADCAST_REPLACEMENTS.items():
        # replace all occurences but mind escaping with \
        pattern = re.compile(r"(?<!\\){}".format(k), re.IGNORECASE)
        formatted_text = pattern.sub(v, formatted_text)
        formatted_text = re.sub(r"\\({})".format(k), r"\1", formatted_text, re.IGNORECASE)

    context.user_data['broadcast'] = dict(context.user_data.get('broadcast', dict()),
                                  **dict(text=formatted_text, target_chat_id=settings.BOTLISTCHAT_ID))
    mode = context.user_data['broadcast'].get('mode', 'just_send')

    buttons = [
        InlineKeyboardButton("Type again", callback_data=util.callback_for_action('broadcast')),
        InlineKeyboardButton("📝 Edit my message" if mode == 'editing' else "▶️ Send to @BotListChat",
                             callback_data=util.callback_for_action('send_broadcast',
                                                                    {'P4l': settings.BOTLISTCHAT_ID})),
    ]

    reply_markup = InlineKeyboardMarkup(util.build_menu(buttons, 1))
    await util.send_md_message(context.bot, uid, formatted_text, reply_markup=reply_markup)
    return ConversationHandler.END


@restricted
async def send_broadcast(update, context):
    uid = update.effective_user.id

    try:
        bc = context.user_data['broadcast']
        text = bc['text']
        recipient = bc['target_chat_id']
        mode = bc.get('mode', 'just_send')
    except AttributeError:
        await context.bot.formatter.send_failure(uid, "Missing attributes for broadcast. Aborting...")
        return ConversationHandler.END

    mid = bc.get('reply_to_message_id')

    if mode == 'replying':
        msg = await util.send_md_message(context.bot, recipient, text, reply_to_message_id=mid)
    elif mode == 'editing':
        msg = await context.bot.formatter.send_or_edit(recipient, text, to_edit=mid)
    else:
        msg = await util.send_md_message(context.bot, recipient, text)

    # Post actions
    buttons = [
        InlineKeyboardButton(captions.PIN,
                             callback_data=util.callback_for_action('pin_message', {'mid': msg.message_id})),
        InlineKeyboardButton('Add "Thank You" counter',
                             callback_data=util.callback_for_action('add_thank_you',
                                                                    {'cid': recipient, 'mid': msg.message_id})),
    ]
    reply_markup = InlineKeyboardMarkup(util.build_menu(buttons, 1))
    mid = util.mid_from_update(update)
    action_taken = "edited" if mode == 'editing' else "broadcasted"
    await context.bot.formatter.send_or_edit(uid, mdformat.success("Message {}.".format(action_taken)), mid, reply_markup=reply_markup)
