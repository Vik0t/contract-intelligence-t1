import argparse
import json

from cuda_dll_setup import configure_cuda_dlls

import platform
if platform.system() != "Darwin":
    configure_cuda_dlls()

from src.local_extraction import extract_contract_key_data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Извлечение 11 ключевых полей договора"
    )
    parser.add_argument(
        "document",
        nargs="?",
        default="dataset/Договор_001.pdf",
        help="Путь к PDF или DOCX",
    )
    args = parser.parse_args()

    result = extract_contract_key_data(args.document)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
