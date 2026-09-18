import { useEffect, useRef, useState } from 'react';
import { requestBlob } from '../api.js';

export default function DocumentPreview({ document, token }) {
  const hostRef = useRef(null);
  const [previewUrl, setPreviewUrl] = useState('');
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !document.has_file) return undefined;
    const controller = new AbortController();
    let objectUrl = '';

    const loadPreview = async () => {
      try {
        const blob = await requestBlob(`/documents/${document.id}/preview`, token, controller.signal);
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(objectUrl);
      } catch (error) {
        if (error.name !== 'AbortError') setFailed(true);
      }
    };

    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        void loadPreview();
      }
    }, { rootMargin: '160px' });
    observer.observe(host);

    return () => {
      observer.disconnect();
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [document.has_file, document.id, token]);

  return (
    <div className="document-preview" ref={hostRef} aria-hidden="true">
      {previewUrl ? <img src={previewUrl} alt="" /> : (
        <div className={`preview-placeholder${failed ? ' is-failed' : ''}`}>
          <span>{document.filename?.split('.').pop()?.toUpperCase() || 'DOC'}</span>
          <i /><i /><i /><i /><i />
        </div>
      )}
      <div className="preview-shade" />
    </div>
  );
}
