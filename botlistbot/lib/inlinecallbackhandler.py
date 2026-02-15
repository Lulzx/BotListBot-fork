import json
import logging
from typing import Callable, Dict, Optional

from telegram import Update
from telegram.ext import BaseHandler


class InlineCallbackHandler(BaseHandler):
    def __init__(self,
                 action,
                 callback,
                 serialize: Callable[[Dict], Dict] = None):
        super().__init__(callback)

        if serialize:
            if not callable(serialize):
                raise ValueError("The `serialize` attribute must be a callable function.")
        self.serialize = serialize
        self.action = action
        self.log = logging.getLogger(__name__)

    def check_update(self, update: object) -> Optional[bool]:
        if isinstance(update, Update) and update.callback_query:
            if self.action:
                try:
                    obj = json.loads(str(update.callback_query.data))
                except (json.JSONDecodeError, TypeError):
                    return False
                if 'a' in obj:
                    action = obj['a']
                    return action == self.action
                else:
                    self.log.warning("No action in update.")
            else:
                return True
        return False

    async def handle_update(self, update, application, check_result, context):
        obj = json.loads(str(update.callback_query.data))

        if self.serialize is not None:
            serialized = self.serialize(obj)
            context.serialized = serialized

        return await self.callback(update, context)
