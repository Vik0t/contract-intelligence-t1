from pypdf import PdfReader
import docx
import fitz
import pytesseract
from pdf2image import convert_from_path

def is_image_only_pdf(pdf_path):
    """Returns True if the PDF contains images but zero digital text on all pages."""
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening file: {e}")
        return False

    has_images = False
    has_text = False

    for page in doc:
        # 1. Extract digital text from the page
        text = page.get_text().strip()
        if text:
            has_text = True
            break  # Early exit if we find digital text anywhere

        # 2. Check for embedded images (XObjects) on the page
        if page.get_images():
            has_images = True

    doc.close()

    # The PDF is "just images" if we found images and absolutely no digital text
    return has_images and not has_text


def ocr_image(image):
    """
    Performs OCR on a given image and returns the extracted text.

    Args:
        image (PIL.Image): The image to perform OCR on.
    """
    images = convert_from_path(image, dpi=300)

    text_results = []

    # 2. Loop through images and apply OCR
    for i, img in enumerate(images):
        text = pytesseract.image_to_string(img)
        text_results.append(text)

    return text_results

def parse_pdf(file_path):
    """
    парсит пдф

    Args:
        file_path (str): The path to the PDF file.
    """
    if is_image_only_pdf(file_path):
        return ocr_image(file_path)
    reader = PdfReader(file_path)
    full_text = ""

    # Loop through each page and extract text
    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"

    return full_text



def parse_docx(file_path):
    """
    парсит docx файл

    Args:
        file_path (str): The path to the DOCX file.
    """
    doc = docx.Document(file_path)
   
    full_text = [para.text for para in doc.paragraphs]
    
    return '\n'.join(full_text)





def parse_file(file_path):
    """
    парсит файл в зависимости от его расширения

    Args:
        file_path (str): The path to the file.
    """
    if file_path.endswith('.pdf'):
        return parse_pdf(file_path)
    elif file_path.endswith('.docx'):
        return parse_docx(file_path)
    else:
        raise ValueError("Unsupported file format. Only PDF and DOCX are supported.")