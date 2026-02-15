import json
import logging
from typing import Callable, Optional

from telegram import Update
from telegram.ext import BaseHandler


class InlineActionHandler(BaseHandler):
    def __init__(self,
                 action: int,
                 callback: Callable):
        super().__init__(callback)

        self.action = action
        self.log = logging.getLogger(__name__)

    def check_update(self, update: object) -> Optional[bool]:
        if isinstance(update, Update) and update.callback_query:
            obj = update.callback_manager.lookup_callback(update.callback_query.data)
            if obj is None:
                return False
            return obj['action'] == self.action
        return False

    async def handle_update(self, update, application, check_result, context):
        obj = update.callback_manager.lookup_callback(update.callback_query.data)

        data = obj['data']
        update.callback_data = data

        return await self.callback(update, context)
