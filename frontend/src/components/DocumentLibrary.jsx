import { useRef, useState } from 'react';
import { fileExtension, formatDate } from '../contractFields.js';
import DocumentPreview from './DocumentPreview.jsx';

function documentStatus(document) {
  if (document.has_metadata) return { label: 'Данные готовы', tone: 'ready' };
  if (document.status === 'processing') return { label: 'Анализируем документ…', tone: 'processing' };
  if (document.status === 'failed') return { label: 'Требует внимания', tone: 'attention' };
  return { label: 'Готов к анализу', tone: 'neutral' };
}

function FolderItem({ active, label, count, onClick, onDrop, onDelete }) {
  return (
    <div className={`folder-item-wrap${active ? ' is-active' : ''}`} onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
      <button className="folder-item" type="button" onClick={onClick}>
        <span>{label}</span><span className="folder-count">{count}</span>
      </button>
      {onDelete ? <button className="folder-delete" type="button" onClick={onDelete} aria-label={`Удалить папку ${label}`}>×</button> : null}
    </div>
  );
}

function DocumentCard({ document, token, selected, onOpen, onOpenFile, onDelete, onAnalyze, onDragStart }) {
  const status = documentStatus(document);
  return (
    <article className={`document-card${selected ? ' is-selected' : ''}`} draggable onDragStart={() => onDragStart(document.id)}>
      <button className="document-card-main" type="button" onClick={() => onOpen(document)}>
        <DocumentPreview document={document} token={token} />
        <span className="document-card-body">
          <span className="document-card-type">{fileExtension(document.filename)}</span>
          <strong>{document.filename || 'Без названия'}</strong>
          <span className={`document-card-status is-${status.tone}`}><i aria-hidden="true" />{status.label}</span>
          <span className="document-card-date">Добавлен {formatDate(document.created_at)}</span>
        </span>
      </button>
      <div className="document-card-actions">
        {(document.status === 'ready' || document.status === 'failed') && !document.has_metadata ? (
          <button type="button" onClick={() => onAnalyze(document)}>{document.status === 'failed' ? 'Повторить' : 'Начать анализ'}</button>
        ) : <button type="button" onClick={() => onOpen(document)}>Открыть</button>}
        {document.has_file ? <button type="button" onClick={() => onOpenFile(document)}>Оригинал</button> : null}
        <button className="danger-link" type="button" onClick={() => onDelete(document)}>Удалить</button>
      </div>
    </article>
  );
}

export default function DocumentLibrary({
  token,
  folders,
  documents,
  totalDocuments,
  selectedFolderId,
  selectedDocumentId,
  search,
  loading,
  uploading,
  error,
  onSearch,
  onSelectFolder,
  onUpload,
  onCreateFolder,
  onDeleteFolder,
  onMoveDocument,
  onOpen,
  onOpenFile,
  onDelete,
  onAnalyze,
}) {
  const inputRef = useRef(null);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [showFolderForm, setShowFolderForm] = useState(false);
  const [draggedDocumentId, setDraggedDocumentId] = useState(null);
  const selectedFolder = folders.find((folder) => folder.id === selectedFolderId);

  const submitFolder = async (event) => {
    event.preventDefault();
    if (!folderName.trim()) return;
    const created = await onCreateFolder(folderName.trim());
    if (created) {
      setFolderName('');
      setShowFolderForm(false);
    }
  };

  const acceptFile = (file) => {
    setIsDraggingFile(false);
    if (file) onUpload(file);
  };

  return (
    <section className="product-shell">
      <header className="product-heading">
        <div>
          <p className="eyebrow">Рабочая библиотека</p>
          <h1>Договоры</h1>
          <p className="muted">Загружайте, проверяйте и возвращайтесь к готовым данным.</p>
        </div>
        <button className="primary-button" type="button" onClick={() => inputRef.current?.click()} disabled={uploading}>
          {uploading ? 'Загружаем…' : '+ Загрузить договор'}
        </button>
        <input ref={inputRef} className="visually-hidden" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => { acceptFile(event.target.files?.[0]); event.target.value = ''; }} />
      </header>

      <div
        className={`upload-strip${isDraggingFile ? ' is-dragging' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); setIsDraggingFile(true); }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setIsDraggingFile(false); }}
        onDrop={(event) => { event.preventDefault(); acceptFile(event.dataTransfer.files?.[0]); }}
      >
        <strong>{isDraggingFile ? 'Отпустите файл, чтобы загрузить' : 'Можно перетащить договор сюда'}</strong>
        <span>PDF или DOCX · до 50 МБ · PDF до 200 страниц</span>
      </div>
      {error ? <p className="error" role="alert">{error}</p> : null}

      <div className="library-layout">
        <aside className="folder-sidebar" aria-label="Папки документов">
          <div className="sidebar-heading">
            <h2>Папки</h2>
            <button className="icon-button" type="button" onClick={() => setShowFolderForm((value) => !value)} aria-label="Создать папку">+</button>
          </div>
          <div className="folder-list">
            <FolderItem active={selectedFolderId === null} label="Все документы" count={totalDocuments} onClick={() => onSelectFolder(null)} onDrop={(event) => { event.preventDefault(); if (draggedDocumentId) onMoveDocument(draggedDocumentId, null); }} />
            {folders.map((folder) => (
              <FolderItem key={folder.id} active={selectedFolderId === folder.id} label={folder.name} count={folder.document_count} onClick={() => onSelectFolder(folder.id)} onDrop={(event) => { event.preventDefault(); if (draggedDocumentId) onMoveDocument(draggedDocumentId, folder.id); }} onDelete={() => onDeleteFolder(folder)} />
            ))}
          </div>
          {showFolderForm ? (
            <form className="folder-form" onSubmit={submitFolder}>
              <label htmlFor="folder-name">Новая папка</label>
              <input id="folder-name" autoFocus value={folderName} onChange={(event) => setFolderName(event.target.value)} placeholder="Например, Поставки" maxLength={120} />
              <div><button className="small-button" type="submit">Создать</button><button className="text-button" type="button" onClick={() => setShowFolderForm(false)}>Отмена</button></div>
            </form>
          ) : null}
          <p className="drop-hint">На компьютере договор можно перетащить на нужную папку.</p>
        </aside>

        <section className="library-content">
          <div className="list-heading">
            <div><h2>{selectedFolder?.name ?? 'Все документы'}</h2><span className="list-count">{documents.length} из {totalDocuments}</span></div>
            <label className="search-box"><span className="visually-hidden">Найти документ</span><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Название или номер договора" /></label>
          </div>
          {loading ? <div className="empty-state">Загружаем документы…</div> : documents.length ? (
            <div className="documents-grid">
              {documents.map((document) => (
                <DocumentCard key={document.id} document={document} token={token} selected={selectedDocumentId === document.id} onOpen={onOpen} onOpenFile={onOpenFile} onDelete={onDelete} onAnalyze={onAnalyze} onDragStart={setDraggedDocumentId} />
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <strong>{search ? 'Ничего не найдено' : 'Здесь пока нет договоров'}</strong>
              <span>{search ? 'Измените поисковый запрос.' : 'Загрузите первый документ — анализ начнётся автоматически.'}</span>
              {!search ? <button className="primary-button" type="button" onClick={() => inputRef.current?.click()}>Загрузить договор</button> : null}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
