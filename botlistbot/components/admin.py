import datetime
from pathlib import Path

import emoji
import os
import re
from logzero import logger as log
from peewee import fn
from telegram import (
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    TelegramError,
)
from telegram.ext import ConversationHandler
from typing import Dict

from botlistbot import appglobals
from botlistbot import captions
from botlistbot import helpers
from botlistbot import mdformat
from botlistbot import settings
from botlistbot import util
from botlistbot.appglobals import db
from botlistbot.components.lookup import lookup_entity
from botlistbot.const import *
from botlistbot.const import BotStates, CallbackActions
from botlistbot.custemoji import Emoji
from botlistbot.dialog import messages, emojis
from botlistbot.models import Bot, Category, Revision, Statistic, Suggestion, User, track_activity
from botlistbot.util import restricted


@track_activity("menu", "Administration", Statistic.ANALYSIS)
@restricted
async def menu(update, context):
    uid = update.effective_user.id

    is_admin = uid in settings.ADMINS
    buttons = _admin_buttons(send_botlist_button=is_admin, logs_button=is_admin)

    txt = "🛃 Administration menu. Current revision: {}".format(
        Revision.get_instance().nr
    )
    await context.bot.formatter.send_message(
        uid, txt, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return BotStates.ADMIN_MENU


def _admin_buttons(send_botlist_button=False, logs_button=False):
    n_unapproved = len(Bot.select().where(Bot.approved == False, Bot.disabled == False))
    n_suggestions = len(Suggestion.select_all())
    n_pending = len(Bot.select_pending_update())

    second_row = list()
    if n_unapproved > 0:
        second_row.append(
            KeyboardButton(
                captions.APPROVE_BOTS
                + " {}🆕".format(mdformat.number_as_emoji(n_unapproved))
            )
        )
    if n_suggestions > 0:
        second_row.append(
            KeyboardButton(
                captions.APPROVE_SUGGESTIONS
                + " {}⁉️".format(mdformat.number_as_emoji(n_suggestions))
            )
        )

    buttons = [
        [KeyboardButton(captions.EXIT), KeyboardButton(captions.REFRESH)],
        [
            KeyboardButton(captions.FIND_OFFLINE),
            KeyboardButton(captions.SEND_CONFIG_FILES),
        ],
    ]

    update_row = list()
    if n_pending > 0:
        update_row.append(
            KeyboardButton(
                captions.PENDING_UPDATE
                + " {}{}".format(
                    mdformat.number_as_emoji(n_pending),
                    captions.SUGGESTION_PENDING_EMOJI,
                )
            )
        )
    if send_botlist_button:
        update_row.append(KeyboardButton(captions.SEND_BOTLIST))
    if logs_button:
        update_row.append(KeyboardButton(captions.SEND_ACTIVITY_LOGS))

    if len(update_row) > 0:
        buttons.insert(1, update_row)
    if len(second_row) > 0:
        buttons.insert(1, second_row)

    return buttons


@restricted
async def _input_failed(update, context, text):
    chat_id = util.uid_from_update(update)
    await context.bot.formatter.send_failure(chat_id, text)
    Statistic.of(
        update,
        "error",
        "input failed in admin menu for {}".format(text),
        Statistic.ANALYSIS,
    )
    context.chat_data["add_bot_message"] = None


def _add_bot_to_chatdata(chat_data, category=None):
    new_bot = Bot(category=category)
    chat_data["add_bot"] = new_bot


def format_pending(text):
    return "{} {}".format(captions.SUGGESTION_PENDING_EMOJI, text)


def _edit_bot_buttons(to_edit: Bot, pending_suggestions: Dict, is_moderator):
    bid = {"id": to_edit.id}

    def is_pending(action):
        if isinstance(action, str):
            return action in pending_suggestions
        else:
            return any(a in pending_suggestions for a in action)

    def pending_or_caption(action, caption):
        return (
            format_pending(str(pending_suggestions[action]))
            if is_pending(action)
            else str(caption)
        )

    buttons = [
        InlineKeyboardButton(
            pending_or_caption("name", to_edit.name or "Set Name"),
            callback_data=util.callback_for_action(CallbackActions.EDIT_BOT_NAME, bid),
        ),
        InlineKeyboardButton(
            pending_or_caption("username", to_edit.username),
            callback_data=util.callback_for_action(
                CallbackActions.EDIT_BOT_USERNAME, bid
            ),
        ),
        InlineKeyboardButton(
            # remove bulletin from category
            pending_or_caption(
                "category",
                str(pending_suggestions.get("category") or to_edit.category)[1:]
                if to_edit.category
                else "Choose a category",
            ),
            callback_data=util.callback_for_action(
                CallbackActions.EDIT_BOT_SELECT_CAT, bid
            ),
        ),
        InlineKeyboardButton(
            pending_or_caption(
                "description",
                "Change description" if to_edit.description else "Write a description",
            ),
            callback_data=util.callback_for_action(
                CallbackActions.EDIT_BOT_DESCRIPTION, bid
            ),
        ),
        InlineKeyboardButton(
            pending_or_caption(
                "country",
                to_edit.country.emojized if to_edit.country else "Set country/language",
            ),
            callback_data=util.callback_for_action(
                CallbackActions.EDIT_BOT_COUNTRY, bid
            ),
        ),
        InlineKeyboardButton(
            pending_or_caption(
                "extra", "Change extra text" if to_edit.extra else "Add an extra text"
            ),
            callback_data=util.callback_for_action(CallbackActions.EDIT_BOT_EXTRA, bid),
        ),
        InlineKeyboardButton(
            format_pending("Set keywords")
            if is_pending(["add_keyword", "remove_keyword"])
            else "Set keywords",
            callback_data=util.callback_for_action(
                CallbackActions.EDIT_BOT_KEYWORDS, bid
            ),
        ),
    ]

    toggleable_properties = [
        ("inlinequeries", "🔎", CallbackActions.EDIT_BOT_INLINEQUERIES),
        ("official", "🔹", CallbackActions.EDIT_BOT_OFFICIAL),
        # ('offline', '💤', CallbackActions.EDIT_BOT_OFFLINE),
        ("spam", "🚮", CallbackActions.EDIT_BOT_SPAM),
    ]

    def toggle_button(property_name, emoji, callback_action):
        is_pending = property_name in pending_suggestions.keys()
        pending_emoji = captions.SUGGESTION_PENDING_EMOJI + " " if is_pending else ""
        active = (
            bool(pending_suggestions[property_name])
            if is_pending
            else bool(getattr(to_edit, property_name))
        )
        active_emoji = "✔️" if active else Emoji.HEAVY_MULTIPLICATION_X
        caption = "{}{} {}".format(pending_emoji, emoji, active_emoji)
        return InlineKeyboardButton(
            caption,
            callback_data=util.callback_for_action(
                callback_action, {"id": to_edit.id, "value": not active}
            ),
        )

    for toggle in toggleable_properties:
        buttons.append(toggle_button(*toggle))

    if is_moderator:
        buttons.append(
            InlineKeyboardButton(
                "Delete",
                callback_data=util.callback_for_action(
                    CallbackActions.CONFIRM_DELETE_BOT, bid
                ),
            )
        )

    header = []
    if to_edit.category:
        header.append(
            InlineKeyboardButton(
                captions.BACK_TO_CATEGORY,
                callback_data=util.callback_for_action(
                    CallbackActions.SELECT_BOT_FROM_CATEGORY,
                    {"id": to_edit.category.id},
                ),
            )
        )
    header.append(
        InlineKeyboardButton(
            captions.REFRESH,
            callback_data=util.callback_for_action(
                CallbackActions.EDIT_BOT, {"id": to_edit.id}
            ),
        )
    )

    footer = list()
    if is_moderator and len(pending_suggestions) > 0:
        footer.append(
            InlineKeyboardButton(
                "🛃 Apply all changes",
                callback_data=util.callback_for_action(
                    CallbackActions.APPLY_ALL_CHANGES, {"id": to_edit.id}
                ),
            )
        )

    return util.build_menu(
        buttons, n_cols=2, header_buttons=header, footer_buttons=footer
    )


@track_activity("menu", "bot editing", Statistic.ANALYSIS)
async def edit_bot(update, context, to_edit=None):
    uid = util.uid_from_update(update)
    message_id = util.mid_from_update(update)
    user = User.from_update(update)

    if not to_edit:
        if update.message:
            command = update.message.text

            if "edit" in command:
                b_id = re.match(r"^/edit(\d+)$", command).groups()[0]
            elif "approve" in command:
                b_id = re.match(r"^/approve(\d+)$", command).groups()[0]
            else:
                raise ValueError("No 'edit' or 'approve' in command.")

            try:
                to_edit = Bot.get(id=b_id)
            except Bot.DoesNotExist:
                await update.message.reply_text(util.failure("No bot exists with this id."))
                return
        else:
            await context.bot.formatter.send_failure(uid, "An unexpected error occured.")
            return

    # if not to_edit.approved:
    #     return approve_bots(update, context, override_list=[to_edit])

    pending_suggestions = Suggestion.pending_for_bot(to_edit, user)
    reply_markup = InlineKeyboardMarkup(
        _edit_bot_buttons(to_edit, pending_suggestions, uid in settings.MODERATORS)
    )
    pending_text = (
        "\n\n{} Some changes are pending approval{}.".format(
            captions.SUGGESTION_PENDING_EMOJI,
            "" if user.chat_id in settings.MODERATORS else " by a moderator",
        )
        if pending_suggestions
        else ""
    )
    meta_text = (
        "\n\nDate added: {}\nMember since revision {}\n"
        "Submitted by {}\nApproved by {}".format(
            to_edit.date_added,
            to_edit.revision,
            to_edit.submitted_by,
            to_edit.approved_by,
        )
    )
    await context.bot.formatter.send_or_edit(
        uid,
        "🛃 Edit {}{}{}".format(
            to_edit.detail_text,
            meta_text if user.id in settings.MODERATORS else "",
            pending_text,
        ),
        to_edit=message_id,
        reply_markup=reply_markup,
    )


@restricted(strict=True)
async def prepare_transmission(update, context):
    chat_id = util.uid_from_update(update)
    await pending_update(update, context)
    text = mdformat.action_hint("Notify subscribers about this update?")
    reply_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "☑ Notifications",
                    callback_data=util.callback_for_action(
                        CallbackActions.SEND_BOTLIST, {"silent": False}
                    ),
                ),
                InlineKeyboardButton(
                    "Silent",
                    callback_data=util.callback_for_action(
                        CallbackActions.SEND_BOTLIST, {"silent": True}
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    "Re-send all Messages",
                    callback_data=util.callback_for_action(
                        CallbackActions.SEND_BOTLIST, {"silent": True, "re": True}
                    ),
                )
            ],
        ]
    )

    # # TODO
    # text = "Temporarily disabled"
    # reply_markup = None

    await util.send_md_message(context.bot, chat_id, text, reply_markup=reply_markup)


@track_activity("menu", "approve suggestions", Statistic.ANALYSIS)
@restricted
async def approve_suggestions(update, context, page=0):
    uid = util.uid_from_update(update)
    suggestions = Suggestion.select_all()
    if page * settings.PAGE_SIZE_SUGGESTIONS_LIST >= len(suggestions):
        # old item deleted, list now too small
        page = page - 1 if page > 0 else 0
    start = page * settings.PAGE_SIZE_SUGGESTIONS_LIST
    end = start + settings.PAGE_SIZE_SUGGESTIONS_LIST

    has_prev_page = page > 0
    has_next_page = (page + 1) * settings.PAGE_SIZE_SUGGESTIONS_LIST < len(suggestions)

    suggestions = suggestions[start:end]

    if len(suggestions) == 0:
        await context.bot.formatter.send_or_edit(
            uid, "No more suggestions available.", to_edit=util.mid_from_update(update)
        )
        return

    buttons = []
    count = 1
    text = "Please choose suggestions to accept.\n"
    for x in suggestions:
        number = str(count) + "."
        text += "\n{} {}".format(number, str(x))
        row = []

        # Should the suggestion be editable and is it too long?
        if x.action in Suggestion.TEXTUAL_ACTIONS:
            row.append(
                InlineKeyboardButton(
                    "{} {}📝".format(number, Emoji.WHITE_HEAVY_CHECK_MARK),
                    callback_data=util.callback_for_action(
                        CallbackActions.CHANGE_SUGGESTION, {"id": x.id, "page": page}
                    ),
                )
            )
        else:
            row.append(
                InlineKeyboardButton(
                    "{} {}".format(number, Emoji.WHITE_HEAVY_CHECK_MARK),
                    callback_data=util.callback_for_action(
                        CallbackActions.ACCEPT_SUGGESTION, {"id": x.id, "page": page}
                    ),
                )
            )

        row.append(
            InlineKeyboardButton(
                "{} {}".format(number, Emoji.CROSS_MARK),
                callback_data=util.callback_for_action(
                    CallbackActions.REJECT_SUGGESTION, {"id": x.id, "page": page}
                ),
            )
        )
        buttons.append(row)
        count += 1

    page_arrows = list()
    if has_prev_page:
        page_arrows.append(
            InlineKeyboardButton(
                Emoji.LEFTWARDS_BLACK_ARROW,
                callback_data=util.callback_for_action(
                    CallbackActions.SWITCH_SUGGESTIONS_PAGE, {"page": page - 1}
                ),
            )
        )
    if has_next_page:
        page_arrows.append(
            InlineKeyboardButton(
                Emoji.BLACK_RIGHTWARDS_ARROW,
                callback_data=util.callback_for_action(
                    CallbackActions.SWITCH_SUGGESTIONS_PAGE, {"page": page + 1}
                ),
            )
        )
    buttons.append(page_arrows)

    reply_markup = InlineKeyboardMarkup(buttons)

    await context.bot.formatter.send_or_edit(
        uid,
        util.action_hint(text),
        reply_markup=reply_markup,
        to_edit=util.mid_from_update(update),
        disable_web_page_preview=True,
    )
    return CallbackStates.APPROVING_BOTS


@track_activity("menu", "approve bots", Statistic.ANALYSIS)
@restricted
async def approve_bots(update, context, page=0, override_list=None):
    chat_id = util.uid_from_update(update)

    if override_list:
        unapproved = override_list
    else:
        unapproved = (
            Bot.select()
            .where(Bot.approved == False, Bot.disabled == False)
            .order_by(Bot.date_added)
        )

    if page < 0:
        page = 0

    last_page = int((len(unapproved) - 1) / settings.PAGE_SIZE_BOT_APPROVAL)

    if page * settings.PAGE_SIZE_BOT_APPROVAL >= len(unapproved):
        # old item deleted, list now too small
        page = last_page
    start = page * settings.PAGE_SIZE_BOT_APPROVAL
    end = start + settings.PAGE_SIZE_BOT_APPROVAL

    has_prev_page = page > 0
    has_next_page = (page + 1) * settings.PAGE_SIZE_BOT_APPROVAL < len(unapproved)
    unapproved = unapproved[start:end]

    if len(unapproved) == 0:
        await context.bot.formatter.send_or_edit(
            chat_id,
            "No more unapproved bots available. "
            "Good job! (Is this the first time? 😂)",
            to_edit=util.mid_from_update(update),
        )
        return

    buttons = list()
    for x in unapproved:
        first_row = [
            InlineKeyboardButton(
                x.username, url="http://t.me/{}".format(x.username[1:])
            )
        ]
        second_row = [
            InlineKeyboardButton(
                "👍",
                callback_data=util.callback_for_action(
                    CallbackActions.ACCEPT_BOT, {"id": x.id}
                ),
            ),
            InlineKeyboardButton(
                "👎",
                callback_data=util.callback_for_action(
                    CallbackActions.REJECT_BOT, {"id": x.id, "page": page, "ntfc": True}
                ),
            ),
            InlineKeyboardButton(
                "🗑",
                callback_data=util.callback_for_action(
                    CallbackActions.REJECT_BOT,
                    {"id": x.id, "page": page, "ntfc": False},
                ),
            ),
            InlineKeyboardButton(
                emojis.RECOMMEND_MODERATOR,
                callback_data=util.callback_for_action(
                    CallbackActions.RECOMMEND_MODERATOR, {"id": x.id, "page": page}
                ),
            ),
        ]
        if len(unapproved) > 1:
            buttons.append(first_row)
        buttons.append(second_row)

    page_arrows = list()
    if has_prev_page:
        page_arrows.append(
            InlineKeyboardButton(
                "⏮",
                callback_data=util.callback_for_action(
                    CallbackActions.SWITCH_APPROVALS_PAGE, {"page": -1}
                ),
            )
        )
        page_arrows.append(
            InlineKeyboardButton(
                Emoji.LEFTWARDS_BLACK_ARROW,
                callback_data=util.callback_for_action(
                    CallbackActions.SWITCH_APPROVALS_PAGE, {"page": page - 1}
                ),
            )
        )

    if has_prev_page or has_next_page:
        page_arrows.append(
            InlineKeyboardButton(
                "·{}·".format(page + 1),
                callback_data=util.callback_for_action(
                    CallbackActions.SWITCH_APPROVALS_PAGE, {"page": page}
                ),
            )
        )

    if has_next_page:
        page_arrows.append(
            InlineKeyboardButton(
                Emoji.BLACK_RIGHTWARDS_ARROW,
                callback_data=util.callback_for_action(
                    CallbackActions.SWITCH_APPROVALS_PAGE, {"page": page + 1}
                ),
            )
        )
        page_arrows.append(
            InlineKeyboardButton(
                "⏭",
                callback_data=util.callback_for_action(
                    CallbackActions.SWITCH_APPROVALS_PAGE, {"page": last_page}
                ),
            )
        )
    buttons.append(page_arrows)

    reply_markup = InlineKeyboardMarkup(buttons)
    text = (
        "What to do with {}?".format(util.escape_markdown(unapproved[0].username))
        if len(unapproved) == 1
        else messages.SELECT_BOT_TO_ACCEPT
    )
    await context.bot.formatter.send_or_edit(
        chat_id,
        util.action_hint(text),
        reply_markup=reply_markup,
        to_edit=util.mid_from_update(update),
    )
    return CallbackStates.APPROVING_BOTS


@track_activity("menu", "recommend moderator", Statistic.DETAILED)
async def recommend_moderator(update, context, bot_in_question, page):
    uid = update.effective_user.id
    mid = util.mid_from_update(update)
    moderators = User.select().where(
        (User.chat_id << settings.MODERATORS) & (User.chat_id != uid)
    )
    buttons = [
        InlineKeyboardButton(
            u.first_name,
            callback_data=util.callback_for_action(
                CallbackActions.SELECT_MODERATOR,
                {"bot_id": bot_in_question.id, "uid": u.id, "page": page},
            ),
        )
        for u in moderators
    ]
    buttons.insert(
        0,
        InlineKeyboardButton(
            captions.BACK,
            callback_data=util.callback_for_action(
                CallbackActions.SWITCH_APPROVALS_PAGE, {"page": page}
            ),
        ),
    )
    reply_markup = InlineKeyboardMarkup(util.build_menu(buttons, 1))
    text = mdformat.action_hint(
        "Select a moderator you think is better suited to evaluate the submission of {}.".format(
            str(bot_in_question)
        )
    )
    await context.bot.formatter.send_or_edit(uid, text, to_edit=mid, reply_markup=reply_markup)


async def share_with_moderator(update, context, bot_in_question, moderator):
    user = User.from_update(update)

    buttons = [
        [
            InlineKeyboardButton(
                "Yea, let me take this one!",
                callback_data=util.callback_for_action(
                    CallbackActions.APPROVE_REJECT_BOTS, {"id": bot_in_question.id}
                ),
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    text = "{} thinks that you have the means to inspect this bot submission:\n▶️ {}".format(
        user.markdown_short, bot_in_question
    )
    try:
        await util.send_md_message(
            context.bot,
            moderator.chat_id,
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
        answer_text = mdformat.success(
            "I will ask {} to have a look at this submission.".format(
                moderator.plaintext
            )
        )
    except Exception as e:
        answer_text = mdformat.failure(f"Could not contact {moderator.plaintext}: {e}")

    if update.callback_query:
        await update.callback_query.answer(text=answer_text)

    Statistic.of(
        update,
        "share",
        "submission {} with {}".format(bot_in_question.username, moderator.plaintext),
    )


@track_activity("menu", "edit bot category", Statistic.DETAILED)
async def edit_bot_category(update, context, for_bot, callback_action=None):
    if callback_action is None:
        callback_action = CallbackActions.EDIT_BOT_CAT_SELECTED
    uid = util.uid_from_update(update)
    categories = Category.select().order_by(Category.name.asc()).execute()

    buttons = util.build_menu(
        [
            InlineKeyboardButton(
                "{}{}".format(emoji.emojize(c.emojis, language='alias'), c.name),
                callback_data=util.callback_for_action(
                    callback_action, {"cid": c.id, "bid": for_bot.id}
                ),
            )
            for c in categories
        ],
        2,
    )
    return await context.bot.formatter.send_or_edit(
        uid,
        util.action_hint(
            "Please select a category" + (" for {}".format(for_bot) if for_bot else "")
        ),
        to_edit=util.mid_from_update(update),
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@restricted
async def accept_bot_submission(update, context, of_bot: Bot, category):
    uid = util.uid_from_update(update)
    message_id = util.mid_from_update(update)
    user = User.from_update(update)

    try:
        of_bot.category = category
        of_bot.date_added = datetime.date.today()
        of_bot.approved = True
        of_bot.approved_by = user
        of_bot.save()

        buttons = [
            [
                InlineKeyboardButton(
                    "Edit {} details".format(of_bot.username),
                    callback_data=util.callback_for_action(
                        CallbackActions.EDIT_BOT, {"id": of_bot.id}
                    ),
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        await context.bot.formatter.send_or_edit(
            uid,
            "{} has been accepted to the Botlist. ".format(
                of_bot
            ),
            to_edit=message_id,
            reply_markup=reply_markup,
        )

        log_msg = "{} accepted by {}.".format(of_bot.username, uid)

        # notify submittant
        if of_bot.submitted_by != user:
            try:
                await context.bot.send_message(
                    of_bot.submitted_by.chat_id,
                    util.success(
                        messages.ACCEPTANCE_PRIVATE_MESSAGE.format(
                            of_bot.username, of_bot.category
                        )
                    ),
                )
                log_msg += "\nUser {} was notified.".format(str(of_bot.submitted_by))
            except TelegramError:
                log_msg += "\nUser {} could NOT be contacted/notified in private.".format(
                    str(of_bot.submitted_by)
                )

        log.info(log_msg)
    except:
        await context.bot.formatter.send_failure(uid, "An error has occured. Bot not added.")


@track_activity("request", "list of offline bots")
async def send_offline(update, context):
    chat_id = util.uid_from_update(update)
    offline = (
        Bot.select()
        .where(Bot.offline == True, Bot.disabled == False)
        .order_by(Bot.last_response.asc())
    )

    def offline_since(b):
        if not b.last_response:
            return "a long time"
        slanged_time = helpers.slang_datetime(b.last_response)
        return slanged_time.replace(" ago", "")

    if len(offline) > 0:
        text = "Offline Bots:\n\n"
        text += "\n".join(
            [
                "{}{} — /edit{}".format(
                    str(b), " (for {})".format(offline_since(b)), b.id
                )
                for b in offline
            ]
        )
    else:
        text = "No bots are offline."
    await context.bot.formatter.send_message(chat_id, text)


@restricted
async def reject_bot_submission(
    update,
    context,
    to_reject=None,
    verbose=True,
    notify_submittant=True,
    reason=None,
):
    uid = util.uid_from_update(update)
    user = User.from_update(update)

    if to_reject is None:
        if not update.message.reply_to_message:
            await context.bot.send_message(
                update.effective_user.id,
                util.failure("You must reply to a message of mine."),
            )
            return

        text = update.message.reply_to_message.text
        reason = reason if reason else (" ".join(context.args) if context.args else None)

        try:
            await update.message.delete()
        except:
            pass

        username = helpers.find_bots_in_text(text, first=True)
        if not username:
            await context.bot.send_message(
                update.effective_user.id,
                util.failure("No username in the message that you replied to."),
            )
            return

        try:
            to_reject = Bot.by_username(username)
        except Bot.DoesNotExist:
            await context.bot.send_message(
                update.effective_user.id,
                util.failure(
                    "Rejection failed: {} is not present in the "
                    "database.".format(username)
                ),
            )
            return

        if to_reject.approved is True:
            msg = "{} has already been accepted, so it cannot be rejected anymore.".format(
                username
            )
            await context.bot.send_message(uid, util.failure(msg))
            return

    Statistic.of(update, "reject", to_reject.username)
    text = await notify_submittant_rejected(context.bot, user, notify_submittant, reason, to_reject)
    to_reject.delete_instance()

    if verbose:
        await context.bot.send_message(uid, text)

    if update.callback_query:
        await update.callback_query.answer(text=text)


async def notify_submittant_rejected(bot, admin_user, notify_submittant, reason, to_reject):
    notification_successful = False
    msg = "{} rejected by {}.".format(to_reject.username, admin_user)
    if notify_submittant or reason:
        try:
            if reason:
                await bot.send_message(
                    to_reject.submitted_by.chat_id,
                    util.failure(
                        messages.REJECTION_WITH_REASON.format(
                            to_reject.username, reason=reason
                        )
                    ),
                )
            else:
                await bot.send_message(
                    to_reject.submitted_by.chat_id,
                    util.failure(
                        messages.REJECTION_PRIVATE_MESSAGE.format(to_reject.username)
                    ),
                )
            msg += "\nUser {} was notified.".format(str(to_reject.submitted_by))
            notification_successful = True
        except TelegramError:
            msg += "\nUser {} could NOT be contacted/notified in private.".format(
                str(to_reject.submitted_by)
            )
            notification_successful = False

    text = util.success("{} rejected.".format(to_reject.username))
    if notification_successful is True:
        text += " User {} was notified.".format(to_reject.submitted_by.plaintext)
    elif notification_successful is False:
        try:
            text += " " + mdformat.failure(
                "Could not contact {}.".format(to_reject.submitted_by.plaintext)
            )
        except:
            pass
    else:
        text += " No notification sent."
    return msg


@restricted
async def ban_handler(update, context, ban_state: bool):
    if context.args:
        query = " ".join(context.args) if isinstance(context.args, list) else context.args

        entity_to_ban = lookup_entity(query, exact=True)

        if isinstance(entity_to_ban, User):
            await ban_user(update, context, entity_to_ban, ban_state)
        elif isinstance(entity_to_ban, Bot):
            await ban_bot(update, context, entity_to_ban, ban_state)
        else:
            await update.message.reply_text(mdformat.failure("Can only ban users and bots."))
    else:
        # no search term
        await update.message.reply_text(
            messages.BAN_MESSAGE if ban_state else messages.UNBAN_MESSAGE,
            reply_markup=ForceReply(selective=True),
        )
    return ConversationHandler.END


@restricted
async def ban_user(update, context, user: User, ban_state: bool):
    if user.banned and ban_state is True:
        await update.message.reply_text(
            mdformat.none_action("User {} is already banned.".format(user)),
            parse_mode="markdown",
        )
        return
    if not user.banned and ban_state is False:
        await update.message.reply_text(
            mdformat.none_action("User {} is not banned.".format(user)),
            parse_mode="markdown",
        )
        return
    user.banned = ban_state
    if ban_state is True:
        with db.atomic():
            user_submissions = Bot.select().where(
                (Bot.approved == False)
                & (Bot.submitted_by == user)
                # TODO: does this need to include `Bot.deleted == True`?
            )
            for b in user_submissions:
                b.delete_instance()

            users_suggestions = Suggestion.select().where(
                (Suggestion.executed == False) & (Suggestion.user == user)
            )
            for s in users_suggestions:
                s.delete_instance()
        await update.message.reply_text(
            mdformat.success(
                "User {} banned, all bot submissions and suggestions removed.".format(
                    user
                )
            ),
            parse_mode="markdown",
        )
        Statistic.of(update, "ban", user.markdown_short)
    else:
        await update.message.reply_text(
            mdformat.success("User {} unbanned.".format(user)), parse_mode="markdown"
        )
        Statistic.of(update, "unban", user.markdown_short)
    user.save()


@restricted
async def ban_bot(update, context, to_ban: Bot, ban_state: bool):
    if to_ban.disabled and ban_state is True:
        await update.message.reply_text(
            mdformat.none_action("{} is already banned.".format(to_ban)),
            parse_mode="markdown",
        )
        return
    if not to_ban.disabled and ban_state is False:
        await update.message.reply_text(
            mdformat.none_action("{} is not banned.".format(to_ban)),
            parse_mode="markdown",
        )
        return

    if ban_state:
        to_ban.disable(Bot.DisabledReason.banned)
        await update.message.reply_text("Bot was banned.")
    else:
        to_ban.enable()
        await update.message.reply_text("Bot was unbanned.")

    to_ban.save()

    from botlistbot.components.explore import send_bot_details

    return await send_bot_details(update, context, to_ban)


async def last_update_job(context):
    return  # make admins happy :)
    last_update = helpers.get_channel().last_update
    if last_update:
        today = datetime.date.today()
        delta = datetime.timedelta(days=10)
        difference = today - last_update

        if difference > delta:
            for admin in settings.ADMINS:
                try:
                    await context.bot.send_message(
                        admin,
                        f"Last @BotList update was {difference.days} days ago. "
                        f"UPDATE NOW YOU CARNT! /admin",
                    )
                except TelegramError:
                    pass


@restricted
async def apply_all_changes(update, context, to_edit):
    user = User.from_update(update)

    user_suggestions = Suggestion.select_all_of_user(user)
    for suggestion in user_suggestions:
        suggestion.apply()

    refreshed_bot = Bot.get(id=to_edit.id)
    await edit_bot(update, context, refreshed_bot)
    Statistic.of(update, "apply", refreshed_bot.username)


@track_activity("menu", "pending bots for next update", Statistic.ANALYSIS)
async def pending_update(update, context):
    uid = update.effective_chat.id
    bots = Bot.select_pending_update()

    if len(bots) == 0:
        await update.message.reply_text("No bots pending for update.")
        return

    txt = "Bots pending for next Update:\n\n"

    if uid in settings.MODERATORS and util.is_private_message(update):
        # append admin edit buttons
        txt += "\n".join(["{} — /edit{}".format(b, b.id) for b in bots])
    else:
        txt += "\n".join([str(b) for b in bots])

    await context.bot.formatter.send_message(uid, txt)


@track_activity("request", "runtime files", Statistic.ANALYSIS)
@restricted
async def send_runtime_files(update, context):
    async def send_file(path: Path):
        path = str(path)
        try:
            uid = update.effective_user.id
            await context.bot.send_document(uid, open(path, "rb"), filename=os.path.split(path)[-1])
        except:
            pass

    root = Path(appglobals.ROOT_DIR) / "botlistbot"

    await send_file(root / "files/intro_en.txt")
    await send_file(root / "files/intro_es.txt")
    await send_file(root / "files/new_bots_list.txt")
    await send_file(root / "files/category_list.txt")
    await send_file(root / "files/commands.txt")
    await send_file(root / "error.log")
    await send_file(root / "debug.log")


# def _merge_statistic_logs(statistic, file, level):
#     all_logs = {s.date: s for s in statistic}
#     handle = open(file, 'r')
#     lines = handle.readlines()
#
#     pattern = re.compile(r'\[(.*)\] .* (INFO|DEBUG|WARNING|ERROR|EXCEPTION) - (.*)')
#     for l in lines:
#         reg = re.match(pattern, l)
#         groups = reg.groups()
#         lvl = logging.getLevelName(groups[1])
#         if level < lvl:
#             continue
#         date = dateutil.parser.parse(groups[0])
#         message = groups[2]
#
#         all_logs[date] = message
#     # sorted(all_logs, key=lambda x: ) # TODO
#     return all_logs


@track_activity("request", "activity logs", Statistic.ANALYSIS)
@restricted
async def send_activity_logs(update, context, level=Statistic.INFO):
    num = 200
    if context.args:
        try:
            num = int(context.args[0])
            num = min(num, 500)
        except:
            pass
    uid = update.effective_user.id
    recent_statistic = Statistic.select().order_by(Statistic.date.desc()).limit(num)
    recent_statistic = list(reversed(recent_statistic))

    step_size = 30
    for i in range(0, len(recent_statistic), step_size):
        items = recent_statistic[i : i + step_size]
        text = "\n".join(x.md_str() for x in items)

        await context.bot.formatter.send_message(uid, text)


@restricted
async def send_statistic(update, context):
    interesting_actions = [
        "explore",
        "menu",
        "command",
        "request",
        "made changes to their suggestion:",
        "issued deletion of conversation in BotListChat",
    ]
    stats = (
        Statistic.select(Statistic, fn.COUNT(Statistic.entity).alias("count"))
        .where(Statistic.action << interesting_actions)
        .group_by(Statistic.action, Statistic.entity)
    )
    maxlen = max(len(str(x.count)) for x in stats)
    text = "\n".join(
        "`{}▪️` {} {}".format(str(s.count).ljust(maxlen), s.action.title(), s.entity)
        for s in stats
    )
    await context.bot.formatter.send_message(update.effective_chat.id, text, parse_mode="markdown")


@track_activity("menu", "short approve list", Statistic.ANALYSIS)
async def short_approve_list(update, context):
    uid = update.effective_chat.id
    bots = Bot.select_unapproved()

    if len(bots) == 0:
        await update.message.reply_text("No bots to be approved.")
        return

    txt = "Bots pending approval:\n\n"

    if uid in settings.MODERATORS and util.is_private_message(update):
        # append admin edit buttons
        txt += "\n".join(["{} — /approve{}".format(b, b.id) for b in bots])
    else:
        txt += "\n".join([str(b) for b in bots])

    await context.bot.formatter.send_message(uid, txt)


@track_activity("menu", "manybots", Statistic.ANALYSIS)
@restricted
async def manybots(update, context):
    uid = update.effective_chat.id
    bots = Bot.select().where(
        Bot.approved == True & Bot.botbuilder == True & Bot.disabled == False
    )

    txt = "Manybots in the BotList:\n\n"

    # if uid in settings.MODERATORS and util.is_private_message(update):
    #     # append admin edit buttons
    #     txt += '\n'.join(["{} — /approve{}".format(b, b.id) for b in bots])
    # else:
    txt += "\n".join([str(b) for b in bots])

    await context.bot.formatter.send_message(uid, txt)
