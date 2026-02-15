from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

from botlistbot import captions
from botlistbot import helpers
from botlistbot import mdformat
from botlistbot import settings
from botlistbot import util
from botlistbot.components import admin
from botlistbot.const import BotStates, CallbackActions
from botlistbot.custemoji import Emoji
from botlistbot.dialog import messages
from botlistbot.lib import InlineCallbackButton
from botlistbot.models import Bot, Country, Keyword, Statistic, Suggestion, User, track_activity
from botlistbot.util import restricted

CLEAR_QUERY = "x"


def _is_clear_query(query):
    return query.lower() == CLEAR_QUERY


async def set_country_menu(update, context, to_edit):
    uid = util.uid_from_update(update)
    countries = Country.select().order_by(Country.name).execute()

    buttons = util.build_menu(
        [InlineKeyboardButton(
            '{} {}'.format(c.emojized, c.name),
            callback_data=util.callback_for_action(
                CallbackActions.SET_COUNTRY, {'cid': c.id, 'bid': to_edit.id})) for c in countries
        ], 3)
    buttons.insert(0, [
        InlineKeyboardButton(captions.BACK,
                             callback_data=util.callback_for_action(CallbackActions.EDIT_BOT,
                                                                    {'id': to_edit.id})),
        InlineKeyboardButton("None",
                             callback_data=util.callback_for_action(CallbackActions.SET_COUNTRY,
                                                                    {
                                                                        'cid': 'None',
                                                                        'bid': to_edit.id
                                                                    })),
    ])
    return await context.bot.formatter.send_or_edit(uid, util.action_hint(
        "Please select a country/language for {}".format(to_edit)),
                                      to_edit=util.mid_from_update(update),
                                      reply_markup=InlineKeyboardMarkup(buttons))


async def set_country(update, context, to_edit, country):
    user = User.from_update(update)

    if await check_suggestion_limit(update, context, user):
        return
    if isinstance(country, Country):
        value = country.id
    elif country is None or country == 'None':
        value = None
    else:
        raise AttributeError("Error setting country to {}.".format(country))
    Suggestion.add_or_update(user, 'country', to_edit, value)


async def set_text_property(update, context, property_name, to_edit=None):
    uid = util.uid_from_update(update)
    user = User.from_update(update)
    if await check_suggestion_limit(update, context, user):
        return

    if to_edit:
        text = (
            util.escape_markdown(getattr(to_edit, property_name)) + "\n\n" if getattr(to_edit,
                                                                                      property_name) else '')
        text += mdformat.action_hint(
            messages.SET_BOTPROPERTY.format(
                property_name,
                util.escape_markdown(to_edit.username),
                CLEAR_QUERY
            ))
        if property_name == 'description':
            text += ', markdown enabled.'
        await update.effective_message.reply_text(text, reply_markup=ForceReply(selective=True),
                                            parse_mode=ParseMode.MARKDOWN)
        context.chat_data['edit_bot'] = to_edit
    elif update.message:
        value = None
        text = update.message.text

        to_edit = context.chat_data.get('edit_bot', None)

        async def too_long(n):
            await context.bot.formatter.send_failure(uid, "Your {} text is too long, it must be shorter "
                                            "than {} characters. Please try again.".format(
                property_name, n))
            await util.wait(update, context)
            return await admin.edit_bot(update, context, to_edit)

        # Validation
        if property_name == 'description' and len(text) > 300:
            return await too_long(300)
        if property_name == 'username':
            value = helpers.validate_username(text)
            if value:
                to_edit = context.chat_data.get('edit_bot', None)
            else:
                await context.bot.formatter.send_failure(uid,
                                           "The username you entered is not valid. Please try again...")
                return await admin.edit_bot(update, context, to_edit)

        if not value:
            value = text

        if to_edit:
            if _is_clear_query(text):
                Suggestion.add_or_update(user, property_name, to_edit, None)
            else:
                Suggestion.add_or_update(user, property_name, to_edit, value)
            await admin.edit_bot(update, context, to_edit)
        else:
            await context.bot.formatter.send_failure(uid, "An unexpected error occured.")


async def toggle_value(update, context, property_name, to_edit, value):
    user = User.from_update(update)

    if await check_suggestion_limit(update, context, user):
        return
    Suggestion.add_or_update(user, property_name, to_edit, bool(value))


async def set_keywords_init(update, context, kw_context):
    to_edit = kw_context.get('to_edit')
    context.chat_data['set_keywords_msg'] = util.mid_from_update(update)
    return await set_keywords(update, context, to_edit)


@track_activity('menu', 'set keywords', Statistic.DETAILED)
async def set_keywords(update, context, to_edit):
    chat_id = util.uid_from_update(update)
    keywords = Keyword.select().where(Keyword.entity == to_edit)
    context.chat_data['edit_bot'] = to_edit
    set_keywords_msgid = context.chat_data.get('set_keywords_msg')

    pending = Suggestion.select().where(
        Suggestion.executed == False,
        Suggestion.subject == to_edit,
        Suggestion.action << ['add_keyword', 'remove_keyword']
    )
    pending_removal = [y for y in pending if y.action == 'remove_keyword']

    # Filter keywords by name to not include removal suggestions
    # We don't need to do this for add_keyword suggestions, because duplicates are not allowed.
    keywords = [k for k in keywords if k.name not in [s.value for s in pending_removal]]

    kw_remove_buttons = [InlineCallbackButton(
        '{} ✖️'.format(x),
        callback_action=CallbackActions.REMOVE_KEYWORD,
        params={'id': to_edit.id, 'kwid': x.id})
        for x in keywords]
    kw_remove_buttons.extend([InlineKeyboardButton(
        '#{} 👓✖️'.format(x.value),
        callback_data=util.callback_for_action(
            CallbackActions.DELETE_KEYWORD_SUGGESTION,
            {'id': to_edit.id, 'suggid': x.id}))
        for x
        in [y for y in pending if y.action == 'add_keyword']
    ])
    kw_remove_buttons.extend([InlineKeyboardButton(
        '#{} 👓❌'.format(x.value),
        callback_data=util.callback_for_action(
            CallbackActions.DELETE_KEYWORD_SUGGESTION,
            {'id': to_edit.id, 'suggid': x.id}))
        for x
        in pending_removal
    ])
    buttons = util.build_menu(kw_remove_buttons, 2, header_buttons=[
        InlineKeyboardButton(captions.DONE,
                             callback_data=util.callback_for_action(
                                 CallbackActions.ABORT_SETTING_KEYWORDS,
                                 {'id': to_edit.id}))
    ])
    reply_markup = InlineKeyboardMarkup(buttons)
    msg = await util.send_or_edit_md_message(
        context.bot,
        chat_id,
        util.action_hint('Send me the keywords for {} one by one...\n\n{}'.format(
            util.escape_markdown(to_edit.username), messages.KEYWORD_BEST_PRACTICES)),
        to_edit=set_keywords_msgid,
        reply_markup=reply_markup)

    if msg:
        # message might not have been edited if the user adds an already-existing keyword
        # TODO: should the user be notified about this?
        context.chat_data['set_keywords_msg'] = msg.message_id

    return BotStates.SENDING_KEYWORDS


async def add_keyword(update, context):
    user = User.from_telegram_object(update.effective_user)
    if await check_suggestion_limit(update, context, user):
        return
    kw = update.message.text
    bot_to_edit = context.chat_data.get('edit_bot')
    kw = helpers.format_keyword(kw)

    # Sanity checks
    if kw in settings.FORBIDDEN_KEYWORDS:
        await update.message.reply_text('The keyword {} is forbidden.'.format(kw))
        return
    if len(kw) <= 1:
        await update.message.reply_text('Keywords must be longer than 1 character.')
        return
    if len(kw) >= 20:
        await update.message.reply_text('Keywords must not be longer than 20 characters.')

    # Ignore duplicates
    try:
        Keyword.get((Keyword.name == kw) & (Keyword.entity == bot_to_edit))
        return
    except Keyword.DoesNotExist:
        pass

    Suggestion.add_or_update(user=user, action='add_keyword', subject=bot_to_edit, value=kw)
    await set_keywords(update, context, bot_to_edit)
    Statistic.of(update, 'added keyword to'.format(kw), bot_to_edit.username)


async def delete_keyword_suggestion(update, context, kw_context):
    suggestion = kw_context.get('suggestion')
    suggestion.delete_instance()
    await set_keywords(update, context, kw_context.get('to_edit'))


@restricted
async def delete_bot_confirm(update, context, to_edit):
    chat_id = util.uid_from_update(update)
    reply_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes, delete it!", callback_data=util.callback_for_action(
            CallbackActions.DELETE_BOT, {'id': to_edit.id}
        )),
        InlineKeyboardButton(captions.BACK, callback_data=util.callback_for_action(
            CallbackActions.EDIT_BOT, {'id': to_edit.id}
        ))
    ]]
    )
    await context.bot.formatter.send_or_edit(chat_id, "Are you sure?", to_edit=util.mid_from_update(update),
                               reply_markup=reply_markup)


@restricted
async def delete_bot(update, context, to_edit: Bot):
    username = to_edit.username
    to_edit.disable(Bot.DisabledReason.banned)
    to_edit.save()
    await context.bot.formatter.send_or_edit(
        update.effective_user.id,
        "Bot has been disabled and banned.",
        to_edit=util.mid_from_update(update)
    )
    Statistic.of(update, 'disable', username, Statistic.IMPORTANT)


async def change_category(update, context, to_edit, category):
    uid = update.effective_user.id
    user = User.get(User.chat_id == uid)

    if uid == 918962:
        # Special for t3chno
        to_edit.category = category
        to_edit.save()
    else:
        if await check_suggestion_limit(update, context, user):
            return
        Suggestion.add_or_update(user, 'category', to_edit, category.id)


async def check_suggestion_limit(update, context, user):
    cid = update.effective_chat.id
    if Suggestion.over_limit(user):
        await context.bot.formatter.send_failure(cid,
                                   "You have reached the limit of {} suggestions. Please wait for "
                                   "the Moderators to approve of some of them.".format(
                                       settings.SUGGESTION_LIMIT))
        Statistic.of(update, 'hit the suggestion limit')
        return True
    return False


async def change_suggestion(update, context, suggestion, page_handover):
    cid = update.effective_chat.id
    mid = update.effective_message.message_id

    text = '{}:\n\n{}'.format(str(suggestion), suggestion.value)
    if suggestion.action == 'description':
        callback_action = CallbackActions.EDIT_BOT_DESCRIPTION
    elif suggestion.action == 'extra':
        callback_action = CallbackActions.EDIT_BOT_EXTRA
    elif suggestion.action == 'name':
        callback_action = CallbackActions.EDIT_BOT_NAME
    elif suggestion.action == 'username':
        callback_action = CallbackActions.EDIT_BOT_USERNAME
    else:
        return  # should not happen

    buttons = [[
        InlineKeyboardButton(captions.BACK,
                             callback_data=util.callback_for_action(
                                 CallbackActions.SWITCH_SUGGESTIONS_PAGE,
                                 {'page': page_handover}))
    ], [
        InlineKeyboardButton("{} Accept".format(Emoji.WHITE_HEAVY_CHECK_MARK),
                             callback_data=util.callback_for_action(
                                 CallbackActions.ACCEPT_SUGGESTION,
                                 {'id': suggestion.id, 'page': page_handover}
                             )),
        InlineKeyboardButton(captions.CHANGE_SUGGESTION, callback_data=util.callback_for_action(
            callback_action, {'id': suggestion.id, 'page': page_handover}
        )),
        InlineKeyboardButton(Emoji.CROSS_MARK, callback_data=util.callback_for_action(
            CallbackActions.REJECT_SUGGESTION, {'id': suggestion.id, 'page': page_handover}
        ))
    ]]

    reply_markup = InlineKeyboardMarkup(buttons)
    await context.bot.formatter.send_or_edit(cid, text, to_edit=mid, disable_web_page_preview=True,
                               reply_markup=reply_markup)


async def remove_keyword(update, context, kw_context):
    user = User.from_telegram_object(update.effective_user)
    if await check_suggestion_limit(update, context, user):
        return
    to_edit = kw_context.get('to_edit')
    kw = kw_context.get('keyword')
    Suggestion.add_or_update(user=user, action='remove_keyword', subject=to_edit, value=kw.name)
    return await set_keywords(update, context, to_edit)


@restricted
async def accept_suggestion(update, context, suggestion: Suggestion):
    user = User.from_telegram_object(update.effective_user)
    suggestion.apply()

    if suggestion.action == 'offline':
        suggestion_text = '{} went {}.'.format(
            suggestion.subject.str_no_md,
            'offline' if suggestion.subject.offline else 'online')
    else:
        suggestion_text = str(suggestion)

    suggestion_text = suggestion_text[0].upper() + suggestion_text[1:]
    suggestion_text += '\nApproved by ' + user.markdown_short
    await context.bot.send_message(settings.BOTLIST_NOTIFICATIONS_ID, suggestion_text,
                     parse_mode='markdown', disable_web_page_preview=True)

    if user != suggestion.user.chat_id:
        submittant_notification = '*Thank you* {}, your suggestion has been accepted:' \
                                  '\n\n{}'.format(util.escape_markdown(suggestion.user.first_name),
                                                  str(suggestion))
        try:
            await context.bot.send_message(suggestion.user.chat_id, submittant_notification,
                             parse_mode='markdown', disable_web_page_preview=True)
        except BadRequest:
            await update.effective_message.reply_text(
                "Could not contact {}.".format(suggestion.user.markdown_short),
                parse_mode='markdown', disable_web_page_preview=True)
