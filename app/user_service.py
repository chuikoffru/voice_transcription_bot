from typing import List, Tuple, Optional
from models import User, UserChat, Chat

def find_matching_users(chat_id: int, found_name: str) -> List[Tuple[str, str, int]]:
    """
    Находит пользователей в чате, чьи имена соответствуют найденному имени
    :param chat_id: ID чата
    :param found_name: Найденное имя
    :return: Список кортежей (firstname, username, user_id)
    """
    found_name = found_name.lower()
    matching_users = []
    
    # Получаем всех пользователей в чате
    chat_users = (User
                 .select(User.firstname, User.username, User.id)
                 .join(UserChat)
                 .join(Chat)
                 .where(Chat.tg_chat_id == chat_id)
                 .tuples())
    
    for firstname, username, user_id in chat_users:
        if firstname and firstname.lower().startswith(found_name):
            matching_users.append((firstname, username, user_id))
    
    return matching_users

def replace_name_with_username(text: str, found_name: str, username: str) -> str:
    """
    Заменяет найденное имя на @username в тексте
    :param text: Исходный текст
    :param found_name: Найденное имя
    :param username: Username пользователя
    :return: Измененный текст
    """
    # Ищем имя в начале текста с учетом регистра
    if text.lower().startswith(found_name.lower()):
        name_end = len(found_name)
        return f"@{username}" + text[name_end:]
    return text