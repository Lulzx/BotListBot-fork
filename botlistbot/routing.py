import json
import traceback

from peewee import DoesNotExist, fn
import re
from functools import partial
from logzero import logger as log
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    ConversationHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from botlistbot import captions
from botlistbot import settings
from botlistbot import util
from botlistbot import components
from botlistbot.components import (
    admin,
    basic,
    botlist,
    botlistchat,
    botproperties,
    broadcasts,
    contributions,
    eastereggs,
    explore,
    favorites,
    help,
    inlinequeries,
)
from botlistbot.components.basic import all_handler
from botlistbot.components.botlistchat import HINTS
from botlistbot.components.explore import (
    select_category,
    send_bot_details,
    send_category,
    show_new_bots,
)
from botlistbot.components.misc import access_token, set_notifications, t3chnostats
from botlistbot.components.search import search_handler, search_query
from botlistbot.const import BotStates, CallbackActions
from botlistbot.dialog import messages
from botlistbot.lib import InlineCallbackHandler
from botlistbot.misc import manage_subscription
from botlistbot.models import (
    Bot,
    Category,
    Country,
    Favorite,
    Keyword,
    Statistic,
    Suggestion,
    User,
)

try:
    from botlistbot.components.userbot import BotChecker
except:
    pass


async def callback_router(update, context):
    obj = json.loads(str(update.callback_query.data))
    user = User.from_update(update)

    try:
        if "a" in obj:
            action = obj["a"]

            # BOTLISTCHAT
            if action == CallbackActions.DELETE_CONVERSATION:
                await botlistchat.delete_conversation(update, context)
            # HELP
            elif action == CallbackActions.HELP:
                await help.help(update, context)
            elif action == CallbackActions.CONTRIBUTING:
                await help.contributing(update, context)
            elif action == CallbackActions.EXAMPLES:
                await help.examples(update, context)
            # BASIC QUERYING
            elif action == CallbackActions.SELECT_CATEGORY:
                await select_category(update, context)
            elif action == CallbackActions.SELECT_BOT_FROM_CATEGORY:
                category = Category.get(id=obj["id"])
                await send_category(update, context, category)
            elif action == CallbackActions.SEND_BOT_DETAILS:
                item = Bot.get(id=obj["id"])
                await send_bot_details(update, context, item)
            # FAVORITES
            elif action == CallbackActions.TOGGLE_FAVORITES_LAYOUT:
                value = obj["v"]
                await favorites.toggle_favorites_layout(update, context, value)
            elif action == CallbackActions.ADD_FAVORITE:
                await favorites.add_favorite_handler(update, context)
            elif action == CallbackActions.REMOVE_FAVORITE_MENU:
                await favorites.remove_favorite_menu(update, context)
            elif action == CallbackActions.REMOVE_FAVORITE:
                to_remove = Favorite.get(id=obj["id"])
                bot_details = to_remove.bot
                to_remove.delete_instance()
                if obj.get("details"):
                    await send_bot_details(update, context, bot_details)
                else:
                    await favorites.remove_favorite_menu(update, context)
            elif action == CallbackActions.SEND_FAVORITES_LIST:
                await favorites.send_favorites_list(update, context)
            elif action == CallbackActions.ADD_ANYWAY:
                await favorites.add_custom(update, context, obj["u"])
            elif action == CallbackActions.ADD_TO_FAVORITES:
                details = obj.get("details")
                discreet = obj.get("discreet", False) or details
                item = Bot.get(id=obj["id"])
                await favorites.add_favorite(update, context, item, callback_alert=discreet)
                if details:
                    await send_bot_details(update, context, item)
            # ACCEPT/REJECT BOT SUBMISSIONS
            elif action == CallbackActions.APPROVE_REJECT_BOTS:
                custom_approve_list = [Bot.get(id=obj["id"])]
                await admin.approve_bots(update, context, override_list=custom_approve_list)
            elif action == CallbackActions.ACCEPT_BOT:
                to_accept = Bot.get(id=obj["id"])
                await admin.edit_bot_category(
                    update, context, to_accept, CallbackActions.BOT_ACCEPTED
                )
                # Run in x minutes, giving the moderator enough time to edit bot details
                context.job_queue.run_once(
                    lambda ctx: botlistchat.notify_group_submission_accepted(
                        ctx, to_accept
                    ),
                    settings.BOT_ACCEPTED_IDLE_TIME * 60,
                )
            elif action == CallbackActions.RECOMMEND_MODERATOR:
                bot_in_question = Bot.get(id=obj["id"])
                await admin.recommend_moderator(update, context, bot_in_question, obj["page"])
            elif action == CallbackActions.SELECT_MODERATOR:
                bot_in_question = Bot.get(id=obj["bot_id"])
                moderator = User.get(id=obj["uid"])
                await admin.share_with_moderator(update, context, bot_in_question, moderator)
                await admin.approve_bots(update, context, obj["page"])
            elif action == CallbackActions.REJECT_BOT:
                to_reject = Bot.get(id=obj["id"])
                notification = obj.get("ntfc", True)
                await admin.reject_bot_submission(
                    update,
                    context,
                    None,
                    to_reject,
                    verbose=False,
                    notify_submittant=notification,
                )
                await admin.approve_bots(update, context, obj["page"])
            elif action == CallbackActions.BOT_ACCEPTED:
                to_accept = Bot.get(id=obj["bid"])
                category = Category.get(id=obj["cid"])
                await admin.accept_bot_submission(update, context, to_accept, category)
            elif action == CallbackActions.COUNT_THANK_YOU:
                new_count = obj.get("count", 1)
                await basic.count_thank_you(update, context, new_count)
            # ADD BOT
            # elif action == CallbackActions.ADD_BOT_SELECT_CAT:
            #     category = Category.get(id=obj['id'])
            #     await admin.add_bot(update, context, category)
            # EDIT BOT
            elif action == CallbackActions.EDIT_BOT:
                to_edit = Bot.get(id=obj["id"])
                await admin.edit_bot(update, context, to_edit)
            elif action == CallbackActions.EDIT_BOT_SELECT_CAT:
                to_edit = Bot.get(id=obj["id"])
                await admin.edit_bot_category(update, context, to_edit)
            elif action == CallbackActions.EDIT_BOT_CAT_SELECTED:
                to_edit = Bot.get(id=obj["bid"])
                cat = Category.get(id=obj["cid"])
                await botproperties.change_category(update, context, to_edit, cat)
                await admin.edit_bot(update, context, to_edit)
            elif action == CallbackActions.EDIT_BOT_COUNTRY:
                to_edit = Bot.get(id=obj["id"])
                await botproperties.set_country_menu(update, context, to_edit)
            elif action == CallbackActions.SET_COUNTRY:
                to_edit = Bot.get(id=obj["bid"])
                if obj["cid"] == "None":
                    country = None
                else:
                    country = Country.get(id=obj["cid"])
                await botproperties.set_country(update, context, to_edit, country)
                await admin.edit_bot(update, context, to_edit)
            elif action == CallbackActions.EDIT_BOT_DESCRIPTION:
                to_edit = Bot.get(id=obj["id"])
                await botproperties.set_text_property(
                    update, context, "description", to_edit
                )
            elif action == CallbackActions.EDIT_BOT_EXTRA:
                to_edit = Bot.get(id=obj["id"])
                # SAME IS DONE HERE, but manually
                await botproperties.set_text_property(
                    update, context, "extra", to_edit
                )
            elif action == CallbackActions.EDIT_BOT_NAME:
                to_edit = Bot.get(id=obj["id"])
                await botproperties.set_text_property(update, context, "name", to_edit)
            elif action == CallbackActions.EDIT_BOT_USERNAME:
                to_edit = Bot.get(id=obj["id"])
                await botproperties.set_text_property(
                    update, context, "username", to_edit
                )
            # elif action == CallbackActions.EDIT_BOT_KEYWORDS:
            #     to_edit = Bot.get(id=obj['id'])
            #     await botproperties.set_keywords_init(update, context, to_edit)
            elif action == CallbackActions.APPLY_ALL_CHANGES:
                to_edit = Bot.get(id=obj["id"])
                await admin.apply_all_changes(update, context, to_edit)
            elif action == CallbackActions.EDIT_BOT_INLINEQUERIES:
                to_edit = Bot.get(id=obj["id"])
                value = bool(obj["value"])
                await botproperties.toggle_value(update, context, "inlinequeries", to_edit, value)
                await admin.edit_bot(update, context, to_edit)
            elif action == CallbackActions.EDIT_BOT_OFFICIAL:
                to_edit = Bot.get(id=obj["id"])
                value = bool(obj["value"])
                await botproperties.toggle_value(update, context, "official", to_edit, value)
                await admin.edit_bot(update, context, to_edit)
            elif action == CallbackActions.EDIT_BOT_OFFLINE:
                to_edit = Bot.get(id=obj["id"])
                value = bool(obj["value"])
                await botproperties.toggle_value(update, context, "offline", to_edit, value)
                await admin.edit_bot(update, context, to_edit)
            elif action == CallbackActions.EDIT_BOT_SPAM:
                to_edit = Bot.get(id=obj["id"])
                value = bool(obj["value"])
                await botproperties.toggle_value(update, context, "spam", to_edit, value)
                await admin.edit_bot(update, context, to_edit)
            elif action == CallbackActions.CONFIRM_DELETE_BOT:
                to_delete = Bot.get(id=obj["id"])
                await botproperties.delete_bot_confirm(update, context, to_delete)
            elif action == CallbackActions.DELETE_BOT:
                to_edit = Bot.get(id=obj["id"])
                await botproperties.delete_bot(update, context, to_edit)
                # send_category(update, context, to_edit.category)
            elif action == CallbackActions.ACCEPT_SUGGESTION:
                suggestion = Suggestion.get(id=obj["id"])
                await components.botproperties.accept_suggestion(update, context, suggestion)
                await admin.approve_suggestions(update, context, page=obj["page"])
            elif action == CallbackActions.REJECT_SUGGESTION:
                suggestion = Suggestion.get(id=obj["id"])
                suggestion.delete_instance()
                await admin.approve_suggestions(update, context, page=obj["page"])
            elif action == CallbackActions.CHANGE_SUGGESTION:
                suggestion = Suggestion.get(id=obj["id"])
                await botproperties.change_suggestion(
                    update, context, suggestion, page_handover=obj["page"]
                )
            elif action == CallbackActions.SWITCH_SUGGESTIONS_PAGE:
                page = obj["page"]
                await admin.approve_suggestions(update, context, page)
            elif action == CallbackActions.SWITCH_APPROVALS_PAGE:
                await admin.approve_bots(update, context, page=obj["page"])
            elif action == CallbackActions.SET_NOTIFICATIONS:
                await set_notifications(update, context, obj["value"])
            elif action == CallbackActions.NEW_BOTS_SELECTED:
                await show_new_bots(update, context, back_button=True)
            elif action == CallbackActions.ABORT_SETTING_KEYWORDS:
                to_edit = Bot.get(id=obj["id"])
                await admin.edit_bot(update, context, to_edit)
            # SENDING BOTLIST
            elif action == CallbackActions.SEND_BOTLIST:
                silent = obj.get("silent", False)
                re_send = obj.get("re", False)
                await botlist.send_botlist(update, context, resend=re_send, silent=silent)
            elif action == CallbackActions.RESEND_BOTLIST:
                await botlist.send_botlist(update, context, resend=True, silent=True)
            # BROADCASTING
            elif action == "send_broadcast":
                await broadcasts.send_broadcast(update, context)
            elif action == "pin_message":
                await broadcasts.pin_message(update, context, obj["mid"])
            elif action == "add_thank_you":
                await basic.add_thank_you_button(update, context, obj["cid"], obj["mid"])
            # EXPLORING
            elif action == CallbackActions.EXPLORE_NEXT:
                await explore.explore(update, context)
    except Exception as e:
        traceback.print_exc()

        # get the callback action in plaintext
        actions = dict(CallbackActions.__dict__)
        a = next(k for k, v in actions.items() if v == obj.get("a"))
        await util.send_md_message(
            context.bot,
            settings.DEVELOPER_ID,
            "Exception in callback query for {}:\n{}\n\nWith CallbackAction {}\n\nWith data:\n{}".format(
                user.markdown_short,
                util.escape_markdown(e),
                util.escape_markdown(a),
                util.escape_markdown(str(obj)),
            ),
        )
    finally:
        await context.bot.answer_callback_query(update.callback_query.id)
        return ConversationHandler.END


async def forward_router(update, context):
    message = update.effective_message

    # First, check if the message was forwarded FROM a bot (sender metadata)
    forward_from = message.forward_from
    if forward_from and forward_from.is_bot:
        username = "@" + forward_from.username if forward_from.username else None
        if username and username != "@" + settings.SELF_BOT_NAME:
            try:
                item = Bot.get(fn.lower(Bot.username) == username.lower())
                await send_bot_details(update, context, item)
                return
            except DoesNotExist:
                pass

    # Fallback: match first @username in the forwarded message text
    text = message.text
    if not text:
        return
    try:
        username = re.match(settings.REGEX_BOT_IN_TEXT, text).groups()[0]
        if username == "@" + settings.SELF_BOT_NAME:
            return  # ignore

        item = Bot.get(fn.lower(Bot.username) == username.lower())
        await send_bot_details(update, context, item)

    except (AttributeError, TypeError, DoesNotExist):
        pass  # no valid username in forwarded message


async def reply_router(update, context):
    reply_to = update.effective_message.reply_to_message
    if not reply_to:
        return

    text = reply_to.text

    if text == messages.ADD_FAVORITE:
        query = update.message.text
        await favorites.add_favorite_handler(update, context, query)
    elif text == messages.SEARCH_MESSAGE:
        query = update.message.text
        await search_query(update, context, query)

    # BOTPROPERTIES
    bot_properties = ["description", "extra", "name", "username"]
    try:
        partition = text.partition(messages.BOTPROPERTY_STARTSWITH)
    except AttributeError:
        return
    if partition[1] != "":
        bot_property = next(p for p in bot_properties if partition[2].startswith(p))
        # Reply for setting a bot property
        await botproperties.set_text_property(update, context, bot_property)
        raise ApplicationHandlerStop
    elif text == messages.BAN_MESSAGE:
        query = update.message.text
        await admin.ban_handler(update, context, query, True)
    elif text == messages.UNBAN_MESSAGE:
        query = update.message.text
        await admin.ban_handler(update, context, query, False)

    # Auto-lookup: if replying to a bot's message, look up that bot
    if reply_to.from_user and reply_to.from_user.is_bot:
        username = "@" + reply_to.from_user.username if reply_to.from_user.username else None
        if username and username != "@" + settings.SELF_BOT_NAME:
            try:
                item = Bot.get(fn.lower(Bot.username) == username.lower())
                await send_bot_details(update, context, item)
            except DoesNotExist:
                pass


def register(application: Application, bot_checker: "BotChecker"):
    def add(*args, **kwargs):
        application.add_handler(*args, **kwargs)

    keywords_handler = ConversationHandler(
        entry_points=[
            InlineCallbackHandler(
                CallbackActions.EDIT_BOT_KEYWORDS,
                botproperties.set_keywords_init,
                serialize=lambda data: dict(to_edit=Bot.get(id=data["id"])),
            )
        ],
        states={
            BotStates.SENDING_KEYWORDS: [
                MessageHandler(
                    filters.TEXT, botproperties.add_keyword
                ),
                InlineCallbackHandler(
                    CallbackActions.REMOVE_KEYWORD,
                    botproperties.remove_keyword,
                    serialize=lambda data: dict(
                        to_edit=Bot.get(id=data["id"]),
                        keyword=Keyword.get(id=data["kwid"]),
                    ),
                ),
                InlineCallbackHandler(
                    CallbackActions.DELETE_KEYWORD_SUGGESTION,
                    botproperties.delete_keyword_suggestion,
                    serialize=lambda data: dict(
                        to_edit=Bot.get(id=data["id"]),
                        suggestion=Suggestion.get(id=data["suggid"]),
                    ),
                ),
            ]
        },
        fallbacks=[
            CallbackQueryHandler(callback_router)
        ],
        per_user=True,
        allow_reentry=False,
    )
    add(keywords_handler)

    broadcasting_handler = ConversationHandler(
        entry_points=[
            InlineCallbackHandler(
                "broadcast", broadcasts.broadcast
            ),
            CommandHandler("broadcast", broadcasts.broadcast),
            CommandHandler("bc", broadcasts.broadcast),
        ],
        states={
            BotStates.BROADCASTING: [
                MessageHandler(
                    filters.TEXT, broadcasts.broadcast_preview
                )
            ]
        },
        fallbacks=[],
        per_user=True,
        per_chat=False,
        allow_reentry=True,
    )
    add(broadcasting_handler)

    add(CallbackQueryHandler(callback_router))

    add(CommandHandler(("cat", "category", "categories"), select_category))
    add(CommandHandler(("s", "search"), search_handler))

    add(MessageHandler(filters.REPLY, reply_router), group=-1)
    add(MessageHandler(filters.FORWARDED, forward_router))

    add(CommandHandler("admin", admin.menu))
    add(CommandHandler("a", admin.menu))

    add(CommandHandler(("rej", "reject"), admin.reject_bot_submission))
    add(
        CommandHandler(
            ("rejsil", "rejectsil", "rejsilent", "rejectsilent"),
            lambda update, context: admin.reject_bot_submission(
                update, context, None, notify_submittant=False
            ),
        )
    )

    # admin menu
    add(MessageHandler(filters.Regex(captions.APPROVE_BOTS + ".*"), admin.approve_bots))
    add(MessageHandler(filters.Regex(captions.APPROVE_SUGGESTIONS + ".*"), admin.approve_suggestions))
    add(MessageHandler(filters.Regex(captions.PENDING_UPDATE + ".*"), admin.pending_update))
    add(
        MessageHandler(
            filters.Regex(captions.SEND_BOTLIST), admin.prepare_transmission
        )
    )
    add(MessageHandler(filters.Regex(captions.FIND_OFFLINE), admin.send_offline))
    add(MessageHandler(filters.Regex(captions.SEND_CONFIG_FILES), admin.send_runtime_files))
    add(MessageHandler(filters.Regex(captions.SEND_ACTIVITY_LOGS), admin.send_activity_logs))

    # main menu
    add(MessageHandler(filters.Regex(captions.ADMIN_MENU), admin.menu))
    add(MessageHandler(filters.Regex(captions.REFRESH), admin.menu))
    add(MessageHandler(filters.Regex(captions.CATEGORIES), select_category))
    add(MessageHandler(filters.Regex(captions.EXPLORE), explore.explore))
    add(MessageHandler(filters.Regex(captions.FAVORITES), favorites.send_favorites_list))
    add(MessageHandler(filters.Regex(captions.NEW_BOTS), show_new_bots))
    add(MessageHandler(filters.Regex(captions.SEARCH), search_handler))
    add(MessageHandler(filters.Regex(captions.CONTRIBUTING), help.contributing))
    add(MessageHandler(filters.Regex(captions.EXAMPLES), help.examples))
    add(MessageHandler(filters.Regex(captions.HELP), help.help))

    add(MessageHandler(filters.Regex(r"^/edit\d+$"), admin.edit_bot), group=1)

    add(MessageHandler(filters.Regex(r"^/approve\d+$"), admin.edit_bot), group=1)
    add(CommandHandler("approve", admin.short_approve_list))

    add(CommandHandler(("manybot", "manybots"), admin.manybots))

    add(
        CommandHandler(
            "new",
            partial(contributions.new_bot_submission, bot_checker=bot_checker),
        )
    )
    add(
        MessageHandler(
            filters.Regex(".*#new.*"),
            lambda update, context: contributions.new_bot_submission(
                update, context, args=None, bot_checker=bot_checker
            ),
        ),
        group=1,
    )
    add(CommandHandler("offline", contributions.notify_bot_offline))
    add(MessageHandler(filters.Regex(".*#offline.*"), contributions.notify_bot_offline), group=1)
    add(CommandHandler("spam", contributions.notify_bot_spam))
    add(MessageHandler(filters.Regex(".*#spam.*"), contributions.notify_bot_spam), group=1)

    add(CommandHandler("help", help.help))
    add(CommandHandler(("contribute", "contributing"), help.contributing))
    add(CommandHandler("examples", help.examples))
    add(CommandHandler("rules", help.rules))

    add(
        CommandHandler(
            ("addfav", "addfavorite"), favorites.add_favorite_handler
        )
    )
    add(CommandHandler(("f", "fav", "favorites"), favorites.send_favorites_list))

    add(CommandHandler(("e", "explore"), explore.explore))
    add(CommandHandler("official", explore.show_official))

    add(
        CommandHandler(
            "ban",
            partial(admin.ban_handler, ban_state=True),
        )
    )
    add(
        CommandHandler(
            "unban",
            partial(admin.ban_handler, ban_state=False),
        )
    )
    add(CommandHandler("t3chno", t3chnostats))
    add(CommandHandler("random", eastereggs.send_random_bot))
    add(CommandHandler("easteregg", eastereggs.send_next))

    add(CommandHandler("subscribe", manage_subscription))
    add(CommandHandler("newbots", show_new_bots))

    add(CommandHandler("accesstoken", access_token))

    add(
        CommandHandler(
            ("stat", "stats", "statistic", "statistics"), admin.send_statistic
        )
    )

    add(CommandHandler(("log", "logs"), admin.send_activity_logs))
    add(
        CommandHandler(
            ("debug", "analysis", "ana", "analyze"),
            lambda update, context: admin.send_activity_logs(
                update, context, Statistic.ANALYSIS
            ),
        )
    )
    add(
        CommandHandler(
            "info",
            lambda update, context: admin.send_activity_logs(
                update, context, Statistic.INFO
            ),
        )
    )
    add(
        CommandHandler(
            ("detail", "detailed"),
            lambda update, context: admin.send_activity_logs(
                update, context, Statistic.DETAILED
            ),
        )
    )
    add(
        CommandHandler(
            ("warn", "warning"),
            lambda update, context: admin.send_activity_logs(
                update, context, Statistic.WARN
            ),
        )
    )
    add(
        CommandHandler(
            "important",
            lambda update, context: admin.send_activity_logs(
                update, context, Statistic.IMPORTANT
            ),
        )
    )

    add(
        MessageHandler(
            filters.TEXT,
            lambda update, context: botlistchat.text_message_logger(update, context, log),
        ),
        group=99,
    )

    for hashtag in HINTS.keys():
        add(
            MessageHandler(
                filters.Regex(r"{}.*".format(hashtag)), botlistchat.hint_handler
            ),
            group=1,
        )
    add(CommandHandler(("hint", "hints"), botlistchat.show_available_hints))

    add(
        MessageHandler(
            filters.Regex("^{}$".format(settings.REGEX_BOT_ONLY)),
            send_bot_details,
        )
    )

    add(ChosenInlineResultHandler(inlinequeries.chosen_result))
    add(InlineQueryHandler(inlinequeries.inlinequery_handler))
    add(MessageHandler(filters.ALL, all_handler), group=98)
