from src.parsing import parse_file
from src.llm import extract_contract_key_data


def main():
    text = parse_file("dataset/Договор_001.docx")
    print(extract_contract_key_data(text))


if __name__ == "__main__":
    main()
