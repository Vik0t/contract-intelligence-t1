from __future__ import annotations

from typing import Any

CONTRACT_TYPE_LABELS = [
    "Договор займа",
    "Договор перевозки",
    "Договор поставки",
    "Договор купли-продажи",
    "Договор возмездного оказания услуг",
    "Договор подряда",
    "Договор страхования имущества",
    "Договор хранения",
    "Договор коммерческой концессии",
    "Договор возмездного оказания образовательных услуг",
    "Договор страхования гражданской ответственности",
    "Трудовой договор",
    "Договор транспортно-экспедиционного обслуживания",
    "Договор оказания образовательных услуг",
]

TERM_SEMANTIC_TYPES = [
    "contract_end_date",
    "loan_repayment_date",
    "service_period_end_date",
]

# Структура шаблона совпадает со структурой ожидаемого JSON.
# verbatim-string-or-null просит модель возвращать текст дословно из документа
# либо null, если значение не найдено.
CONTRACT_TEMPLATE: dict[str, Any] = {
    "contract_number": {
        "value": "verbatim-string-or-null",
        "evidence": "verbatim-string-or-null",
        "page_number": "integer-or-null",
    },
    "contract_date": {
        "value": "YYYY-MM-DD-or-null",
        "evidence": "verbatim-string-or-null",
        "page_number": "integer-or-null",
    },
    "contract_type": {
        "value": CONTRACT_TYPE_LABELS,
        "raw_value": "verbatim-string-or-null",
        "evidence": "verbatim-string-or-null",
        "page_number": "integer-or-null",
    },
    "place": {
        "value": "verbatim-string-or-null",
        "evidence": "verbatim-string-or-null",
        "page_number": "integer-or-null",
    },
    "term": {
        "value": "YYYY-MM-DD-or-null",
        "raw_value": "verbatim-string-or-null",
        "semantic_type": TERM_SEMANTIC_TYPES,
        "evidence": "verbatim-string-or-null",
        "page_number": "integer-or-null",
    },
    "parties": [
        {
            "name": "verbatim-string-or-null",
            "role": "verbatim-string-or-null",
            "inn": "verbatim-string-or-null",
            "name_evidence": "verbatim-string-or-null",
            "name_page_number": "integer-or-null",
            "inn_evidence": "verbatim-string-or-null",
            "inn_page_number": "integer-or-null",
        }
    ],
    "total_amount": {
        "value": "number-or-null",
        "raw_value": "verbatim-string-or-null",
        "currency": "currency-or-null",
        "evidence": "verbatim-string-or-null",
        "page_number": "integer-or-null",
    },
    "vat": {
        "raw_value": "verbatim-string-or-null",
        "rate": "number-or-null",
        "mode": ["included", "excluded", "not_subject", "not_stated"],
        "evidence": "verbatim-string-or-null",
        "page_number": "integer-or-null",
    },
}

INSTRUCTIONS = f"""
Извлеки реквизиты именно заключаемого договора из русскоязычного документа.

Общие правила:
1. Ничего не выдумывай. Если значение явно не найдено, верни null или пустой список.
2. Для каждого значения верни короткое дословное evidence из документа.
3. Не путай основной договор с приложениями, счетами, доверенностями и письмами.

contract_type:
- value должен быть ровно одним значением из этого списка:
  {", ".join(CONTRACT_TYPE_LABELS)}.
- Определяй тип по заголовку и предмету договора, а не по случайным упоминаниям в реквизитах.
- Нормализуй формулировки: "перевозки" -> "Договор перевозки"; транспортная экспедиция ->
  "Договор транспортно-экспедиционного обслуживания".
- Для страхования различай имущество и гражданскую ответственность по предмету договора.
- Для образовательных услуг различай обычное оказание образовательных услуг и возмездное оказание.
- Не возвращай номер договора, скобки, пояснения или новый класс вне списка.

term:
- value возвращай только в формате YYYY-MM-DD.
- semantic_type выбирай только из:
  contract_end_date, loan_repayment_date, service_period_end_date.
- Выбирай дату окончания срока договора/займа/периода услуг, а не дату подписания.
- Если написано "с X по Y", возвращай дату Y.
- Для займа выбирай дату возврата или погашения займа.
- Игнорируй даты оплаты, платежей, поставки, гарантии, уведомлений, претензий и штрафов.
- raw_value и evidence должны содержать исходную формулировку срока.

contract_date:
- value также возвращай в формате YYYY-MM-DD.
- Не используй даты приложений, оплат, платежей и регистрации.
""".strip()