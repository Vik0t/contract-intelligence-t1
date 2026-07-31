from src.llm import extract_contract_key_data
import json

def evaluate_llm(dataset_path, number_of_samples=10):
    with open(f"{dataset_path}/meta.json", 'r',  encoding='utf-8') as file:
        ground_truth = json.load(file)

    failure_times, evaluations = 0, 0

    for i in range(1, number_of_samples + 1):
        llm_output = extract_contract_key_data(f"{dataset_path}/Договор_{i:03d}.pdf")
        if not compare_outputs(ground_truth[i], llm_output):
            failure_times += 1
        evaluations += 1

    print(f"Failure Times: {failure_times}")
    print(f"Total Evaluations: {evaluations}")


def compare_outputs(ground_truth, llm_output):
    return ground_truth == llm_output
