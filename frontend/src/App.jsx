import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ApiError, API_PREFIX, authHeaders, friendlyError, request } from './api.js';
import AuthView from './components/AuthView.jsx';
import DocumentLibrary from './components/DocumentLibrary.jsx';
import DocumentWorkspace from './components/DocumentWorkspace.jsx';
import SiteHeader from './components/SiteHeader.jsx';
import { useConfirmation } from './components/ConfirmationDialog.jsx';
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
  const [confirmAction, confirmationDialog, cancelConfirmation] = useConfirmation();
  const [token, setToken] = useState(() => localStorage.getItem('contract_token'));
  const [user, setUser] = useState(getSavedUser);
  const [authMode, setAuthMode] = useState('login');
  const [authForm, setAuthForm] = useState({ username: '', email: '', password: '' });
  const [authLoading, setAuthLoading] = useState(false);
  const [folders, setFolders] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [totalDocuments, setTotalDocuments] = useState(0);
  const [resultTotal, setResultTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [viewStatus, setViewStatus] = useState('all');
  const [workspaceDirty, setWorkspaceDirty] = useState(false);
  const [uploadMessage, setUploadMessage] = useState('');
  const [selectedFolderId, setSelectedFolderId] = useState(null);
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [openingDocumentId, setOpeningDocumentId] = useState(null);
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortOrder, setSortOrder] = useState('desc');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryError, setLibraryError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const libraryRequestIdRef = useRef(0);
  const autoAnalyzeIdsRef = useRef(new Set());
  const activeTokenRef = useRef(token);
  const openRequestIdRef = useRef(0);
  const libraryPositionRef = useRef(null);
  const documentRevisionRef = useRef(0);
  const selectedDocumentRef = useRef(selectedDocument);
  useLayoutEffect(() => { selectedDocumentRef.current = selectedDocument; }, [selectedDocument]);
  const libraryQuery = useMemo(() => ({ page, viewStatus, selectedFolderId, debouncedSearch, sortBy, sortOrder }), [page, viewStatus, selectedFolderId, debouncedSearch, sortBy, sortOrder]);
  const libraryQueryRef = useRef(libraryQuery);
  useLayoutEffect(() => { libraryQueryRef.current = libraryQuery; }, [libraryQuery]);

  useLayoutEffect(() => {
    if (!token || selectedDocument || libraryLoading || libraryError || !libraryPositionRef.current) return undefined;
    const position = libraryPositionRef.current;
    libraryPositionRef.current = null;
    const frame = requestAnimationFrame(() => {
      window.scrollTo({ top: position.scrollY, behavior: 'instant' });
      const rows = Array.from(document.querySelectorAll('[data-document-id]'));
      const row = rows.find(item => item.dataset.documentId === String(position.documentId)) || rows.find(item => {
        const bounds = item.getBoundingClientRect();
        return bounds.bottom > 0 && bounds.top < window.innerHeight;
      });
      const target = row?.querySelector('[data-open-document]');
      const bounds = target?.getBoundingClientRect();
      if (target) target.focus({ preventScroll: bounds.bottom > 0 && bounds.top < window.innerHeight });
      else document.querySelector('.library-content')?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [selectedDocument?.id, token, libraryLoading, libraryError]);

  const resetWorkspace = useCallback(() => {
    cancelConfirmation();
    libraryRequestIdRef.current += 1;
    documentRevisionRef.current += 1;
    autoAnalyzeIdsRef.current.clear();
    openRequestIdRef.current += 1;
    libraryPositionRef.current = null;
    setOpeningDocumentId(null);
    setAuthMode('login');
    setAuthForm({ username: '', email: '', password: '' });
    setSelectedDocument(null);
    setDocuments([]);
    setFolders([]);
    setTotalDocuments(0);
    setResultTotal(0);
    setPage(1);
    setViewStatus('all');
    setWorkspaceDirty(false);
    setUploadMessage('');
    setLibraryLoading(false);
    setLibraryError('');
    setError('');
    setSelectedFolderId(null);
    setSearch('');
    setDebouncedSearch('');
    setUploading(false);
  }, [cancelConfirmation]);

  const clearSession = useCallback(() => {
    if (activeTokenRef.current !== token) return;
    activeTokenRef.current = null;
    localStorage.removeItem('contract_token');
    localStorage.removeItem('contract_user');
    setToken(null);
    setUser(null);
    resetWorkspace();
  }, [token, resetWorkspace]);

  useEffect(() => {
    const syncSession = event => {
      if (event.key === 'contract_user') {
        setUser(activeTokenRef.current ? getSavedUser() : null);
        return;
      }
      if (event.key !== 'contract_token' && event.key !== null) return;
      const savedToken = localStorage.getItem('contract_token');
      if (savedToken === activeTokenRef.current) return;
      activeTokenRef.current = savedToken;
      resetWorkspace();
      setToken(savedToken);
      setUser(savedToken ? getSavedUser() : null);
    };
    window.addEventListener('storage', syncSession);
    return () => window.removeEventListener('storage', syncSession);
  }, [resetWorkspace]);

  const logout = useCallback(async () => {
    try {
      if (token) await request('/auth/logout', { method: 'POST', body: JSON.stringify({ session_token: token }) });
    } catch {
      // The local session must still be cleared when the server is unavailable.
    }
    clearSession();
  }, [clearSession, token]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => { setDebouncedSearch(search.trim()); setPage(1); }, 280);
    return () => window.clearTimeout(timeoutId);
  }, [search]);

  const loadLibrary = useCallback(async ({ showLoading = true } = {}) => {
    if (!token || activeTokenRef.current !== token) return;
    const currentQuery = libraryQueryRef.current;
    const { page, viewStatus, selectedFolderId, debouncedSearch, sortBy, sortOrder } = currentQuery;
    const requestId = ++libraryRequestIdRef.current;
    if (showLoading) { setLibraryLoading(true); setDocuments([]); }
    try {
      const query = new URLSearchParams({ page: String(page), limit: '50', view_status: viewStatus });
      query.set('sort_by', sortBy);
      query.set('sort_order', sortOrder);
      if (selectedFolderId !== null) query.set('folder_id', String(selectedFolderId));
      if (debouncedSearch) query.set('search', debouncedSearch);
      const rootCountRequest = selectedFolderId === null && !debouncedSearch && viewStatus === 'all'
        ? null
        : request('/documents?page=1&limit=1', { headers: authHeaders(token) });
      const [folderResult, documentResult, rootCountResult] = await Promise.all([
        request('/folders', { headers: authHeaders(token) }),
        request(`/documents?${query.toString()}`, { headers: authHeaders(token) }),
        rootCountRequest,
      ]);
      if (requestId !== libraryRequestIdRef.current || currentQuery !== libraryQueryRef.current || activeTokenRef.current !== token) return;
      setFolders(folderResult.folders ?? []);
      setDocuments(documentResult.documents ?? []);
      setTotalDocuments(rootCountResult?.total ?? documentResult.total ?? 0);
      setResultTotal(documentResult.total ?? 0);
      const lastPage = Math.max(1, Math.ceil((documentResult.total ?? 0) / 50));
      if (page > lastPage) setPage(lastPage);
      setLibraryError('');
    } catch (requestError) {
      if (requestId !== libraryRequestIdRef.current || currentQuery !== libraryQueryRef.current || activeTokenRef.current !== token) return;
      if (requestError.status === 401) { clearSession(); setError(friendlyError(requestError)); }
      else setLibraryError(friendlyError(requestError));
    } finally {
      if (requestId === libraryRequestIdRef.current) setLibraryLoading(false);
    }
  }, [clearSession, token]);

  useEffect(() => { void loadLibrary(); }, [loadLibrary, libraryQuery]);

  const hasProcessingDocuments = documents.some((document) => document.status === 'processing' || document.status === 'uploaded');
  useEffect(() => {
    if (!token || (!hasProcessingDocuments && viewStatus !== 'processing' && viewStatus !== 'pending')) return undefined;
    const intervalId = window.setInterval(() => { void loadLibrary({ showLoading: false }); }, 4000);
    return () => window.clearInterval(intervalId);
  }, [hasProcessingDocuments, loadLibrary, token, viewStatus]);

  const watchedDocumentId = selectedDocument && (['processing', 'uploaded'].includes(selectedDocument.status) || selectedDocument.metadata?.risk_review?.status === 'running') ? selectedDocument.id : null;
  useEffect(() => {
    if (!token || !watchedDocumentId) return undefined;
    const controller = new AbortController();
    const intervalId = window.setInterval(async () => {
      const revision = documentRevisionRef.current;
      try {
        const updated = await request(`/documents/${watchedDocumentId}`, { headers: authHeaders(token), signal: controller.signal });
        if (activeTokenRef.current !== token || controller.signal.aborted || revision !== documentRevisionRef.current) return;
        setSelectedDocument((current) => current?.id === watchedDocumentId && (['processing', 'uploaded'].includes(current.status) || current.metadata?.risk_review?.status === 'running') ? updated : current);
      } catch (requestError) {
        if (!controller.signal.aborted && activeTokenRef.current === token && requestError.status === 401) clearSession();
      }
    }, 3000);
    return () => { window.clearInterval(intervalId); controller.abort(); };
  }, [watchedDocumentId, token, clearSession]);

  const openDocument = useCallback(async (document) => {
    const requestId = ++openRequestIdRef.current;
    if (!selectedDocument) libraryPositionRef.current = { scrollY: window.scrollY, documentId: document.id };
    setOpeningDocumentId(document.id);
    setError('');
    try {
      const fullDocument = await request(`/documents/${document.id}`, { headers: authHeaders(token) });
      if (activeTokenRef.current !== token || requestId !== openRequestIdRef.current) return false;
      setSelectedDocument(fullDocument);
      window.scrollTo({ top: 0, behavior: 'auto' });
      return true;
    } catch (requestError) {
      if (activeTokenRef.current !== token || requestId !== openRequestIdRef.current) return false;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
      return false;
    } finally {
      if (requestId === openRequestIdRef.current) setOpeningDocumentId(null);
    }
  }, [clearSession, token, selectedDocument?.id]);

  const analyzeDocument = useCallback(async (document) => {
    if (document.has_metadata && !await confirmAction({ title:'Извлечь данные заново?', description:'Текущие исправления и подтверждение будут заменены новым результатом. Оригинал документа сохранится.', confirmLabel:'Извлечь заново' })) return;
    setError('');
    const navigation = openRequestIdRef.current;
    try {
      await request(`/documents/${document.id}/analyze`, { method: 'POST', headers: authHeaders(token) });
      if (activeTokenRef.current !== token) return;
      await loadLibrary({ showLoading: false });
      if (selectedDocumentRef.current?.id === document.id && navigation === openRequestIdRef.current) await openDocument(document);
    } catch (requestError) {
      if (activeTokenRef.current !== token) return;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
    }
  }, [clearSession, loadLibrary, openDocument, selectedDocument?.id, token, confirmAction]);

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
    const revision = documentRevisionRef.current;
    request(`/documents/${selectedDocument.id}`, { headers: authHeaders(token) })
      .then((document) => { if (!cancelled && revision === documentRevisionRef.current && activeTokenRef.current === token) setSelectedDocument(document); })
      .catch((requestError) => { if (!cancelled && requestError.status === 401) clearSession(); });
    return () => { cancelled = true; };
  }, [clearSession, documents, selectedDocument, token]);

  const waitingForInsights = Boolean(selectedDocument?.has_metadata && selectedDocument.metadata?.processing?.backend !== 'rules' && !selectedDocument.metadata?.summary);
  useEffect(() => {
    if (!token || !selectedDocument?.id || !waitingForInsights) return undefined;
    const documentId = selectedDocument.id;
    const started = Date.now();
    let cancelled = false;
    const intervalId = window.setInterval(async () => {
      const revision = documentRevisionRef.current;
      if (Date.now() - started > 125_000) {
        window.clearInterval(intervalId);
        return;
      }
      try {
        const updated = await request(`/documents/${documentId}`, { headers: authHeaders(token) });
        if (!cancelled && activeTokenRef.current === token && revision === documentRevisionRef.current) setSelectedDocument((current) => current?.id === documentId ? updated : current);
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
    let failed = false;
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
      failed = true;
      setError(friendlyError(requestError));
    } finally {
      setAuthLoading(false);
      requestAnimationFrame(() => {
        const target = failed ? window.document.getElementById(authMode === 'login' ? 'auth-password' : 'auth-username') : window.document.getElementById('main-content');
        target?.focus();
      });
    }
  };

  const openOriginalFile = async (document) => {
    setError('');
    try {
      const response = await fetch(`${API_PREFIX}/documents/${document.id}/file`, { headers: authHeaders(token) });
      if (!response.ok) throw new ApiError('Не удалось открыть исходный файл', response.status);
      const blob = await response.blob();
      if (activeTokenRef.current !== token) return;
      const blobUrl = URL.createObjectURL(blob);
      const link = window.document.createElement('a');
      link.href = blobUrl;
      link.download = document.filename || 'document';
      window.document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
    } catch (requestError) {
      if (activeTokenRef.current !== token) return;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
    }
  };

  const handleUpload = async (input) => {
    const files = Array.isArray(input) ? input : input ? [input] : [];
    if (!files.length || !token) return;
    const uploadQuery = libraryQueryRef.current;
    const uploadNavigation = openRequestIdRef.current;
    setUploading(true);
    setError('');
    setUploadMessage(`Загружаем: ${files.map(file => file.name).join(', ')}`);
    try {
      const formData = new FormData();
      files.forEach((file) => formData.append('files', file));
      if (selectedFolderId !== null) formData.append('folder_id', String(selectedFolderId));
      const upload = await request('/documents/batch', { method: 'POST', headers: authHeaders(token), body: formData });
      if (activeTokenRef.current !== token) return;
      await loadLibrary({ showLoading: false });
      const accepted = upload.results.filter((item) => item.success);
      setUploadMessage(`Загружено ${accepted.length} из ${files.length}.`);
      if (libraryQueryRef.current === uploadQuery && openRequestIdRef.current === uploadNavigation) {
        setPage(1);
        setViewStatus('all');
        setSearch('');
        setDebouncedSearch('');
        if (files.length === 1 && accepted.length === 1) await openDocument({ id: accepted[0].document_id });
      }
      const rejected = upload.results.filter((item) => !item.success);
      if (rejected.length) setError(rejected.map((item) => `${item.filename}: ${item.error}`).join('; '));
    } catch (requestError) {
      if (activeTokenRef.current !== token) return;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
      setUploadMessage('');
    } finally {
      if (activeTokenRef.current === token) setUploading(false);
    }
  };

  const createFolder = async (name) => {
    try {
      const folder = await request('/folders', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ name }) });
      if (activeTokenRef.current !== token) return false;
      setSelectedFolderId(folder.id);
      setPage(1);
      setSearch('');
      setDebouncedSearch('');
      setViewStatus('all');
      setError('');
      return true;
    } catch (requestError) {
      if (activeTokenRef.current !== token) return false;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
      return false;
    }
  };

  const deleteFolder = async (folder) => {
    if (!await confirmAction({ title:`Удалить папку «${folder.name}»?`, description:'Документы останутся в общем списке.', confirmLabel:'Удалить папку', danger:true })) return;
    try {
      await request(`/folders/${folder.id}`, { method: 'DELETE', headers: authHeaders(token) });
      if (activeTokenRef.current !== token) return;
      setSelectedFolderId(current => current === folder.id ? null : current);
      await loadLibrary();
    } catch (requestError) {
      if (activeTokenRef.current !== token) return;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
    }
  };

  const moveDocument = async (documentId, folderId) => {
    try {
      await request(`/documents/${documentId}`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify({ folder_id: folderId }) });
      if (activeTokenRef.current !== token) return;
      await loadLibrary({ showLoading: false });
    } catch (requestError) {
      if (activeTokenRef.current !== token) return;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
    }
  };

  const deleteDocument = async (document) => {
    if (!await confirmAction({ title:'Удалить документ?', description:`«${document.filename}» и результат обработки будут удалены без возможности восстановления.`, confirmLabel:'Удалить документ', danger:true })) return;
    try {
      await request(`/documents/${document.id}`, { method: 'DELETE', headers: authHeaders(token) });
      if (activeTokenRef.current !== token) return;
      setSelectedDocument(current => current?.id === document.id ? null : current);
      await loadLibrary();
    } catch (requestError) {
      if (activeTokenRef.current !== token) return;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
    }
  };

  const saveDocumentMetadata = async (document, fields) => {
    setError('');
    try {
      const updated = await request(`/documents/${document.id}/metadata`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify({ fields: fieldsForSave(fields) }) });
      if (activeTokenRef.current !== token) return;
      documentRevisionRef.current += 1;
      setSelectedDocument((current) => current?.id === document.id ? updated : current);
      await loadLibrary({ showLoading: false });
    } catch (requestError) {
      if (activeTokenRef.current !== token) throw requestError;
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
      documentRevisionRef.current += 1;
      setSelectedDocument((current) => current?.id === document.id ? updated : current);
      await loadLibrary({ showLoading: false });
    } catch (requestError) {
      if (activeTokenRef.current !== token) throw requestError;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
      throw requestError;
    }
  };

  const refreshDocumentInsights = async (document) => {
    setError('');
    const revision = documentRevisionRef.current;
    try {
      const result = await request(`/documents/${document.id}/insights`, { method: 'POST', headers: authHeaders(token) });
      if (activeTokenRef.current !== token) return result;
      const updated = await request(`/documents/${document.id}`, { headers: authHeaders(token) });
      if (activeTokenRef.current !== token) return result;
      if (revision === documentRevisionRef.current) {
        documentRevisionRef.current += 1;
        setSelectedDocument((current) => current?.id === document.id ? updated : current);
      }
      return result;
    } catch (requestError) {
      if (activeTokenRef.current !== token) throw requestError;
      if (requestError.status === 401) clearSession();
      setError(friendlyError(requestError));
      throw requestError;
    }
  };

  const reviewDocumentRisks = async (document, profile) => {
    setError('');
    const pending = { status: 'running', profile };
    const revision = ++documentRevisionRef.current;
    setSelectedDocument((current) => current?.id === document.id ? { ...current, metadata: { ...current.metadata, risks: null, risk_review: pending } } : current);
    try {
      const result = await request(`/documents/${document.id}/risks`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify(profile) });
      if (activeTokenRef.current !== token) return;
      if (revision === documentRevisionRef.current) {
        documentRevisionRef.current += 1;
        setSelectedDocument((current) => current?.id === document.id ? { ...current, metadata: result.metadata } : current);
      }
      return result;
    } catch (requestError) {
      if (activeTokenRef.current === token) {
        if (requestError.status === 401) clearSession();
        else {
          // A rejected request must not erase an earlier report. A disconnected
          // request may still be running on the server, so reconcile its state.
          let actualMetadata;
          try {
            const actual = await request(`/documents/${document.id}`, { headers: authHeaders(token) });
            actualMetadata = actual.metadata;
          } catch (recoveryError) {
            if (recoveryError.status === 401) clearSession();
          }
          if (activeTokenRef.current === token && revision === documentRevisionRef.current) {
            documentRevisionRef.current += 1;
            setSelectedDocument((current) => current?.id === document.id ? { ...current, metadata: actualMetadata ?? { ...current.metadata, risks: document.metadata?.risks, risk_review: document.metadata?.risk_review } } : current);
          }
        }
      }
      throw new Error(friendlyError(requestError));
    }
  };

  const leaveWorkspace = async (action) => {
    if (workspaceDirty && !await confirmAction({title:'Есть несохранённые изменения',description:'Сохраните правку или продолжите редактирование. Если выйти сейчас, изменения этого поля потеряются.',confirmLabel:'Выйти без сохранения',cancelLabel:'Продолжить редактирование'})) return;
    setWorkspaceDirty(false);
    openRequestIdRef.current += 1;
    setOpeningDocumentId(null);
    action();
  };

  const openNextDocument = async () => {
    const result = await request('/documents?view_status=pending&limit=2', { headers: authHeaders(token) });
    if (activeTokenRef.current !== token) return false;
    const next = result.documents?.find(item => item.id !== selectedDocument?.id);
    if (!next) return false;
    if (!await openDocument(next)) throw new Error('Не удалось открыть следующий документ');
    return true;
  };

  if (!token) {
    return (
      <>
      {confirmationDialog}
      <main className="page-shell" id="top">
        <a className="skip-link" href="#main-content">Перейти к содержимому</a>
        <SiteHeader />
        <AuthView authMode={authMode} authForm={authForm} loading={authLoading} error={error} onChange={updateAuthField} onSubmit={handleAuth} onToggle={() => { setAuthMode((mode) => mode === 'login' ? 'register' : 'login'); setError(''); }} />
      </main></>
    );
  }

  return (
    <>
      {confirmationDialog}
      <main className="page-shell" id="top">
        <a className="skip-link" href="#main-content">Перейти к содержимому</a>
      <SiteHeader user={user} onHome={() => leaveWorkspace(() => setSelectedDocument(null))} onLogout={() => leaveWorkspace(logout)} />
      {selectedDocument ? (
        <DocumentWorkspace key={selectedDocument.id} document={selectedDocument} token={token} error={error} onClearError={() => setError('')} onDirtyChange={setWorkspaceDirty} onConfirm={confirmAction} onNext={openNextDocument} onBack={() => leaveWorkspace(() => { setSelectedDocument(null); setError(''); })} onOpenFile={openOriginalFile} onAnalyze={analyzeDocument} onSaveMetadata={saveDocumentMetadata} onReview={updateDocumentReview} onRefreshInsights={refreshDocumentInsights} onReviewRisks={reviewDocumentRisks} />
      ) : (
        <DocumentLibrary token={token} folders={folders} documents={documents} openingDocumentId={openingDocumentId} totalDocuments={totalDocuments} resultTotal={resultTotal} page={page} pageSize={50} onPage={setPage} viewStatus={viewStatus} onFilter={(value) => { setViewStatus(value); setPage(1); }} selectedFolderId={selectedFolderId} search={search} sortBy={sortBy} sortOrder={sortOrder} onSort={(by, order) => { setSortBy(by); setSortOrder(order); setPage(1); }} loading={libraryLoading} libraryError={libraryError} uploading={uploading} uploadMessage={uploadMessage} error={error} onDismissError={() => setError('')} onRetry={loadLibrary} onSearch={setSearch} onSelectFolder={(id) => { setSelectedFolderId(id); setPage(1); }} onUpload={handleUpload} onCreateFolder={createFolder} onDeleteFolder={deleteFolder} onMoveDocument={moveDocument} onOpen={openDocument} onOpenFile={openOriginalFile} onDelete={deleteDocument} onAnalyze={analyzeDocument} />
      )}
    </main></>
  );
}
