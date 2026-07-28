// src/App.jsx
import React, { useState } from 'react';
import './App.css';

function App() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    setFile(selectedFile);
    setResult(null);
    setError(null);
  };

  const handleUpload = async () => {
    if (!file) {
      alert('Please select a file');
      return;
    }

    setLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('http://localhost:8000/upload-contract', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.error || 'Upload failed');
      }

      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <h1>Contract Upload</h1>
      
      <div className="upload-box">
        <input
          type="file"
          id="fileInput"
          accept=".docx,.pdf"
          onChange={handleFileChange}
        />
        <label htmlFor="fileInput" className="file-label">
          {file ? file.name : 'Choose file (DOCX, PDF)'}
        </label>
        
        <button 
          onClick={handleUpload} 
          disabled={!file || loading}
          className="upload-btn"
        >
          {loading ? 'Processing...' : 'Upload & Parse'}
        </button>
      </div>

      {error && (
        <div className="error">
          Error: {error}
        </div>
      )}

      {result && result.success && (
        <div className="result">
          <h2>Extracted Metadata</h2>
          <div className="metadata">
            <div className="meta-row">
              <span className="label">Number:</span>
              <span className="value">{result.metadata.meta.number}</span>
            </div>
            <div className="meta-row">
              <span className="label">Date:</span>
              <span className="value">{result.metadata.meta.date}</span>
            </div>
            <div className="meta-row">
              <span className="label">Party 1:</span>
              <span className="value">{result.metadata.meta.party1}</span>
            </div>
            <div className="meta-row">
              <span className="label">Party 2:</span>
              <span className="value">{result.metadata.meta.party2}</span>
            </div>
            <div className="meta-row">
              <span className="label">Amount:</span>
              <span className="value">{result.metadata.meta.amount} ₽</span>
            </div>
            <div className="meta-row">
              <span className="label">Contract Type:</span>
              <span className="value">{result.metadata.meta.contract_type}</span>
            </div>
            <div className="meta-row">
              <span className="label">Term:</span>
              <span className="value">{result.metadata.meta.term}</span>
            </div>
            <div className="meta-row">
              <span className="label">Place:</span>
              <span className="value">{result.metadata.meta.place}</span>
            </div>
            <div className="meta-row">
              <span className="label">VAT:</span>
              <span className="value">{result.metadata.meta.vat}</span>
            </div>
            <div className="meta-row">
              <span className="label">INN 1:</span>
              <span className="value">{result.metadata.meta.inn1}</span>
            </div>
            <div className="meta-row">
              <span className="label">INN 2:</span>
              <span className="value">{result.metadata.meta.inn2}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;