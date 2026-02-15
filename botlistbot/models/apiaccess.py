from peewee import *
from botlistbot.models.user import User
from botlistbot.models.basemodel import BaseModel


class APIAccess(BaseModel):
    user = ForeignKeyField(User)
    token = CharField(64)
    webhook_url = CharField(null=True)
