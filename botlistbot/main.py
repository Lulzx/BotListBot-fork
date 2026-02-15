import logging

import sentry_sdk
from logzero import logger as log
from sentry_sdk.integrations.logging import LoggingIntegration
from telegram.ext import ApplicationBuilder

from botlistbot import appglobals
from botlistbot import routing
from botlistbot import settings
from botlistbot.components import admin, basic
from botlistbot.custom_botlistbot import BotListBot
from botlistbot.lib.markdownformatter import MarkdownFormatter


def setup_logging():
    sentry_logging = LoggingIntegration(
        level=logging.INFO,
        event_level=logging.WARNING,
    )
    sentry_sdk.init(
        dsn=settings.SENTRY_URL,
        integrations=[sentry_logging],
        environment=settings.SENTRY_ENVIRONMENT,
    )


def main():
    if settings.is_sentry_enabled():
        setup_logging()

    bot_token = str(settings.BOT_TOKEN)

    application = (
        ApplicationBuilder()
        .token(bot_token)
        .read_timeout(8)
        .connect_timeout(7)
        .pool_timeout(max(settings.WORKER_COUNT, 4))
        .bot_class(BotListBot)
        .build()
    )

    application.bot.formatter = MarkdownFormatter(application.bot)

    # Initialize the BotChecker for pinging bots
    bot_checker = None
    if settings.RUN_BOTCHECKER:
        try:
            from botlistbot.components.userbot import (
                initialize_bot_checker,
                start_bot_checker,
            )

            bot_checker = initialize_bot_checker()
            if bot_checker:
                start_bot_checker(application.job_queue, bot_checker)
        except Exception as e:
            log.warning(f"BotChecker initialization skipped: {e}")

    routing.register(application, bot_checker)
    basic.register(application)

    application.job_queue.run_repeating(admin.last_update_job, interval=3600 * 24)

    if settings.DEV:
        log.info("Starting using long polling...")
        application.run_polling()
    else:
        log.info("Starting using webhooks...")
        application.run_webhook(
            listen="0.0.0.0",
            port=settings.PORT,
            url_path=settings.BOT_TOKEN,
            webhook_url=f"https://botlistbot.herokuapp.com/{settings.BOT_TOKEN}",
        )


if __name__ == "__main__":
    main()
