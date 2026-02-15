import json
import logging

from telegram import Update
from telegram.ext import BaseHandler


class JSONCallbackHandler(BaseHandler):

    def __init__(self, action, callback, mapping=None):
        super().__init__(callback)
        self.action = action
        self.mapping = mapping
        self.logger = logging.getLogger(__name__)

    def check_update(self, update):
        if isinstance(update, Update) and update.callback_query:
            if self.action:
                try:
                    obj = json.loads(str(update.callback_query.data))
                except (json.JSONDecodeError, TypeError):
                    return False
                if 'a' in obj:
                    return obj['a'] == self.action
                else:
                    self.logger.error("No action in update.")
                    return False
            else:
                return True
        return False

    async def handle_update(self, update, application, check_result, context):
        obj = json.loads(str(update.callback_query.data))

        kwargs = {}
        if self.mapping is not None:
            for key, value in self.mapping.items():
                db_wrapper = value[0]
                method_name = value[1]
                if key in obj:
                    try:
                        model_obj = db_wrapper.get(db_wrapper.id == obj[key])
                        kwargs[method_name] = model_obj
                    except db_wrapper.DoesNotExist:
                        self.logger.error(
                            "Field {} with id {} was not found in database.".format(key, obj[key])
                        )
                else:
                    self.logger.error("Expected field {} was not supplied.".format(key))

        # Store mapped objects on context for the callback to access
        context.json_data = obj
        context.mapped_objects = kwargs

        return await self.callback(update, context)
