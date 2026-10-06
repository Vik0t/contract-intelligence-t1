import gdown
import zipfile

# ссылка на dataset.zip (сами документы)
dataset_url = "https://drive.google.com/file/d/1gL5bwq3yOXkTBZuZbQkUXkqCyhBQgg7U/view?usp=sharing"
# ссылка на meta.zip (разметка, json на каждый файл)
meta_url = "https://drive.google.com/file/d/1aSvJMbpT9Umq2omGPZoRIPBtFmZN3lZz/view?usp=sharing"

gdown.download(url=dataset_url, output="dataset.zip")
gdown.download(url=meta_url, output="meta.zip")

with zipfile.ZipFile("dataset.zip", "r") as zip_ref:
    zip_ref.extractall("dataset")

with zipfile.ZipFile("meta.zip", "r") as zip_ref:
    zip_ref.extractall("meta")
