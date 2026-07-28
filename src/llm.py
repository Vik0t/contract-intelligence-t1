import requests
import json
from dotenv import load_dotenv
import os
load_dotenv()
api_key = os.getenv("OPENROUTER_API_KEY")

system_prompt = """You are a helpful assistant that extracts key data from contracts. 
You will be given a contract text
 and your task is to extract the following key data points:

 number, date, party1, party2, amount, contract_type, term, place, vat, inn1, inn2

 output the extracted data in and only in JSON format with the following structure:

 "meta": {
      "number": "100-22-2024",
      "date": "23.03.2026",
      "party1": "ООО \"ГаммаТрейд\"",
      "party2": "ООО \"ЭтаЛогистик\"",
      "amount": 1268390,
      "contract_type": "Договор хранения",
      "term": "20.08.2026",
      "place": "г. Казань",
      "vat": "10%",
      "inn1": "3470907725",
      "inn2": "6312492486"
    }
 """


def extract_contract_key_data(text):
    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        data=json.dumps({
            "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "messages": [
            {
              "role": "system",
              "content": system_prompt
            },
            {
              "role": "user",
              "content": text
            }
            ],
            "reasoning": {"enabled": False}
        })
    )
    response = response.json()
    print("СТРУКТУРА ОТВЕТА:", response)
    response = response['choices'][0]['message']['content']
    try:
        contract_data = json.loads(response)
        return contract_data
    except json.JSONDecodeError:
        return response
    
