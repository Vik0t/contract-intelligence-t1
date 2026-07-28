# app.py
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import tempfile
import os
from ..src.parsing import parse_file
from ..src.llm import extract_contract_key_data

app = FastAPI()

@app.post("/upload-contract")
async def upload_contract(file: UploadFile = File(...)):
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        # Parse and extract metadata
        text = parse_file(tmp_path)
        metadata = extract_contract_key_data(text)
        
        # Clean up temp file
        os.unlink(tmp_path)
        
        return JSONResponse({
            "success": True,
            "metadata": metadata,
            "filename": file.filename
        })
        
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)

@app.get("/")
async def root():
    return {"message": "Contract Upload API"}