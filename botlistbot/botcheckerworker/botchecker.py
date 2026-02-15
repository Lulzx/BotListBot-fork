#!/usr/bin/python3
from collections import Counter

import asyncio
import filecmp
import logging
import os
import re
import shutil
import time
import traceback
from datetime import datetime, timedelta
from logzero import logger as log

from pyrogram.raw.functions.contacts import ResolveUsername as Search
from pyrogram.raw.functions.messages import DeleteHistory
from pyrogram.raw.functions.users import GetUsers
from pyrogram.raw.types import InputPeerUser
from pyrogram.raw.types.contacts import ResolvedPeer

from pyrogram.errors import (
    FloodWait,
    QueryTooShort,
    UnknownError,
    UsernameInvalid,
    UsernameNotOccupied,
)
from telegram import Bot as TelegramBot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

try:
    from tgintegration import InlineResultContainer, InteractionClientAsync, Response
except ImportError:
    InteractionClientAsync = None
    InlineResultContainer = None
    Response = None

from typing import Union

from botlistbot import captions
from botlistbot import helpers
from botlistbot import settings
from botlistbot import util
from botlistbot.const import CallbackActions
from botlistbot.helpers import make_sticker
from botlistbot.models import Bot, Bot as BotModel, Keyword

logging.getLogger().setLevel(logging.WARNING)

ZERO_CHAR1 = u"\u200C"  # ZERO-WIDTH-NON-JOINER
ZERO_CHAR2 = u"\u200B"  # ZERO-WIDTH-SPACE
botbuilder_pattern = re.compile('|'.join(settings.BOTBUILDER_DETERMINERS), re.IGNORECASE)
offline_pattern = re.compile('|'.join(settings.OFFLINE_DETERMINERS), re.IGNORECASE)

TMP_DIR = os.path.join(settings.BOT_THUMBNAIL_DIR, "tmp")
if os.path.exists(TMP_DIR):
    shutil.rmtree(TMP_DIR)
os.makedirs(TMP_DIR)


def zero_width_encoding(encoded_string):
    if not encoded_string:
        return None
    result = ''
    for c in encoded_string:
        if c in (ZERO_CHAR1, ZERO_CHAR2):
            result += c
        else:
            return result
    return None


_BaseClass = InteractionClientAsync if InteractionClientAsync is not None else object


class BotChecker(_BaseClass):
    def __init__(self, session_name, api_id, api_hash, phone_number, workdir=None):

        self.username_flood_until = None
        self._message_intervals = {}
        self._last_ping = None
        self.__photos_lock = asyncio.Lock()

        if InteractionClientAsync is not None:
            super(BotChecker, self).__init__(
                session_name,
                api_id,
                api_hash,
                workers=4,
                phone_number=phone_number,
                workdir=workdir
            )
            self.logger.setLevel(logging.WARNING)
        else:
            log.warning("tgintegration not available, BotChecker running in limited mode")

    async def schedule_conversation_deletion(self, peer, delay=5):
        await asyncio.sleep(delay)
        self.send(DeleteHistory(await self.resolve_peer(peer), max_id=999999999, just_clear=True))
        log.debug("Deleted conversation with {}".format(peer))

    def update_bot_details(self, to_check: BotModel, peer):
        """
        Set basic properties of the bot
        """
        if isinstance(peer, ResolvedPeer):
            peer = self.resolve_peer(peer.peer.user_id)
        elif isinstance(peer, InputPeerUser):
            pass
        else:
            peer = self.resolve_peer(peer.id)

        try:
            user = self.send(GetUsers([peer]))[0]
        except:
            traceback.print_exc()
            print("this peer does not work for GetUsers:")
            print(type(peer))
            print(peer)
            return None

        if hasattr(user, 'bot') and user.bot is True:
            # Regular bot
            to_check.official = bool(user.verified)
            to_check.inlinequeries = bool(user.bot_inline_placeholder)
            to_check.name = user.first_name
            to_check.bot_info_version = user.bot_info_version
        else:
            # Userbot
            to_check.userbot = True
            to_check.name = helpers.format_name(user)

        # In any case
        to_check.chat_id = int(user.id)
        to_check.username = '@' + str(user.username)

    async def get_ping_response(
            self,
            to_check: Bot,
            timeout=30,
            try_inline=True
    ) -> Union[Response, InlineResultContainer]:
        response = await self.ping_bot(
            to_check.chat_id,
            override_messages=settings.PING_MESSAGES,
            max_wait_response=timeout,
            raise_=False
        )
        if response.empty:
            if try_inline and to_check.inlinequeries:
                for q in settings.PING_INLINEQUERIES:
                    try:
                        return self.get_inline_bot_results(to_check.username, q)
                    except UnknownError as e:
                        if "timeout" in e.MESSAGE.lower():
                            continue
                        else:
                            raise e
                return False

        # Evaluate WJClub's ParkMeBot flags
        reserved_username = ZERO_CHAR1 + ZERO_CHAR1 + ZERO_CHAR1 + ZERO_CHAR1
        parked = ZERO_CHAR1 + ZERO_CHAR1 + ZERO_CHAR1 + ZERO_CHAR2
        maintenance = ZERO_CHAR1 + ZERO_CHAR1 + ZERO_CHAR2 + ZERO_CHAR1

        full_text = response.full_text
        if zero_width_encoding(full_text) in (reserved_username, parked, maintenance):
            return False
        if offline_pattern.search(full_text):
            return False

        return response

    def resolve_bot(self, bot: BotModel):
        if bot.chat_id:
            try:
                return self.resolve_peer(bot.chat_id)
            except Exception:
                pass

        # Try resolving by username directly
        if self.username_flood_until:
            if self.username_flood_until < datetime.now():
                self.username_flood_until = None
        else:
            try:
                return self.resolve_peer(bot.username)
            except FloodWait as e:
                wait_seconds = getattr(e, 'x', getattr(e, 'value', 60))
                self.username_flood_until = datetime.now() + timedelta(
                    seconds=wait_seconds)
                log.warning("Flood wait for ResolveUsername: {}s (until {})".format(
                    wait_seconds, self.username_flood_until))
            except UsernameInvalid as e:
                log.error(e)

        return None

    async def download_profile_photo(self, bot: BotModel, photo_path):
        tmp_file = os.path.join(TMP_DIR, bot.username.replace('@', '') + '.jpg')
        photos = self.get_user_profile_photos(bot.chat_id).photos
        if photos:
            photo_size_object = photos[0][-1]

            await self.__photos_lock.acquire()
            try:
                try:
                    self.download_media(
                        photo_size_object,
                        file_name=tmp_file,
                        block=True
                    )
                except FloodWait as e:
                    wait_seconds = getattr(e, 'x', getattr(e, 'value', 60))
                    log.debug(f"FloodWait for downloading media ({wait_seconds})")

                if os.path.exists(tmp_file):
                    try:
                        similar = filecmp.cmp(tmp_file, photo_path, shallow=False)
                    except FileNotFoundError:
                        similar = False

                    if not similar:
                        shutil.copy(tmp_file, photo_path)
            finally:
                self.__photos_lock.release()


async def check_bot(
        telegram_bot,
        bot_checker: BotChecker,
        to_check: BotModel,
        result_queue: asyncio.Queue
):
    log.debug("Checking bot {}...".format(to_check.username))

    try:
        peer = bot_checker.resolve_bot(to_check)
    except UsernameNotOccupied:
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(captions.EDIT_BOT, callback_data=util.callback_for_action(
                CallbackActions.EDIT_BOT,
                dict(id=to_check.id)
            ))
        ]])
        text = "{} does not exist (anymore). Please resolve this " \
               "issue manually!".format(to_check.username)
        try:
            await telegram_bot.send_message(settings.BLSF_ID, text, reply_markup=markup)
        except BadRequest:
            await telegram_bot.send_notification(text)
        return await result_queue.put('not found')

    if not peer:
        return await result_queue.put('skipped')

    bot_checker.update_bot_details(to_check, peer=peer)

    # Check online state
    try:
        response = await bot_checker.get_ping_response(
            to_check,
            timeout=30,
            try_inline=to_check.inlinequeries)
    except UnknownError as e:
        await result_queue.put(e.MESSAGE)
        return
    except Exception as e:
        log.exception(e)
        await result_queue.put(str(e))
        return

    for _ in range(2):
        await result_queue.put('messages sent')

    was_offline = to_check.offline
    is_offline = response.empty if isinstance(response, Response) else not bool(response)

    now = datetime.now()
    to_check.last_ping = now
    if not is_offline:
        to_check.last_response = now

    if was_offline != is_offline:
        await telegram_bot.send_message(settings.BOTLIST_NOTIFICATIONS_ID, '{} went {}.'.format(
            to_check.str_no_md,
            'offline' if to_check.offline else 'online'
        ), timeout=40)

    await add_keywords(telegram_bot, response, to_check)

    # Download profile picture
    if settings.DOWNLOAD_PROFILE_PICTURES:
        await download_profile_picture(telegram_bot, bot_checker, to_check)

    to_check.save()

    if settings.DELETE_CONVERSATION_AFTER_PING:
        await bot_checker.schedule_conversation_deletion(to_check.chat_id, 10)

    await disable_decider(telegram_bot, to_check)

    await result_queue.put('offline' if to_check.offline else 'online')


async def download_profile_picture(telegram_bot, bot_checker, to_check):
    photo_file = to_check.thumbnail_file
    sticker_file = os.path.join(settings.BOT_THUMBNAIL_DIR, '_sticker_tmp.webp')
    await bot_checker.download_profile_photo(to_check, photo_file)
    if settings.NOTIFY_NEW_PROFILE_PICTURE:
        make_sticker(photo_file, sticker_file)
        await telegram_bot.send_notification("New profile picture of {}:".format(to_check.username))
        await telegram_bot.send_sticker(settings.BOTLIST_NOTIFICATIONS_ID,
                         open(photo_file, 'rb'), timeout=360)


async def add_keywords(telegram_bot, response, to_check):
    if not isinstance(response, Response) or response.empty:
        return

    full_text = response.full_text.lower()
    # Search for botbuilder pattern to see if this bot is a Manybot/Chatfuelbot/etc.
    if botbuilder_pattern.search(full_text):
        to_check.botbuilder = True

    # Search /start and /help response for global list of keywords
    to_add = []
    for name in Keyword.get_distinct_names(exclude_from_bot=to_check):
        if re.search(r'\b{}\b'.format(name), full_text, re.IGNORECASE):
            to_add.append(name)

    to_add = [x for x in to_add if x not in settings.FORBIDDEN_KEYWORDS]

    if to_add:
        Keyword.insert_many([dict(name=k, entity=to_check) for k in to_add]).execute()
        msg = 'New keyword{}: {} for {}.'.format(
            's' if len(to_add) > 1 else '',
            ', '.join(['#' + k for k in to_add]),
            to_check.str_no_md)
        await telegram_bot.send_message(settings.BOTLIST_NOTIFICATIONS_ID, msg, timeout=40)
        log.info(msg)


async def result_reader(queue) -> Counter:
    stats = Counter()
    while True:
        value = await queue.get()
        if value is None:
            break
        stats.update([value])
    return stats


async def run(telegram_bot, bot_checker, bots, stop_event=None) -> Counter:
    result_queue = asyncio.Queue()
    reader_future = asyncio.ensure_future(result_reader(result_queue))

    semaphore = asyncio.Semaphore(settings.BOTCHECKER_CONCURRENT_COUNT)

    async def _worker(to_check_bot):
        async with semaphore:
            await check_bot(telegram_bot, bot_checker, to_check_bot, result_queue)

    tasks = []
    for to_check in bots:
        if stop_event and stop_event.is_set():
            break
        tasks.append(asyncio.ensure_future(_worker(to_check)))

    await asyncio.gather(*tasks, return_exceptions=True)

    await result_queue.put(None)
    return await reader_future


async def ping_bots_job(context):
    bot = context.bot
    bot_checker: BotChecker = context.job.data.get('checker')
    stop_event = context.job.data.get('stop')

    all_bots = BotModel.select(BotModel).where(
        (BotModel.approved == True)
        &
        ((BotModel.disabled_reason == BotModel.DisabledReason.offline) |
         BotModel.disabled_reason.is_null())
    ).order_by(
        BotModel.last_ping.asc()
    )

    start = time.time()
    result = await run(bot, bot_checker, all_bots, stop_event)  # type: Counter
    end = time.time()

    if not result:
        msg = "BotChecker encountered problems."
    else:
        msg = "BotChecker completed in {}s:\n".format(round(end - start))
        for k, v in result.items():
            msg += "\n- {} {}".format(v, k)
    await bot.send_message(settings.BOTLIST_NOTIFICATIONS_ID, msg)
    log.info(msg)


async def disable_decider(telegram_bot: TelegramBot, to_check: BotModel):
    assert to_check.disabled_reason != BotModel.DisabledReason.banned

    if (
            to_check.offline and
            to_check.offline_for > settings.DISABLE_BOT_INACTIVITY_DELTA and
            to_check.disabled_reason != BotModel.DisabledReason.offline
    ):
        # Disable if the bot has been offline for too long
        if to_check.disable(to_check.DisabledReason.offline):
            to_check.save()

            if to_check.last_response:
                reason = "its last response was " + helpers.slang_datetime(to_check.last_response)
            else:
                reason = "it's been offline for.. like... ever"

            msg = "{} disabled as {}.".format(to_check, reason)
            log.info(msg)
            await telegram_bot.send_message(settings.BOTLIST_NOTIFICATIONS_ID, msg, timeout=30,
                             parse_mode=ParseMode.MARKDOWN)
        else:
            log.info("huhwtf")
    elif (
            to_check.online and
            to_check.disabled_reason == BotModel.DisabledReason.offline
    ):
        # Re-enable if the bot is disabled and came back online
        if to_check.enable():
            to_check.save()
            msg = "{} was included in the @BotList again as it came back online.".format(to_check)
            log.info(msg)
            await telegram_bot.send_message(settings.BOTLIST_NOTIFICATIONS_ID, msg, timeout=30,
                             parse_mode=ParseMode.MARKDOWN)
        else:
            log.info("huhwtf")
