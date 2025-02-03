from datetime import datetime
from peewee import *

# Инициализация базы данных
db = SqliteDatabase("transcription_bot.db")


class BaseModel(Model):
    class Meta:
        database = db


class Usage(BaseModel):
    id = AutoField()
    tg_user_id = IntegerField(index=True)
    message_id = IntegerField()
    duration = FloatField()  # длительность в секундах
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "usages"


def init_db():
    """Инициализация базы данных и создание таблиц"""
    db.connect()
    db.create_tables([Usage])
    db.close()
