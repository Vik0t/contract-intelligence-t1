import { useCallback, useEffect, useState } from 'react';
import './App.css';

const API_PREFIX = '/api';

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(options.headers ?? {}),
    },
  });
  const contentType = response.headers.get('content-type') ?? '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof data === 'object' ? data.detail || data.message || 'Не удалось выполнить запрос' : data || 'Не удалось выполнить запрос';
    throw new ApiError(message, response.status);
  }
  return data;
}

function authHeaders(token) { return { Authorization: `Bearer ${token}` }; }

function getSavedUser() {
  try {
    const savedUser = localStorage.getItem('contract_user');
    return savedUser ? JSON.parse(savedUser) : null;
  } catch { return null; }
}

function friendlyError(error) {
  if (error?.status === 401) return 'Сессия закончилась. Войдите снова.';
  if (error?.status === 404) return 'Документ или папка не найдены.';
  if (error?.status === 409) {
    if (error.message?.includes('prepared')) return 'Документ ещё подготавливается.';
    if (error.message?.includes('running')) return 'Анализ этого документа уже выполняется.';
    return 'Папка с таким названием уже существует.';
  }
  if (error?.status >= 500) return 'Сервис временно недоступен. Попробуйте ещё раз.';
  return error?.message || 'Не удалось выполнить действие.';
}

const fieldLabels = {
  contract_number: 'Номер договора', contract_date: 'Дата договора', contract_type: 'Вид договора',
  place: 'Место заключения', term: 'Срок действия', parties: 'Стороны', total_amount: 'Общая сумма', vat: 'НДС',
};
const currencyLabels = { RUB: '₽', USD: '$', EUR: '€' };

function displayText(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет';
  if (typeof value === 'number') return new Intl.NumberFormat('ru-RU').format(value);
  return String(value);
}

function formatDate(value) {
  if (!value) return 'Дата не указана';
  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'long', year: 'numeric' }).format(new Date(value));
}

function fileExtension(filename) { return filename?.split('.').pop()?.toUpperCase() || 'FILE'; }

function renderParties(parties) {
  return <ul className="party-list">{parties.map((party, index) => <li className="party-row" key={`${party.inn ?? party.name ?? index}`}><strong>{displayText(party.name)}</strong><span>{displayText(party.role)}</span><span className="party-inn">ИНН {displayText(party.inn)}</span></li>)}</ul>;
}

function renderNestedValue(value) {
  if (Array.isArray(value)) {
    if (value.every((item) => item && typeof item === 'object' && ('name' in item || 'role' in item || 'inn' in item))) return renderParties(value);
    return <ul className="field-list">{value.map((item, index) => <li key={index}>{renderNestedValue(item)}</li>)}</ul>;
  }
  if (value && typeof value === 'object') return <dl className="field-details">{Object.entries(value).map(([key, nestedValue]) => <div className="detail-row" key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{renderNestedValue(nestedValue)}</dd></div>)}</dl>;
  return displayText(value);
}

function renderFieldValue(field) {
  const structured = field && typeof field === 'object' && !Array.isArray(field);
  const value = structured ? field.raw_value ?? field.value ?? field.name : field;
  const currency = structured ? currencyLabels[field.currency] : null;
  return <><div className="field-value">{renderNestedValue(value)}{currency && <span className="field-currency"> {currency}</span>}</div>{structured && field.evidence && <p className="field-evidence">{field.evidence}</p>}{structured && field.page_number !== undefined && field.page_number !== null && <p className="field-page">Страница {displayText(field.page_number)}</p>}</>;
}

function MetadataList({ fields }) {
  const entries = Object.entries(fields ?? {});
  if (!entries.length) return <p className="muted">Реквизиты пока не извлечены.</p>;
  return <div className="metadata-list">{entries.map(([key, value]) => <div className="metadata-row" key={key}><h3 className="metadata-key">{fieldLabels[key] ?? key}</h3><div className="metadata-content">{renderFieldValue(value)}</div></div>)}</div>;
}

function cloneFields(fields) { return JSON.parse(JSON.stringify(fields ?? {})); }
function isStructuredField(field) { return field && typeof field === 'object' && !Array.isArray(field); }
function fieldValueForEdit(key, field) {
  if (key === 'parties') return isStructuredField(field) ? field.value ?? [] : field ?? [];
  if (!isStructuredField(field)) return field ?? '';
  if (key === 'vat') return field.raw_value ?? '';
  return field.value ?? field.raw_value ?? field.name ?? '';
}
function updateFieldValue(fields, key, value) {
  const next = cloneFields(fields);
  const current = next[key];
  if (isStructuredField(current)) {
    if (key === 'vat' || (!Object.prototype.hasOwnProperty.call(current, 'value') && Object.prototype.hasOwnProperty.call(current, 'raw_value'))) current.raw_value = value;
    else current.value = value;
  } else next[key] = value;
  return next;
}

function MetadataEditor({ fields, onChange }) {
  const entries = Object.entries(fields ?? {});
  if (!entries.length) return <p className="muted">Нет полей для редактирования.</p>;
  const updateParty = (index, name, value) => {
    const next = cloneFields(fields);
    const partyField = isStructuredField(next.parties) ? next.parties : { value: next.parties ?? [] };
    const parties = Array.isArray(partyField.value) ? partyField.value : [];
    parties[index] = { ...(parties[index] ?? {}), [name]: value };
    partyField.value = parties; next.parties = partyField; onChange(next);
  };
  const addParty = () => {
    const next = cloneFields(fields);
    const partyField = isStructuredField(next.parties) ? next.parties : { value: next.parties ?? [] };
    partyField.value = [...(partyField.value ?? []), { name: '', role: '', inn: '' }]; next.parties = partyField; onChange(next);
  };
  const removeParty = (index) => {
    const next = cloneFields(fields);
    const partyField = isStructuredField(next.parties) ? next.parties : { value: next.parties ?? [] };
    partyField.value = (partyField.value ?? []).filter((_, partyIndex) => partyIndex !== index); next.parties = partyField; onChange(next);
  };
  return <div className="metadata-editor">{entries.map(([key, field]) => {
    if (key === 'parties') {
      const parties = fieldValueForEdit(key, field);
      const rows = parties.length ? parties : [{ name: '', role: '', inn: '' }];
      return <div className="editor-row" key={key}><h3 className="metadata-key">{fieldLabels[key] ?? key}</h3><div className="party-editor">{rows.map((party, index) => <div className="party-editor-row" key={index}><input value={party.name ?? ''} onChange={(event) => updateParty(index, 'name', event.target.value)} placeholder="Название стороны" /><input value={party.role ?? ''} onChange={(event) => updateParty(index, 'role', event.target.value)} placeholder="Роль" /><input value={party.inn ?? ''} onChange={(event) => updateParty(index, 'inn', event.target.value)} placeholder="ИНН" /><button className="remove-button" type="button" onClick={() => removeParty(index)} aria-label="Удалить сторону">×</button></div>)}<button className="link-button editor-add" type="button" onClick={addParty}>+ Добавить сторону</button></div></div>;
    }
    const value = fieldValueForEdit(key, field);
    const simple = typeof value !== 'object' || value === null;
    return <div className="editor-row" key={key}><label className="metadata-key" htmlFor={`metadata-${key}`}>{fieldLabels[key] ?? key}</label>{simple ? <input id={`metadata-${key}`} value={value} onChange={(event) => onChange(updateFieldValue(fields, key, event.target.value))} /> : <textarea id={`metadata-${key}`} rows={5} value={JSON.stringify(value, null, 2)} onChange={(event) => { try { onChange(updateFieldValue(fields, key, JSON.parse(event.target.value))); } catch { /* Complete JSON before saving. */ } }} />}</div>;
  })}</div>;
}

function SiteHeader({ user, onLogout }) {
  return <header className="site-header"><a className="brand" href="#top" aria-label="Т1 — анализ договоров"><span className="brand-mark">+I</span><span className="brand-name">T1</span></a>{user && <div className="header-account"><span>{user.username}</span><button className="secondary-button" type="button" onClick={onLogout}>Выйти</button></div>}</header>;
}

function AuthView({ authMode, authForm, loading, error, onChange, onSubmit, onToggle }) {
  return <section className="auth-card"><p className="eyebrow">Т1 / Анализ договоров</p><h1>{authMode === 'login' ? 'Войти' : 'Создать аккаунт'}</h1><p className="muted">Войдите, чтобы загрузить договор и сохранить историю анализа.</p><form className="form-stack" onSubmit={onSubmit}><label>Имя пользователя<input name="username" value={authForm.username} onChange={onChange} minLength={3} required /></label>{authMode === 'register' && <label>Электронная почта<input name="email" type="email" value={authForm.email} onChange={onChange} required /></label>}<label>Пароль<input name="password" type="password" value={authForm.password} onChange={onChange} minLength={6} required /></label><button className="primary-button" disabled={loading}>{loading ? 'Подождите…' : authMode === 'login' ? 'Войти' : 'Зарегистрироваться'}</button></form>{error && <p className="error">{error}</p>}<button className="link-button" type="button" onClick={onToggle}>{authMode === 'login' ? 'Создать аккаунт' : 'У меня уже есть аккаунт'}</button></section>;
}

function FolderItem({ active, label, count, onClick, onDrop, onDragOver, onDelete, canDelete }) {
  return <div className={`folder-item-wrap${active ? ' is-active' : ''}`} onDragOver={onDragOver} onDrop={onDrop}><button className="folder-item" type="button" onClick={onClick}><span className="folder-icon" aria-hidden="true">{active ? '●' : '○'}</span><span className="folder-name">{label}</span>{count !== undefined && <span className="folder-count">{count}</span>}</button>{canDelete && <button className="folder-delete" type="button" onClick={onDelete} aria-label={`Удалить папку ${label}`}>×</button>}</div>;
}

function DocumentRow({ document, selected, onOpen, onOpenFile, onDelete, onAnalyze, onDragStart }) {
  const status = document.has_metadata ? 'Данные готовы' : document.status === 'ready' ? 'Готов к анализу' : document.status === 'processing' ? 'Обрабатывается' : document.status === 'failed' ? 'Не удалось обработать' : 'Загружен';
  return <article className={`document-row${selected ? ' is-selected' : ''}`} draggable onDragStart={() => onDragStart(document.id)} onClick={() => onOpen(document)}><span className="file-type">{fileExtension(document.filename)}</span><div className="document-main"><strong>{document.filename || 'Без названия'}</strong><span>{formatDate(document.created_at)}</span></div><span className={`document-status ${document.has_metadata || document.status === 'ready' ? 'is-ready' : ''}`}>{status}</span><div className="document-actions">{(document.status === 'ready' || document.status === 'failed') && !document.has_metadata && <button type="button" onClick={(event) => { event.stopPropagation(); onAnalyze(document); }}>{document.status === 'failed' ? 'Повторить анализ' : 'Проанализировать'}</button>}{document.has_file && <button type="button" onClick={(event) => { event.stopPropagation(); onOpenFile(document); }}>Открыть файл</button>}<button type="button" onClick={(event) => { event.stopPropagation(); onDelete(document); }}>Удалить</button></div></article>;
}

function DocumentDetail({ document, onClose, onOpenFile, onAnalyze, onSaveMetadata }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draftFields, setDraftFields] = useState(() => cloneFields(document.metadata?.fields));
  useEffect(() => { setEditing(false); setDraftFields(cloneFields(document.metadata?.fields)); }, [document.id, document.metadata]);
  const hasMetadata = document.has_metadata && document.metadata?.fields;
  const canStartAnalysis = document.status === 'ready' || document.status === 'failed';
  const saveMetadata = async () => { setSaving(true); try { await onSaveMetadata(document, draftFields); setEditing(false); } finally { setSaving(false); } };
  return <section className="document-detail"><div className="detail-header"><div><p className="eyebrow">Результат анализа</p><h2>{document.filename || 'Документ'}</h2><p className="muted">Загружен {formatDate(document.created_at)}</p></div><div className="detail-actions">{document.has_file && <button className="secondary-button" type="button" onClick={() => onOpenFile(document)}>Открыть файл</button>}{hasMetadata && !editing && <button className="secondary-button" type="button" onClick={() => setEditing(true)}>Редактировать поля</button>}{editing && <><button className="secondary-button" type="button" onClick={() => { setEditing(false); setDraftFields(cloneFields(document.metadata?.fields)); }}>Отменить</button><button className="primary-button compact-button" type="button" onClick={saveMetadata} disabled={saving}>{saving ? 'Сохраняем…' : 'Сохранить поля'}</button></>}<button className="close-button" type="button" onClick={onClose}>Закрыть</button></div></div>{hasMetadata ? (editing ? <MetadataEditor fields={draftFields} onChange={setDraftFields} /> : <MetadataList fields={document.metadata.fields} />) : <div className="detail-state"><strong>{document.status === 'processing' ? 'Документ обрабатывается' : document.status === 'failed' ? 'Не удалось обработать документ' : 'Документ готов к анализу'}</strong><span>{document.processing_error || (document.status === 'processing' ? 'Можно закрыть это окно — статус обновится автоматически.' : 'Запустите анализ, чтобы извлечь реквизиты договора.')}</span>{canStartAnalysis && <button className="primary-button" type="button" onClick={() => onAnalyze(document)}>{document.status === 'failed' ? 'Повторить анализ' : 'Проанализировать документ'}</button>}</div>}</section>;
}

function App() {
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
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [showFolderForm, setShowFolderForm] = useState(false);
  const [draggedDocumentId, setDraggedDocumentId] = useState(null);
  const [error, setError] = useState('');

  const clearSession = useCallback(() => { localStorage.removeItem('contract_token'); localStorage.removeItem('contract_user'); setToken(null); setUser(null); setSelectedDocument(null); }, []);
  const logout = useCallback(async () => { try { if (token) await request('/auth/logout', { method: 'POST', body: JSON.stringify({ session_token: token }) }); } catch { /* Local session is still cleared. */ } clearSession(); }, [clearSession, token]);

  const loadLibrary = useCallback(async () => {
    if (!token) return;
    setLibraryLoading(true);
    try {
      const query = new URLSearchParams({ page: '1', limit: '100' });
      if (selectedFolderId !== null) query.set('folder_id', String(selectedFolderId));
      if (search.trim()) query.set('search', search.trim());
      const [folderResult, documentResult] = await Promise.allSettled([request('/folders', { headers: authHeaders(token) }), request(`/documents?${query.toString()}`, { headers: authHeaders(token) })]);
      if (documentResult.status === 'rejected') throw documentResult.reason;
      setDocuments(documentResult.value.documents ?? []); setTotalDocuments(documentResult.value.total ?? 0);
      if (folderResult.status === 'fulfilled') setFolders(folderResult.value.folders ?? []);
      else { setFolders([]); setError('Не удалось загрузить папки. Документы доступны в общем списке.'); }
    } catch (requestError) { if (requestError.status === 401) clearSession(); setError(friendlyError(requestError)); } finally { setLibraryLoading(false); }
  }, [clearSession, search, selectedFolderId, token]);
  useEffect(() => { loadLibrary(); }, [loadLibrary]);
  useEffect(() => { if (!token || !documents.some((document) => document.status === 'processing')) return undefined; const intervalId = window.setInterval(loadLibrary, 2500); return () => window.clearInterval(intervalId); }, [documents, loadLibrary, token]);
  useEffect(() => { if (!token || !selectedDocument) return; const summary = documents.find((document) => document.id === selectedDocument.id); if (!summary || (summary.status === selectedDocument.status && summary.has_metadata === selectedDocument.has_metadata)) return; request(`/documents/${selectedDocument.id}`, { headers: authHeaders(token) }).then(setSelectedDocument).catch((requestError) => { if (requestError.status === 401) clearSession(); }); }, [clearSession, documents, selectedDocument, token]);

  const updateAuthField = (event) => { const { name, value } = event.target; setAuthForm((current) => ({ ...current, [name]: value })); };
  const handleAuth = async (event) => { event.preventDefault(); setAuthLoading(true); setError(''); try { if (authMode === 'register') await request('/auth/register', { method: 'POST', body: JSON.stringify(authForm) }); const session = await request('/auth/login', { method: 'POST', body: JSON.stringify({ username: authForm.username, password: authForm.password }) }); localStorage.setItem('contract_token', session.session_token); localStorage.setItem('contract_user', JSON.stringify(session.user)); setToken(session.session_token); setUser(session.user); setAuthForm({ username: '', email: '', password: '' }); } catch (requestError) { setError(friendlyError(requestError)); } finally { setAuthLoading(false); } };
  const openDocument = async (document) => { setError(''); try { setSelectedDocument(await request(`/documents/${document.id}`, { headers: authHeaders(token) })); } catch (requestError) { setError(friendlyError(requestError)); } };
  const openOriginalFile = async (document) => { const preview = window.open('', '_blank'); try { const response = await fetch(`${API_PREFIX}/documents/${document.id}/file`, { headers: authHeaders(token) }); if (!response.ok) throw new ApiError('Не удалось открыть исходный файл', response.status); const blobUrl = URL.createObjectURL(await response.blob()); if (preview) preview.location.href = blobUrl; window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000); } catch (requestError) { preview?.close(); setError(friendlyError(requestError)); } };
  const analyzeDocument = async (document) => { setError(''); try { await request(`/documents/${document.id}/analyze`, { method: 'POST', headers: authHeaders(token) }); await loadLibrary(); await openDocument(document); } catch (requestError) { if (requestError.status === 401) clearSession(); setError(friendlyError(requestError)); } };
  const saveDocumentMetadata = async (document, fields) => { try { setSelectedDocument(await request(`/documents/${document.id}/metadata`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify({ fields }) })); await loadLibrary(); } catch (requestError) { if (requestError.status === 401) clearSession(); setError(friendlyError(requestError)); throw requestError; } };
  const handleUpload = async (event) => { const nextFile = event.target.files?.[0]; event.target.value = ''; if (!nextFile || !token) return; setUploading(true); setError(''); try { const formData = new FormData(); formData.append('file', nextFile); if (selectedFolderId !== null) formData.append('folder_id', String(selectedFolderId)); const upload = await request('/documents', { method: 'POST', headers: authHeaders(token), body: formData }); await loadLibrary(); await openDocument({ id: upload.document_id }); } catch (requestError) { if (requestError.status === 401) clearSession(); setError(friendlyError(requestError)); } finally { setUploading(false); } };
  const createFolder = async (event) => { event.preventDefault(); if (!folderName.trim()) return; try { const folder = await request('/folders', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ name: folderName.trim() }) }); setFolderName(''); setShowFolderForm(false); setSelectedFolderId(folder.id); await loadLibrary(); } catch (requestError) { setError(friendlyError(requestError)); } };
  const deleteFolder = async (folder) => { if (!window.confirm(`Удалить папку «${folder.name}»? Документы останутся в общем списке.`)) return; try { await request(`/folders/${folder.id}`, { method: 'DELETE', headers: authHeaders(token) }); if (selectedFolderId === folder.id) setSelectedFolderId(null); await loadLibrary(); } catch (requestError) { setError(friendlyError(requestError)); } };
  const moveDocument = async (documentId, folderId) => { setDraggedDocumentId(null); try { await request(`/documents/${documentId}`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify({ folder_id: folderId }) }); await loadLibrary(); } catch (requestError) { setError(friendlyError(requestError)); } };
  const deleteDocument = async (document) => { if (!window.confirm(`Удалить «${document.filename}»?`)) return; try { await request(`/documents/${document.id}`, { method: 'DELETE', headers: authHeaders(token) }); if (selectedDocument?.id === document.id) setSelectedDocument(null); await loadLibrary(); } catch (requestError) { setError(friendlyError(requestError)); } };

  if (!token) return <main className="page-shell" id="top"><SiteHeader /><AuthView authMode={authMode} authForm={authForm} loading={authLoading} error={error} onChange={updateAuthField} onSubmit={handleAuth} onToggle={() => { setAuthMode((mode) => mode === 'login' ? 'register' : 'login'); setError(''); }} /></main>;
  const selectedFolder = folders.find((folder) => folder.id === selectedFolderId);
  return <main className="page-shell" id="top"><SiteHeader user={user} onLogout={logout} /><section className="product-shell"><header className="product-heading"><div><p className="eyebrow">Т1 / Анализ договоров</p><h1>Мои документы</h1><p className="muted">Храните договоры, раскладывайте их по папкам и возвращайтесь к результатам анализа.</p></div><label className="primary-button upload-trigger">{uploading ? 'Подготавливаем…' : 'Загрузить договор'}<input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={handleUpload} disabled={uploading} /></label></header>{error && <p className="error">{error}</p>}<div className="library-layout"><aside className="folder-sidebar"><div className="sidebar-heading"><h2>Папки</h2><button className="add-folder-button" type="button" onClick={() => setShowFolderForm((current) => !current)} aria-label="Создать папку">+</button></div><FolderItem active={selectedFolderId === null} label="Все документы" count={totalDocuments} onClick={() => setSelectedFolderId(null)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (draggedDocumentId) moveDocument(draggedDocumentId, null); }} /><div className="folder-list">{folders.map((folder) => <FolderItem key={folder.id} active={selectedFolderId === folder.id} label={folder.name} count={folder.document_count} onClick={() => setSelectedFolderId(folder.id)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (draggedDocumentId) moveDocument(draggedDocumentId, folder.id); }} onDelete={() => deleteFolder(folder)} canDelete />)}</div>{showFolderForm && <form className="folder-form" onSubmit={createFolder}><input autoFocus value={folderName} onChange={(event) => setFolderName(event.target.value)} placeholder="Название папки" maxLength={120} /><button className="primary-button" type="submit">Создать</button></form>}<p className="drop-hint">Перетащите документ на папку, чтобы переместить его.</p></aside><section className="library-content"><div className="list-heading"><div><h2>{selectedFolder?.name ?? 'Все документы'}</h2><span className="list-count">{totalDocuments} документов</span></div><input className="search-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Найти документ" aria-label="Найти документ" /></div>{libraryLoading ? <div className="empty-state">Загружаем документы…</div> : documents.length ? <div className="document-list"><div className="document-list-head"><span>Документ</span><span>Статус</span><span>Действия</span></div>{documents.map((document) => <DocumentRow key={document.id} document={document} selected={selectedDocument?.id === document.id} onOpen={openDocument} onOpenFile={openOriginalFile} onDelete={deleteDocument} onAnalyze={analyzeDocument} onDragStart={setDraggedDocumentId} />)}</div> : <div className="empty-state"><strong>{search ? 'Ничего не найдено' : 'В этой папке пока нет документов'}</strong><span>{search ? 'Попробуйте изменить запрос.' : 'Загрузите первый договор, и он появится здесь.'}</span></div>}{selectedDocument && <DocumentDetail document={selectedDocument} onClose={() => setSelectedDocument(null)} onOpenFile={openOriginalFile} onAnalyze={analyzeDocument} onSaveMetadata={saveDocumentMetadata} />}</section></div></section></main>;
}

export default App;
