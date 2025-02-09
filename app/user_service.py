from typing import List, Tuple, Optional
from models import User, UserChat, Chat

def process_chat_message(chat_id: int, text: str, llm_service) -> Tuple[Optional[str], List[Tuple[str, str, int]]]:
    """
    Обрабатывает сообщение из чата, ищет упоминания имен и соответствующих пользователей
    :param chat_id: ID чата
    :param text: Текст сообщения
    :param llm_service: Экземпляр LLMService для обработки имен
    :return: Кортеж (найденное_имя, список_подходящих_пользователей)
    """
    # Получаем всех пользователей в чате
    chat_users = (User
                 .select(User.firstname, User.username, User.id)
                 .join(UserChat)
                 .join(Chat)
                 .where(Chat.tg_chat_id == chat_id)
                 .tuples())
    
    # Фильтруем пользователей без имени или username
    valid_users = [
        (firstname, username, user_id)
        for firstname, username, user_id in chat_users
        if firstname and username
    ]
    
    if not valid_users:
        return None, []
    
    # Используем LLM для анализа текста и поиска соответствий
    return llm_service.process_name_mention(text, valid_users)

def replace_name_with_username(text: str, found_name: str, username: str) -> str:
    """
    Заменяет найденное имя на @username в тексте
    :param text: Исходный текст
    :param found_name: Найденное имя
    :param username: Username пользователя
    :return: Измененный текст
    """
    import re

    # Создаем регулярное выражение для поиска имени в начале текста
    # Учитываем возможные пробелы и знаки препинания после имени
    pattern = f"^{re.escape(found_name)}([\\s,.!?]|$)"
    
    # Ищем совпадение с учетом регистра
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        # Получаем символ или пустую строку после имени
        suffix = match.group(1) if match.group(1) else ''
        # Заменяем имя на @username, сохраняя символ после имени
        return f"@{username}{suffix}" + text[match.end():]
    
    return text