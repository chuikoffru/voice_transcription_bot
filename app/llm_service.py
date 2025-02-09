import openai
from typing import Optional, List, Tuple

class LLMService:
    def __init__(self, api_key: str):
        self.client = openai.OpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=api_key,
        )

    def check_name_mention(self, text: str) -> Optional[str]:
        """Проверяет, есть ли обращение по имени в начале текста"""
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that analyzes text in Russian language. "
                                "Your task is to identify if there's a name mentioned at the beginning of the text "
                                "that appears to be addressing someone. Return ONLY the found name or None if no name found."
                    },
                    {
                        "role": "user",
                        "content": f"Is there a name mentioned at the beginning of this text that appears to be addressing someone? Text: {text}"
                    }
                ],
                temperature=0,
                max_tokens=50
            )
            
            result = response.choices[0].message.content.strip()
            if result.lower() == "none":
                return None
            return result
        except Exception as e:
            print(f"Error in check_name_mention: {e}")
            return None