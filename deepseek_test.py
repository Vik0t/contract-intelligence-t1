from openai import OpenAI


client = OpenAI(
    base_url="https://deepcode.ci.nsu.ru/api/v1",
    api_key="sk-f9fe89f5c1dd4fbcbaa413b9261dca37"  
)

try:
    models_list = client.models.list()
    print("Доступные модели на сервере:")
    for model in models_list.data:
        print(f"- {model.id}")
except Exception as e:
    print(f"Не удалось получить список моделей: {e}")
completion = client.chat.completions.create(
    model="deepseek-ai/DeepSeek-V4-Flash-0731", 
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Привет! Напиши приветствие из 5 слов."}
    ]
)

print(completion.choices[0].message.content)
