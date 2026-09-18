"""
Запуск:
    uv run tests/test_summarize.py --ids 4 7 --format pdf --backend hf_space

    --backend hf_space - hf_space_pipeline
    --backend local - local_extraction

    --ids - номера документов для теста

    --format - docx или pdf
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import json
from pathlib import Path

from src.extraction.pipeline import extract_contract_key_data, extract_text_from_document
from src.extraction.hf_space_pipeline import extract_contract_key_data_hf_space
from src.extraction.summary import summarize_document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset", help="папка с файлами документов")
    parser.add_argument("--meta", default="meta/meta", help="папка с {id}.json разметкой (не обязательна для теста)")
    parser.add_argument("--ids", type=int, nargs="+", default=[4, 7], help="doc_id для теста, по умолчанию 4 и 7")
    parser.add_argument("--format", choices=["docx", "pdf", "png"], default="pdf")
    parser.add_argument("--backend", choices=["local", "hf_space"], default="hf_space")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    meta_dir = Path(args.meta)

    for doc_id in args.ids:
        meta_path = meta_dir / f"{doc_id}.json"
        if not meta_path.is_file():
            print(f"--- doc_id {doc_id}: нет файла разметки {meta_path}, пропуск ---")
            continue

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        filename = meta.get("files", {}).get(args.format)
        if not filename:
            print(f"--- doc_id {doc_id}: нет формата {args.format} для этого документа, пропуск ---")
            continue

        doc_path = dataset / filename
        if not doc_path.is_file():
            print(f"--- doc_id {doc_id}: файл {doc_path} не найден на диске, пропуск ---")
            continue

        print(f"\n=== doc_id {doc_id} ({args.format}, backend={args.backend}) ===")

        if args.backend == "local":
            extracted_fields, _token_usage = extract_contract_key_data(document=doc_path)
        else:
            extracted_fields = extract_contract_key_data_hf_space(document=doc_path)

        print("Извлечённые поля:")
        print(json.dumps(extracted_fields, ensure_ascii=False, indent=2))

        document_text, _document_ir = extract_text_from_document(doc_path)

        summary = summarize_document(document_text, extracted_fields)

        print("\nSummary:")
        print(summary)
        print("=" * 60)


if __name__ == "__main__":
    main()