from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import fitz
import torch
from PIL import Image
from transformers import AutoModelForMultimodalLM, AutoProcessor

MODEL_ID = "numind/NuExtract3"

# Структура шаблона совпадает со структурой ожидаемого JSON.
# verbatim-string просит модель возвращать текст дословно из документа.
CONTRACT_TEMPLATE: dict[str, Any] = {
    "contract_number": {
        "value": "verbatim-string",
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "contract_date": {
        "value": "date",
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "contract_type": {
        "value": "string",
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "place": {
        "value": "verbatim-string",
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "term": {
        "value": "verbatim-string",
        "semantic_type": [
            "contract_end_date",
            "validity_period",
            "performance_deadline",
            "return_deadline",
            "indefinite",
            "other",
        ],
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "parties": [
        {
            "name": "verbatim-string",
            "role": "verbatim-string",
            "inn": "verbatim-string",
            "name_evidence": "verbatim-string",
            "name_page_number": "integer",
            "inn_evidence": "verbatim-string",
            "inn_page_number": "integer",
        }
    ],
    "total_amount": {
        "value": "number",
        "raw_value": "verbatim-string",
        "currency": "currency",
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
    "vat": {
        "raw_value": "verbatim-string",
        "rate": "number",
        "mode": ["included", "excluded", "not_subject", "not_stated"],
        "evidence": "verbatim-string",
        "page_number": "integer",
    },
}

INSTRUCTIONS = """
Извлеки реквизиты именно заключаемого договора из русскоязычного документа.

Правила:
1. Ничего не выдумывай. Если значение явно не найдено, верни null или пустой список.
2. contract_number — номер основного договора, а не номер приложения, счета, спецификации,
   доверенности или входящего письма.
3. contract_date — дата заключения основного договора. Не используй даты приложений,
   платежей, доверенностей или регистрации, если они не являются датой договора.
4. contract_type — вид заключаемого договора, например договор поставки, займа,
   подряда, хранения или оказания услуг. Подтверди его заголовком или предметом договора.
5. place — место заключения договора из шапки. Не используй адрес стороны, банка,
   суда, объекта работ или место исполнения обязательств.
6. term — срок действия договора или срок исполнения основного обязательства,
   соответствующий смыслу договора. Не используй срок оплаты, гарантии, уведомления
   или ответа на претензию. Если договор бессрочный, верни значение из документа
   и semantic_type=indefinite.
7. parties — стороны, которые заключают договор. Не считай сторонами банки, получателей
   платежа, контактных лиц и подписантов самих по себе. Роль бери из формулировок документа,
   например Заказчик, Исполнитель, Поставщик, Покупатель. Для названия и ИНН верни
   отдельные evidence и page_number. Не связывай ИНН одной стороны с другой стороной.
8. total_amount — общая цена/стоимость договора. Не подставляй отдельный платеж,
   штраф, обеспечение или сумму одной спецификации, если это не вся цена договора.
9. vat — режим и ставка НДС именно для общей суммы договора. Для формулировки
   "без НДС" используй mode=not_subject и rate=null. Если НДС не указан,
   используй mode=not_stated.
10. evidence должно быть короткой дословной цитатой, подтверждающей конкретное значение.
11. page_number должен соответствовать метке PAGE N, расположенной перед изображением страницы.
12. Для total_amount.value верни число без пробелов и обозначения валюты,
    а в total_amount.raw_value сохрани сумму дословно из документа.
""".strip()


def pdf_to_images(path: Path, dpi: int, start_page: int, max_pages: int) -> tuple[list[Image.Image], int]:
    images: list[Image.Image] = []
    with fitz.open(path) as doc:
        total_pages = len(doc)
        start_index = start_page - 1
        if start_index < 0 or start_index >= total_pages:
            raise ValueError(f"start-page должен быть от 1 до {total_pages}")

        stop_index = min(total_pages, start_index + max_pages)
        for page_index in range(start_index, stop_index):
            page = doc[page_index]
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(image)

    return images, total_pages


def load_document(path: Path, dpi: int, start_page: int, max_pages: int) -> tuple[list[Image.Image], int]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return pdf_to_images(path, dpi=dpi, start_page=start_page, max_pages=max_pages)
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        return [Image.open(path).convert("RGB")], 1
    raise ValueError("Поддерживаются PDF и изображения PNG/JPG/WEBP/BMP/TIFF")


def build_messages(images: list[Image.Image], start_page: int) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for offset, image in enumerate(images):
        page_number = start_page + offset
        content.append({"type": "text", "text": f"PAGE {page_number}"})
        content.append({"type": "image", "image": image})
    return [{"role": "user", "content": content}]


def parse_json_output(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Модель не вернула JSON")
        return json.loads(cleaned[start : end + 1])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Извлечение реквизитов договора через numind/NuExtract3"
    )
    parser.add_argument("document", type=Path, help="Путь к PDF или изображению")
    parser.add_argument("--output", type=Path, default=Path("contract_result.json"))
    parser.add_argument("--raw-output", type=Path, default=Path("contract_result_raw.txt"))
    parser.add_argument("--dpi", type=int, default=120, help="DPI рендеринга PDF")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Сколько страниц отправить за один запуск. Для 16 ГБ VRAM начните с 2–3.",
    )
    parser.add_argument(
        "--thinking",
        action="store_true",
        help="Включить reasoning для сложного документа; медленнее и требует больше памяти.",
    )
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    args = parser.parse_args()

    if not args.document.exists():
        print(f"Файл не найден: {args.document}", file=sys.stderr)
        return 2
    if not torch.cuda.is_available():
        print("CUDA недоступна. Сначала запустите check_cuda.py.", file=sys.stderr)
        return 3

    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"Загрузка {MODEL_ID}. При первом запуске будет скачано около 9.3 ГБ...")

    processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
    model = AutoModelForMultimodalLM.from_pretrained(
        MODEL_ID,
        dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    ).eval()

    images, total_pages = load_document(
        args.document,
        dpi=args.dpi,
        start_page=args.start_page,
        max_pages=args.max_pages,
    )
    last_page = args.start_page + len(images) - 1
    print(f"Обрабатываются страницы {args.start_page}–{last_page} из {total_pages}")
    if last_page < total_pages:
        print(
            "Внимание: документ обработан не полностью. Для следующего блока используйте "
            f"--start-page {last_page + 1}."
        )

    messages = build_messages(images, start_page=args.start_page)
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
        template=json.dumps(CONTRACT_TEMPLATE, ensure_ascii=False, indent=2),
        instructions=INSTRUCTIONS,
        enable_thinking=args.thinking,
    ).to(model.device)

    print("Запуск извлечения...")
    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
        )

    generated_ids = generated_ids[:, inputs["input_ids"].shape[1] :]
    raw = processor.batch_decode(
        generated_ids,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0].strip()

    args.raw_output.write_text(raw, encoding="utf-8")

    try:
        parsed = parse_json_output(raw)
    except Exception as exc:
        print(f"Не удалось разобрать JSON: {exc}", file=sys.stderr)
        print(f"Сырой ответ сохранён в {args.raw_output}")
        return 4

    args.output.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
    print(f"\nРезультат: {args.output.resolve()}")
    print(f"Сырой ответ: {args.raw_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
