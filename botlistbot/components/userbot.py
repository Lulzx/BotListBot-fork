# -*- coding: utf-8 -*-
import asyncio
import threading

from logzero import logger as log

from botlistbot import appglobals
from botlistbot import settings

BotChecker = None
_bot_checker_instance = None


def _create_bot_checker():
    """Create and return a BotChecker instance using the botcheckerworker module."""
    from botlistbot.botcheckerworker.botchecker import BotChecker as _BotChecker

    loop = appglobals.loop

    checker = _BotChecker(
        event_loop=loop,
        session_name=settings.USERBOT_SESSION,
        api_id=settings.API_ID,
        api_hash=settings.API_HASH,
        phone_number=settings.USERBOT_PHONE,
        workdir=str(appglobals.ACCOUNTS_DIR),
    )
    return checker


def initialize_bot_checker():
    """
    Initialize the BotChecker if configured.
    Returns the BotChecker instance or None if not configured/available.
    """
    global BotChecker, _bot_checker_instance

    if not settings.RUN_BOTCHECKER:
        log.info("BotChecker disabled in settings.")
        return None

    if not all([settings.API_ID, settings.API_HASH, settings.USERBOT_SESSION]):
        log.warning(
            "BotChecker not configured: missing API_ID, API_HASH, or USERBOT_SESSION."
        )
        return None

    try:
        from botlistbot.botcheckerworker.botchecker import BotChecker as _BotChecker

        BotChecker = _BotChecker
        _bot_checker_instance = _create_bot_checker()
        log.info("BotChecker initialized successfully.")
        return _bot_checker_instance
    except ImportError as e:
        log.warning(f"BotChecker dependencies not available: {e}")
        return None
    except Exception as e:
        log.error(f"Failed to initialize BotChecker: {e}")
        return None


def start_bot_checker(job_queue, bot_checker):
    """
    Start the BotChecker userbot and set up the periodic ping job.

    Args:
        job_queue: The PTB job queue for scheduling periodic checks.
        bot_checker: The BotChecker instance to use.
    """
    if bot_checker is None:
        return

    from botlistbot.botcheckerworker.botchecker import ping_bots_job

    try:
        loop = bot_checker.event_loop
        bot_checker.start()
        log.info("BotChecker userbot started.")
    except Exception as e:
        log.error(f"Failed to start BotChecker userbot: {e}")
        return

    stop_event = threading.Event()
    context = {"checker": bot_checker, "stop": stop_event}

    job_queue.run_repeating(
        ping_bots_job,
        context=context,
        first=60,  # Start first check after 60 seconds
        interval=settings.BOTCHECKER_INTERVAL,
    )
    log.info(
        f"BotChecker periodic job scheduled (interval: {settings.BOTCHECKER_INTERVAL}s)."
    )


def get_bot_checker():
    """Get the current BotChecker instance."""
    return _bot_checker_instance
