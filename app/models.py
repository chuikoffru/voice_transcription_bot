from datetime import datetime
from peewee import *
from aiogram import types

# Инициализация базы данных
db = SqliteDatabase("transcription_bot.db")


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    id = AutoField()
    firstname = CharField(null=True)
    lastname = CharField(null=True)
    username = CharField(null=True)
    tg_id = IntegerField(unique=True, index=True, constraints=[SQL("UNIQUE")])

    class Meta:
        table_name = "users"


class Chat(BaseModel):
    id = AutoField()
    tg_chat_id = IntegerField(unique=True, index=True, constraints=[SQL("UNIQUE")])
    name = CharField(null=True)

    class Meta:
        table_name = "chats"


class UserChat(BaseModel):
    id = AutoField()
    user = ForeignKeyField(User, backref="chats")
    chat = ForeignKeyField(Chat, backref="users")

    class Meta:
        table_name = "user_chats"
        # Создаем составной индекс для оптимизации поиска и уникальности пары user-chat
        indexes = (
            (("user", "chat"), True),  # True означает уникальный индекс
        )


class Usage(BaseModel):
    id = AutoField()
    user = ForeignKeyField(User, backref="usages")
    chat = ForeignKeyField(Chat, backref="usages")
    message_id = IntegerField()
    duration = FloatField()  # длительность в секундах
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "usages"


def upsert_user(tg_user: types.User) -> User:
    # Сначала пытаемся найти пользователя по индексированному полю tg_id
    try:
        user = User.get(User.tg_id == tg_user.id)
        return user
    except User.DoesNotExist:
        # Если пользователь не найден, выполняем upsert
        data = {
            "tg_id": tg_user.id,
            "firstname": tg_user.first_name,
            "lastname": tg_user.last_name,
            "username": tg_user.username,
        }
        User.insert(**data).on_conflict(
            conflict_target=[User.tg_id],
            update={key: data[key] for key in data if key != "tg_id"},
        ).execute()
        return User.get(User.tg_id == tg_user.id)


def upsert_chat(message: types.Message) -> Chat:
    # Сначала пытаемся найти чат по индексированному полю tg_chat_id
    try:
        chat = Chat.get(Chat.tg_chat_id == message.chat.id)
        return chat
    except Chat.DoesNotExist:
        # Если чат не найден, выполняем upsert
        data = {
            "tg_chat_id": message.chat.id,
            "name": message.chat.title or message.chat.username or str(message.chat.id),
        }
        Chat.insert(**data).on_conflict(
            conflict_target=[Chat.tg_chat_id],
            update={key: data[key] for key in data if key != "tg_chat_id"},
        ).execute()
        return Chat.get(Chat.tg_chat_id == message.chat.id)


def upsert_user_chat(user: User, chat: Chat) -> UserChat:
    # Используем get_or_create для оптимальной вставки записи
    user_chat, created = UserChat.get_or_create(user=user, chat=chat)
    return user_chat


def init_db():
    """Инициализация базы данных и создание таблиц"""
    db.connect()
    db.create_tables([User, Chat, UserChat, Usage])
    db.close()
