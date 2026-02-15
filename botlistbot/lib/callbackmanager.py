import json
from typing import Any, Dict, Optional, Union
from uuid import uuid4
from telegram import InlineKeyboardButton


class CallbackManager:
    def __init__(self, redis_client, user):
        self.redis = redis_client
        self._key = f'callbacks_{user.id}'

    def create_callback(self, action: int, data: Dict) -> str:
        id_ = str(uuid4())
        callback = dict(action=action, data=data)
        self.redis.hset(self._key, id_, json.dumps(callback))
        return id_

    def inline_button(self, caption: str, action: int, data: Dict = None) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=caption,
            callback_data=self.create_callback(action, data)
        )

    def lookup_callback(self, id_: Union[str, uuid4]) -> Optional[Any]:
        raw = self.redis.hget(self._key, id_)
        if raw is None:
            return None
        return json.loads(raw)
