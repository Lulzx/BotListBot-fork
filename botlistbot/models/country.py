import emoji
from peewee import *

from botlistbot.models.basemodel import BaseModel


class Country(BaseModel):
    id = AutoField()
    name = CharField(unique=True)
    emoji = CharField()

    @property
    def emojized(self):
        return emoji.emojize(self.emoji, language='alias')

    def __str__(self):
        return self.name + ' ' + self.emojized
