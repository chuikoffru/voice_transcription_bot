import openai
from typing import Optional, List, Tuple

from typing import List, Tuple, Optional
import json

class LLMService:
    def __init__(self, api_key: str):
        self.client = openai.OpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=api_key,
        )

    def process_name_mention(self, text: str, user_names: List[Tuple[str, str, int]]) -> Tuple[Optional[str], List[Tuple[str, str, int]]]:
        """
        Проверяет наличие имени в начале текста и находит соответствующих пользователей
        
        :param text: Текст для анализа
        :param user_names: Список кортежей (firstname, username, user_id)
        :return: Кортеж (найденное_имя, список_подходящих_пользователей)
        """
        try:
            # Создаем контекст с примерами вариаций имен
            name_examples = {
                "Konstantin": ["Костя", "Костян", "Константин", "Kostya"],
                "Alexander": ["Саша", "Саня", "Александр", "Шура", "Sasha"],
                "Vladimir": ["Вова", "Володя", "Владимир", "Vova"],
                "Dmitry": ["Дима", "Димон", "Дмитрий", "Dimka"],
                "Mikhail": ["Миша", "Михаил", "Мишаня", "Misha"],
                "Nikolay": ["Коля", "Николай", "Колян", "Kolya"],
            }
            
            # Формируем список имен пользователей для проверки
            users_json = json.dumps([
                {"firstname": firstname, "username": username, "id": user_id}
                for firstname, username, user_id in user_names
            ], ensure_ascii=False)

            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are a helpful assistant that analyzes Russian text and matches names with their variations.

Examples of name variations:
{json.dumps(name_examples, ensure_ascii=False, indent=2)}

Your task is to:
1. Find if there's a name mentioned at the beginning of the text that appears to be addressing someone
2. If a name is found, identify which users from the provided list match this name, considering:
   - Different languages (Russian/English)
   - Diminutive forms and nicknames
   - Common variations of the name

Return a JSON object in the following format:
{{
    "found_name": "string or null",  // The name found in the text, or null if none found
    "matching_ids": [1, 2, 3]        // Array of matching user IDs, or empty array if no matches
}}"""
                    },
                    {
                        "role": "user",
                        "content": f"""Text to analyze: {text}
Available users: {users_json}

Return the analysis result as JSON."""
                    }
                ],
                temperature=0,
                max_tokens=150
            )
            
            result = response.choices[0].message.content.strip()
            # Удаляем маркеры кода JSON, если они есть
            result = result.strip('`').strip()
            if result.startswith('json'):
                result = result[4:].strip()
                
            try:
                parsed = json.loads(result)
                found_name = parsed.get("found_name")
                matching_ids = parsed.get("matching_ids", [])
                
                if not found_name:
                    return None, []
                
                # Фильтруем пользователей по найденным ID
                matching_users = [
                    (firstname, username, user_id)
                    for firstname, username, user_id in user_names
                    if user_id in matching_ids
                ]
                
                return found_name, matching_users
                
            except json.JSONDecodeError as e:
                print(f"Error decoding LLM response: {result}")
                print(f"JSON error: {e}")
                return None, []
                
        except Exception as e:
            print(f"Error in process_name_mention: {e}")
            return None, []