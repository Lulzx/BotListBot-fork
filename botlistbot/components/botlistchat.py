import asyncio
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyMarkup,
)
from telegram.constants import ParseMode

from botlistbot import captions
from botlistbot import settings
from botlistbot import util
from botlistbot.const import CallbackActions
from botlistbot.dialog import messages
from botlistbot.models import track_activity, User
from typing import *
from logzero import logger as log

HINTS = {
    "#inline": {
        "message": "*Consider using me in inline-mode* 😎\n`@BotListBot {query}`",
        "default": "Your search terms",
        "buttons": [{"text": "🔎 Try it out", "switch_inline_query": "{query}"}],
        "help": "Give a query that will be used for a `switch_to_inline`-button",
        "should_reply": False,
    },
    "#rules": {
        "message": messages.BOTLISTCHAT_RULES,
        "help": "Send the rules of @BotListChat",
        "should_reply": False,
    },
    "#manybot": {
        "message": "The @BotList moderators aim to set a *high standard for bots on the* @BotList. "
        "Bots built with bot builders like @Manybot or @Chatfuelbot certainly have "
        "their place, but usually *lack the quality* we impose for inclusion to the "
        "list. We prefer when bot makers actually take their time and effort to "
        "program bots without using a sandbox kindergarten tool as the ones mentioned "
        "above. Don't get us wrong, there are great tools out there built with these "
        "bot builders, and if you feel like the BotList is lacking some feature that "
        "this bot brings, feel free to submit it. But as a rule of thumb, Manybots are "
        "*generally too spammy, not very useful and not worth another look*. "
        "\nThank you 🙏🏻",
        "help": "Send our Manybot policy",
        "should_reply": True,
    },
    "#private": {
        "message": "Please don't spam the group with {query}, and go to a private "
        "chat with me instead. Thanks a lot, the other members will appreciate it 😊",
        "default": "searches or commands",
        "buttons": [
            {
                "text": captions.SWITCH_PRIVATE,
                "url": "https://t.me/{}".format(settings.SELF_BOT_NAME),
            }
        ],
        "help": "Tell a member to stop spamming and switch to a private chat",
        "should_reply": True,
    },
    "#userbot": {
        "message": "Refer to [this article](http://telegra.ph/How-a-"
        "Userbot-superacharges-your-Telegram-Bot-07-09) to learn more about *Userbots*.",
        "help": "@JosXa's article about Userbots",
        "should_reply": True,
    },
    "#devlist": {
        "message": "There exists a list of developers at @Devlist where you can surely find someone to build your "
        "bot.\nNote that most of them expect some amount of payment for their services, but if your idea "
        "is good enough, maybe you can convince them that they're going to make life easier for the "
        "whole Telegram community. Good luck with your project!",
        "help": "Where to find a bot developer?",
        "should_reply": True,
    },
}


def append_restricted_delete_button(
    update, chat_data, reply_markup
) -> Tuple[Optional[ReplyMarkup], Callable[[Message], None]]:
    uid = update.effective_user.id
    command_mid = update.effective_message.message_id

    if not util.is_group_message(update) or not isinstance(
        reply_markup, InlineKeyboardMarkup
    ):
        return reply_markup, lambda _: None

    def append_callback(message):
        if message is None:  # No message was saved
            return
        if isinstance(message, Message):
            mid = message.message_id
        else:
            mid = message
        deletions_pending = chat_data.get("deletions_pending", dict())
        if not deletions_pending.get(mid):
            deletions_pending[mid] = dict(user_id=uid, command_id=command_mid)
            chat_data["deletions_pending"] = deletions_pending

    buttons = reply_markup.inline_keyboard
    buttons.append(
        [
            InlineKeyboardButton(
                captions.random_done_delete(),
                callback_data=util.callback_for_action(
                    CallbackActions.DELETE_CONVERSATION
                ),
            )
        ]
    )
    reply_markup.inline_keyboard = buttons
    return reply_markup, append_callback


def append_free_delete_button(update, reply_markup) -> Optional[ReplyMarkup]:
    if not util.is_group_message(update) or not isinstance(
        reply_markup, InlineKeyboardMarkup
    ):
        return reply_markup

    buttons = reply_markup.inline_keyboard
    buttons.append(
        [
            InlineKeyboardButton(
                captions.random_done_delete(),
                callback_data=util.callback_for_action(
                    CallbackActions.DELETE_CONVERSATION
                ),
            )
        ]
    )

    reply_markup.inline_keyboard = buttons
    return reply_markup


@track_activity("issued deletion of conversation in BotListChat")
async def delete_conversation(update, context):
    cid = update.effective_chat.id
    uid = update.effective_user.id
    mid = util.mid_from_update(update)

    deletions_pending = context.chat_data.get("deletions_pending", dict())
    ctx: Optional[dict] = deletions_pending.get(mid)

    if ctx and uid != ctx.get("user_id"):
        if uid not in settings.MODERATORS:
            await context.bot.answer_callback_query(
                update.callback_query.id, text="✋️ You didn't prompt this message."
            )
            return

    await context.bot.delete_message(cid, mid)
    await context.bot.delete_message(cid, ctx["command_id"])


BROADCAST_REPLACEMENTS = {"categories": "📚 ᴄᴀᴛɢᴏʀɪᴇs", "bots": "🤖 *bots*", "- ": "👉 "}


async def _delete_multiple_delayed(context_bot, chat_id, immediately=None, delayed=None):
    if immediately is None:
        immediately = []
    if delayed is None:
        delayed = []

    for mid in immediately:
        await context_bot.delete_message(chat_id, mid)

    await asyncio.sleep(1.5)

    for mid in delayed:
        await context_bot.delete_message(chat_id, mid)


async def show_available_hints(update, context):
    message = "In @BotListChat, you can use the following hashtag hints to guide new members:\n\n"
    parts = []
    for k, v in HINTS.items():
        query_appendix = f" _text_" if v.get("default") else ""
        parts.append(f"🗣 {k}{query_appendix} ➖ {v['help']}")

    message += "\n".join(parts)

    message += "\n\nMake sure to reply to another message, so the person knows they're being referred to."
    await update.effective_message.reply_text(
        message, parse_mode="markdown", disable_web_page_preview=True
    )


def get_hint_data(text):
    for k, v in HINTS.items():
        if k not in text:
            continue

        text = text.replace(k, "")
        query = text.strip()

        reply_markup = None
        if v.get("buttons"):
            # Replace 'query' placeholder and expand kwargs
            buttons = [
                InlineKeyboardButton(**{k: v.format(query=query) for k, v in b.items()})
                for b in v.get("buttons")
            ]
            reply_markup = InlineKeyboardMarkup(util.build_menu(buttons, 1))

        msg = v["message"].format(
            query=query if query else v["default"] if v.get("default") else ""
        )
        return msg, reply_markup, k
    return None, None, None


async def hint_handler(update, context):
    chat_id = update.message.chat_id
    if not util.is_group_message(update):
        return
    text = update.message.text
    reply_to = update.message.reply_to_message
    user = User.from_update(update)
    msg, reply_markup, hashtag = get_hint_data(text)

    async def _send_hint(hint_text):
        if hint_text is None:
            return
        if reply_to:
            hint_text = f"{user.markdown_short} hints: {hint_text}"

        await context.bot.formatter.send_message(
            chat_id,
            hint_text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to.message_id if reply_to else None,
        )
        await update.effective_message.delete()

    should_reply: bool = HINTS.get(hashtag)["should_reply"]
    if should_reply and not reply_to:
        del_markup = append_free_delete_button(update, InlineKeyboardMarkup([[]]))
        await _send_hint(msg)
        ntfc_msg = await update.effective_message.reply_text(
            f"Hey {user.markdown_short}, next time reply to someone 🙃",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=del_markup,
            quote=False,
            disable_web_page_preview=True,
        )
        context.job_queue.run_once(lambda *_: ntfc_msg.delete(), 7, name="delete notification")
    else:
        await _send_hint(msg)


async def notify_group_submission_accepted(update, context, accepted_bot):
    pass  # upon @T3CHNO's request :((((


async def text_message_logger(update, context, logger):
    pass
