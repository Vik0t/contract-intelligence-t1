import gdown
import zipfile
file_url = "https://drive.google.com/file/d/1tiA14BfdsRb5sio8J-tAUuDXlZHdYGsf/view?usp=sharing"

gdown.download(
    url=file_url,
    output="dataset.zip", 
)


with zipfile.ZipFile('dataset.zip', 'r') as zip_ref:

    zip_ref.extractall('')