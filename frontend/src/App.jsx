import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, API_PREFIX, authHeaders, friendlyError, request } from './api.js';
import AuthView from './components/AuthView.jsx';
import DocumentLibrary from './components/DocumentLibrary.jsx';
import DocumentWorkspace from './components/DocumentWorkspace.jsx';
import SiteHeader from './components/SiteHeader.jsx';
import { fieldsForSave } from './contractFields.js';
import './App.css';

function getSavedUser() {
  try {
    const savedUser = localStorage.getItem('contract_user');
    return savedUser ? JSON.parse(savedUser) : null;
  } catch {
    return null;
  }
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem('contract_token'));
  const [user, setUser] = useState(getSavedUser);
  const [authMode, setAuthMode] = useState('login');
  const [authForm, setAuthForm] = useState({ username: '', email: '', password: '' });
  const [authLoading, setAuthLoading] = useState(false);
  const [folders, setFolders] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [totalDocuments, setTotalDocuments] = useState(0);
  const [selectedFolderId, setSelectedFolderId] = useState(null);
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const libraryRequestIdRef = useRef(0);
  const autoAnalyzeIdsRef = useRef(new Set());
  const activeTokenRef = useRef(token);

  const clearSession = useCallback(() => {
    if (activeTokenRef.current !== token) return;
    activeTokenRef.current = null;
    libraryRequestIdRef.current += 1;
    autoAnalyzeIdsRef.current.clear();
    localStorage.removeItem('contract_token');
    localStorage.removeItem('contract_user');
    setToken(null);
    setUser(null);
    setSelectedDocument(null);
    setDocuments([]);
    setFolders([]);
    setTotalDocuments(0);
    setSelectedFolderId(null);
    setSearch('');
    setDebouncedSearch('');
    setUploading(false);
  }, [token]);

  const logout = useCallback(async () => {
    try {
      if (token) await request('/auth/logout', { method: 'POST', body: JSON.stringify({ session_token: token }) });
    } catch {
      // The local session must still be cleared when the server is unavailable.
    }
    clearSession();
  }, [clearSession, token]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => setDebouncedSearch(search.trim()), 280);
    return () => window.clearTimeout(timeoutId);
  }, [search]);

  const loadLibrary = useCallback(async ({ showLoading = true } = {}) => {
    if (!token || activeTokenRef.current !== token) return;
    const requestId = ++libraryRequestIdRef.current;
    if (showLoading) setLibraryLoading(true);
    try {
      const query = new URLSearchParams({ page: '1', limit: '100' });
      if (selectedFolderId !== null) query.set('folder_id', String(selectedFolderId));
      if (debouncedSearch) query.set('search', debouncedSearch);
      const rootCountRequest = selectedFolderId === null && !debouncedSearch
        ? null
        : request('/documents?page=1&limit=1', { headers: authHeaders(token) });
      const [folderResult, documentResult, rootCountResult] = await Promise.all([
        request('/folders', { headers: authHeaders(token) }),
        request(`/documents?${query.toString()}`, { headers: authHeaders(token) }),
        rootCountRequest,
      ]);
      if (requestId !== libraryRequestIdRef.current) return;
      setFolders(folderResult.folders ?? []);
      setDocuments(documentResult.documents ?? []);
      setTotalDocuments(rootCountResult?.total ?? documentResult.total ?? 0);
      setError('');
    } catch (requestError) {
      if (requestId !== libraryRequestIdRef.current) return;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
    } finally {
      if (showLoading && requestId === libraryRequestIdRef.current) setLibraryLoading(false);
    }
  }, [clearSession, debouncedSearch, selectedFolderId, token]);

  useEffect(() => { void loadLibrary(); }, [loadLibrary]);

  const hasProcessingDocuments = documents.some((document) => document.status === 'processing');
  useEffect(() => {
    if (!token || !hasProcessingDocuments) return undefined;
    const intervalId = window.setInterval(() => { void loadLibrary({ showLoading: false }); }, 4000);
    return () => window.clearInterval(intervalId);
  }, [hasProcessingDocuments, loadLibrary, token]);

  const openDocument = useCallback(async (document) => {
    setError('');
    try {
      const fullDocument = await request(`/documents/${document.id}`, { headers: authHeaders(token) });
      if (activeTokenRef.current !== token) return;
      setSelectedDocument(fullDocument);
      window.scrollTo({ top: 0, behavior: 'auto' });
    } catch (requestError) {
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
    }
  }, [clearSession, token]);

  const analyzeDocument = useCallback(async (document) => {
    setError('');
    try {
      await request(`/documents/${document.id}/analyze`, { method: 'POST', headers: authHeaders(token) });
      if (activeTokenRef.current !== token) return;
      await loadLibrary({ showLoading: false });
      if (selectedDocument?.id === document.id) await openDocument(document);
    } catch (requestError) {
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
    }
  }, [clearSession, loadLibrary, openDocument, selectedDocument?.id, token]);

  useEffect(() => {
    for (const document of documents) {
      if (document.status !== 'ready' || document.has_metadata || !autoAnalyzeIdsRef.current.has(document.id)) continue;
      autoAnalyzeIdsRef.current.delete(document.id);
      void analyzeDocument(document);
    }
  }, [analyzeDocument, documents]);

  useEffect(() => {
    if (!token || !selectedDocument) return undefined;
    const summary = documents.find((document) => document.id === selectedDocument.id);
    if (!summary || (
      summary.status === selectedDocument.status
      && summary.has_metadata === selectedDocument.has_metadata
      && summary.review_status === selectedDocument.review_status
    )) return undefined;
    let cancelled = false;
    request(`/documents/${selectedDocument.id}`, { headers: authHeaders(token) })
      .then((document) => { if (!cancelled) setSelectedDocument(document); })
      .catch((requestError) => { if (!cancelled && requestError.status === 401) clearSession(); });
    return () => { cancelled = true; };
  }, [clearSession, documents, selectedDocument, token]);

  const waitingForInsights = Boolean(selectedDocument?.has_metadata && (!selectedDocument.metadata?.summary || !Array.isArray(selectedDocument.metadata?.risks)));
  useEffect(() => {
    if (!token || !selectedDocument?.id || !waitingForInsights) return undefined;
    const documentId = selectedDocument.id;
    const started = Date.now();
    let cancelled = false;
    const intervalId = window.setInterval(async () => {
      if (Date.now() - started > 125_000) {
        window.clearInterval(intervalId);
        return;
      }
      try {
        const updated = await request(`/documents/${documentId}`, { headers: authHeaders(token) });
        if (!cancelled) setSelectedDocument((current) => current?.id === documentId ? updated : current);
      } catch (requestError) {
        if (!cancelled && requestError.status === 401) clearSession();
      }
    }, 5000);
    return () => { cancelled = true; window.clearInterval(intervalId); };
  }, [clearSession, selectedDocument?.id, token, waitingForInsights]);

  const updateAuthField = (event) => {
    const { name, value } = event.target;
    setAuthForm((current) => ({ ...current, [name]: value }));
  };

  const handleAuth = async (event) => {
    event.preventDefault();
    setAuthLoading(true);
    setError('');
    try {
      if (authMode === 'register') await request('/auth/register', { method: 'POST', body: JSON.stringify(authForm) });
      const session = await request('/auth/login', { method: 'POST', body: JSON.stringify({ username: authForm.username, password: authForm.password }) });
      localStorage.setItem('contract_token', session.session_token);
      localStorage.setItem('contract_user', JSON.stringify(session.user));
      activeTokenRef.current = session.session_token;
      setToken(session.session_token);
      setUser(session.user);
      setAuthForm({ username: '', email: '', password: '' });
    } catch (requestError) {
      setError(friendlyError(requestError));
    } finally {
      setAuthLoading(false);
    }
  };

  const openOriginalFile = async (document) => {
    const preview = window.open('', '_blank');
    try {
      const response = await fetch(`${API_PREFIX}/documents/${document.id}/file`, { headers: authHeaders(token) });
      if (!response.ok) throw new ApiError('Не удалось открыть исходный файл', response.status);
      const blobUrl = URL.createObjectURL(await response.blob());
      if (preview) preview.location.href = blobUrl;
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
    } catch (requestError) {
      preview?.close();
      setError(friendlyError(requestError));
    }
  };

  const handleUpload = async (file) => {
    if (!file || !token) return;
    const extension = file.name.split('.').pop()?.toLowerCase();
    if (!['pdf', 'docx', 'jpg', 'jpeg', 'png'].includes(extension)) {
      setError('Поддерживаются файлы PDF, DOCX, JPG и PNG.');
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      setError('Файл больше 50 МБ. Выберите документ меньшего размера.');
      return;
    }
    setUploading(true);
    setError('');
    try {
      const formData = new FormData();
      formData.append('file', file);
      if (selectedFolderId !== null) formData.append('folder_id', String(selectedFolderId));
      const upload = await request('/documents', { method: 'POST', headers: authHeaders(token), body: formData });
      if (activeTokenRef.current !== token) return;
      autoAnalyzeIdsRef.current.add(upload.document_id);
      await loadLibrary({ showLoading: false });
      await openDocument({ id: upload.document_id });
    } catch (requestError) {
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
    } finally {
      if (activeTokenRef.current === token) setUploading(false);
    }
  };

  const createFolder = async (name) => {
    try {
      const folder = await request('/folders', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ name }) });
      setSelectedFolderId(folder.id);
      return true;
    } catch (requestError) {
      setError(friendlyError(requestError));
      return false;
    }
  };

  const deleteFolder = async (folder) => {
    if (!window.confirm(`Удалить папку «${folder.name}»? Документы останутся в общем списке.`)) return;
    try {
      await request(`/folders/${folder.id}`, { method: 'DELETE', headers: authHeaders(token) });
      if (selectedFolderId === folder.id) setSelectedFolderId(null);
      await loadLibrary();
    } catch (requestError) {
      setError(friendlyError(requestError));
    }
  };

  const moveDocument = async (documentId, folderId) => {
    try {
      await request(`/documents/${documentId}`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify({ folder_id: folderId }) });
      await loadLibrary({ showLoading: false });
    } catch (requestError) {
      setError(friendlyError(requestError));
    }
  };

  const deleteDocument = async (document) => {
    if (!window.confirm(`Удалить «${document.filename}»? Восстановить документ не получится.`)) return;
    try {
      await request(`/documents/${document.id}`, { method: 'DELETE', headers: authHeaders(token) });
      if (selectedDocument?.id === document.id) setSelectedDocument(null);
      await loadLibrary();
    } catch (requestError) {
      setError(friendlyError(requestError));
    }
  };

  const saveDocumentMetadata = async (document, fields) => {
    try {
      const updated = await request(`/documents/${document.id}/metadata`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify({ fields: fieldsForSave(fields) }) });
      if (activeTokenRef.current !== token) return;
      setSelectedDocument((current) => current?.id === document.id ? updated : current);
      await loadLibrary({ showLoading: false });
    } catch (requestError) {
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
      throw requestError;
    }
  };

  const updateDocumentReview = async (document, confirmed) => {
    try {
      const updated = await request(`/documents/${document.id}/review`, {
        method: 'PATCH',
        headers: authHeaders(token),
        body: JSON.stringify({ confirmed }),
      });
      if (activeTokenRef.current !== token) return;
      setSelectedDocument((current) => current?.id === document.id ? updated : current);
      await loadLibrary({ showLoading: false });
    } catch (requestError) {
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
      throw requestError;
    }
  };

  const refreshDocumentInsights = async (document) => {
    setError('');
    try {
      const result = await request(`/documents/${document.id}/insights`, { method: 'POST', headers: authHeaders(token) });
      if (activeTokenRef.current !== token) return result;
      const updated = await request(`/documents/${document.id}`, { headers: authHeaders(token) });
      setSelectedDocument((current) => current?.id === document.id ? updated : current);
      return result;
    } catch (requestError) {
      if (activeTokenRef.current !== token) throw requestError;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
      throw requestError;
    }
  };

  if (!token) {
    return (
      <main className="page-shell" id="top">
        <SiteHeader />
        <AuthView authMode={authMode} authForm={authForm} loading={authLoading} error={error} onChange={updateAuthField} onSubmit={handleAuth} onToggle={() => { setAuthMode((mode) => mode === 'login' ? 'register' : 'login'); setError(''); }} />
      </main>
    );
  }

  return (
    <main className="page-shell" id="top">
      <SiteHeader user={user} onHome={() => setSelectedDocument(null)} onLogout={logout} />
      {selectedDocument ? (
        <DocumentWorkspace document={selectedDocument} token={token} error={error} onBack={() => { setSelectedDocument(null); setError(''); }} onOpenFile={openOriginalFile} onAnalyze={analyzeDocument} onSaveMetadata={saveDocumentMetadata} onReview={updateDocumentReview} onRefreshInsights={refreshDocumentInsights} />
      ) : (
        <DocumentLibrary token={token} folders={folders} documents={documents} totalDocuments={totalDocuments} selectedFolderId={selectedFolderId} selectedDocumentId={selectedDocument?.id} search={search} loading={libraryLoading} uploading={uploading} error={error} onSearch={setSearch} onSelectFolder={setSelectedFolderId} onUpload={handleUpload} onCreateFolder={createFolder} onDeleteFolder={deleteFolder} onMoveDocument={moveDocument} onOpen={openDocument} onOpenFile={openOriginalFile} onDelete={deleteDocument} onAnalyze={analyzeDocument} />
      )}
    </main>
  );
}
