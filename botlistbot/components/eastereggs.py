import random
from pprint import pprint

from peewee import fn

from botlistbot.components import botlistchat
from botlistbot.models import Bot

from telegram import ReplyKeyboardMarkup

from botlistbot import util
from telegram import KeyboardButton

from botlistbot import captions
from botlistbot.models import track_activity


def _crapPy_Tr0ll_kbmarkup(rows=None):
    if rows is None:
        rows = 3
    first = [  # adjectives
        "Gay",
        "Pony",
        "Dick",
        "Telegram",
        "Milk",
        "WhatsApp",
        "Daniils",
        "T3CHNOs",
        "Adult",
        "ThirdWorld",
        "Asian",
        "Mexican",
        "SM",
        "Russian",
        "Chinese",
        "Gonzo",
        "Anime",
        "JosXas",
        "Twitfaces",
        "N9ghtLY",
        "Super",
        "Disturbing",
        "Unnecessary",
        "Mighty",
        "Wanktastic",
        "Rag",
        "CrossEyed",
        "FritzlAdmiring",
        "Dumb",
    ]
    second = [  # nouns (plural)
        "Shit",
        "Tales",
        "Porn",
        "Rice",
        "FluShot",
        "Bugs",
        "Whores",
        "Pigs",
        "Alternatives",
        "Pics",
        "CornCake",
        "Candlestick",
        "Coffee",
        "Women",
        "Karate",
        "Love",
        "Dragons",
        "Penetrator",
        "Addiction",
        "Ducks",
        "Slaves",
        "Sucking",
        "Tiddies",
        "Awesome",
        "ArseBiscuit",
        "Suck",
        "Voyeurism",
    ]
    third = [
        "Collection",
        "Channel",
        "Bot",
        "Radio",
        "Chat",
        "Discussion",
        "Conversation",
        "Voting",
        "ForPresident",
        "Group",
        "SelfHelpGroup",
        "Enterprise",
        "Therapy",
        "Lobby",
        "ForKids",
    ]

    def compound():
        choices = [
            "{} {} {}".format(
                random.choice(first), random.choice(second), random.choice(third)
            ),
            "@{}{}{}".format(
                random.choice(first),
                random.choice(second),
                "".join(random.choice(third).split(" ")),
            ),
        ]
        return random.choice(choices)

    buttons = [[KeyboardButton(compound()) for x in range(2)] for y in range(rows)]
    buttons.insert(0, [KeyboardButton("/easteregg")])
    return buttons


@track_activity("easteregg", '"crappy troll markup"')
async def send_next(update, context):
    uid = util.uid_from_update(update)
    num_rows = None
    if context.args:
        try:
            num_rows = int(context.args[0])
        except:
            num_rows = None

    reply_markup = ReplyKeyboardMarkup(
        _crapPy_Tr0ll_kbmarkup(num_rows), one_time_keyboard=False, per_user=True
    )
    text = "ɹoʇɐɹǝuǝb ǝɯɐuɹǝsn ɯɐɹbǝןǝʇ"
    await util.send_md_message(context.bot, uid, text, reply_markup=reply_markup)

    if util.is_group_message(update):
        del_msg = await context.bot.formatter.send_message(
            update.effective_chat.id, "Have fun in private ;)\n/easteregg"
        )
        await update.effective_message.delete()
        context.job_queue.run_once(
            lambda *_: del_msg.delete(safe=True), 4, name="delete easteregg hint"
        )


async def send_random_bot(update, context):
    from botlistbot.components.explore import send_bot_details

    random_bot = (
        Bot.select()
        .where(
            (Bot.approved == True, Bot.disabled == False),
            (Bot.description.is_null(False)),
        )
        .order_by(fn.Random())
        .limit(1)[0]
    )
    await send_bot_details(update, context, random_bot)
