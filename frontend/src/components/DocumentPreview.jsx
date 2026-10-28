import { useEffect, useRef, useState } from 'react';
import { requestBlob } from '../api.js';

export default function DocumentPreview({ document, token }) {
  const hostRef = useRef(null);
  const [previewUrl, setPreviewUrl] = useState('');
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    setPreviewUrl('');
    setFailed(false);
    if (!host || !document.has_file) return undefined;
    const controller = new AbortController();
    let objectUrl = '';

    const loadPreview = async () => {
      try {
        const blob = await requestBlob(`/documents/${document.id}/preview`, token, controller.signal, 'no-cache');
        if (!blob.type.startsWith('image/png')) throw new Error('Original preview unavailable');
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(objectUrl);
      } catch (error) {
        if (!controller.signal.aborted && error.name !== 'AbortError') setFailed(true);
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
  }, [document.has_file, document.id, document.filename, token]);

  return (
    <div className="document-preview" ref={hostRef} aria-hidden="true">
      {previewUrl ? <img src={previewUrl} alt="" onError={() => { setPreviewUrl(''); setFailed(true); }} /> : (
        <div className="preview-placeholder"><span>{!document.has_file ? 'Файл недоступен' : failed ? 'Превью недоступно' : 'Готовим превью…'}</span></div>
      )}
    </div>
  );
}
