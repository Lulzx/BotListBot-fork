from peewee import *
from botlistbot.models.basemodel import BaseModel


class Notifications(BaseModel):
    id = AutoField()
    chat_id = BigIntegerField(unique=True)
    enabled = BooleanField(default=True)
    last_notification = DateField(null=True)
