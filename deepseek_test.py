"""Manual DeepCode diagnostic. Run explicitly after configuring the API in .env."""

import os
from dotenv import load_dotenv


def main():
    load_dotenv()
    api_key = os.getenv('OPENAI_API_KEY') or os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        raise SystemExit('Заполните OPENAI_API_KEY (или OPENROUTER_API_KEY) в .env.')
    from openai import OpenAI
    with OpenAI(
        base_url=os.getenv('OPENAI_BASE_URL', 'https://deepcode.ci.nsu.ru/api/v1'),
        api_key=api_key,
    ) as client:
        try:
            models_list = client.models.list()
            print('Доступные модели на сервере:')
            for model in models_list.data:
                print(f'- {model.id}')
        except Exception as exc:
            print(f'Не удалось получить список моделей: {type(exc).__name__}')
        completion = client.chat.completions.create(
            model=os.getenv('DEEPCODE_TEST_MODEL', 'deepseek-ai/DeepSeek-V4-Flash-0731'),
            messages=[
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Привет! Напиши приветствие из 5 слов.'},
            ],
        )
        print(completion.choices[0].message.content)


if __name__ == '__main__':
    main()
