from telegram.error import BadRequest
from typing import Callable

from logzero import logger as log
from telegram.ext import ExtBot

from botlistbot import settings
from botlistbot import util


class BotListBot(ExtBot):
    async def send_notification(self, message, **kwargs):
        await self.send_message(
            settings.BOTLIST_NOTIFICATIONS_ID,
            util.escape_markdown(message),
            parse_mode="markdown",
            read_timeout=20,
            **kwargs,
        )
        log.info(message)

    async def _wrap_safe(self, coro, safe: bool):
        if not safe:
            return await coro
        try:
            return await coro
        except BadRequest:
            return None

    async def answer_inline_query(
            self,
            inline_query_id,
            results,
            cache_time=300,
            is_personal=None,
            next_offset=None,
            button=None,
            safe=True,
            **kwargs,
    ):
        return await self._wrap_safe(
            super().answer_inline_query(
                inline_query_id,
                results,
                cache_time=cache_time,
                is_personal=is_personal,
                next_offset=next_offset,
                button=button,
                **kwargs,
            ),
            safe=safe
        )

    async def delete_message(self, chat_id, message_id, safe=False, **kwargs):
        return await self._wrap_safe(
            super().delete_message(chat_id, message_id, **kwargs),
            safe=safe
        )
