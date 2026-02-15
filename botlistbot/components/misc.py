import binascii
import datetime
import os

from telegram.constants import ParseMode
from telegram.ext import ConversationHandler

from botlistbot import util
from botlistbot.models import Statistic, APIAccess
from botlistbot.models import User, Bot, Notifications
from botlistbot.util import restricted


@restricted(strict=True)
async def access_token(update, context):
    user = User.from_telegram_object(update.effective_user)
    rd_token = binascii.hexlify(os.urandom(32)).decode('utf-8')
    try:
        db_token = APIAccess.get(user=user).token
    except:
        db_token = "You have no token."
    text = "Random token: {}\n" \
           "Database token (use this for api calls):\n{}".format(rd_token, db_token)
    await update.message.reply_text(text)
    return ConversationHandler.END


async def credits(update, context):
    users_contrib = User.select().join(Bot)
    pass
    Bot.select(Bot.submitted_by)
    return ConversationHandler.END


async def t3chnostats(update, context):
    days = 30
    txt = 'Bots approved by other people *in the last {} days*:\n\n'.format(days)
    bots = Bot.select().where(
        (Bot.approved_by != User.get(User.chat_id == 918962)) &
        (Bot.date_added.between(
            datetime.date.today() - datetime.timedelta(days=days),
            datetime.date.today()
        ))
    )
    txt += '\n'.join(['{} by @{}'.format(str(b), b.approved_by.username) for b in bots])
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)


async def set_notifications(update, context, value: bool):
    cid = update.effective_chat.id
    try:
        notifications = Notifications.get(Notifications.chat_id == cid)
    except Notifications.DoesNotExist:
        notifications = Notifications(chat_id=cid)
    notifications.enabled = value
    notifications.save()

    Statistic.of(update, ('enabled' if value else 'disabled') + ' notifications for their group {}'.format(
        cid))

    msg = util.success("Nice! Notifications enabled.") if value else "Ok, notifications disabled."
    msg += '\nYou can always adjust this setting with the /subscribe command.'
    await context.bot.formatter.send_or_edit(cid, msg, to_edit=util.mid_from_update(update))
    return ConversationHandler.END
