from src.parsing import parse_file
from src.llm import extract_contract_key_data

from src.evaluate import evaluate_llm

def main():
    
    text = parse_file("dataset/Договор_002.docx")
    print(extract_contract_key_data(text))
    #evaluate_llm("dataset")

if __name__ == "__main__":
    main()
