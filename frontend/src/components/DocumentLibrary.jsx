import { useEffect, useId, useRef, useState } from 'react';
import { fileExtension, formatDate, formatFieldValue, getFieldValue, fieldNeedsReview } from '../contractFields.js';
import { DOCUMENT_FILTERS, documentStatus } from '../documentLibrary.js';
import DocumentPreview from './DocumentPreview.jsx';
import ActionMenu from './ActionMenu.jsx';

function Status({ document }) {
  const status = documentStatus(document);
  return <span className={`document-card-status is-${status.tone}`}><i aria-hidden="true" />{status.label}</span>;
}

function DocumentActions({ document, onOpenFile, onDelete, onAnalyze, onMove, folders }) {
  return <ActionMenu label={`Действия с документом ${document.filename}`}>
      {document.has_file ? <button type="button" onClick={() => onOpenFile(document)}>Скачать оригинал</button> : null}
      {document.status !== 'processing' ? <button type="button" onClick={() => {
        onAnalyze(document);
      }}>{document.has_metadata ? 'Извлечь заново…' : document.status === 'failed' ? 'Повторить обработку' : 'Извлечь данные'}</button> : null}
      {folders.length ? <label className="move-document">Переместить в папку<select aria-label={`Папка документа ${document.filename}`} value={document.folder_id ?? ''} onChange={(event) => onMove(document.id, event.target.value ? Number(event.target.value) : null)}><option value="">Без папки</option>{folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label> : null}
      <button className="danger-link" type="button" onClick={() => onDelete(document)}>Удалить…</button>
  </ActionMenu>;
}

function RegistryValue({ fieldKey, field, children, ready, reviewed }) {
  const review = ready && !reviewed && fieldNeedsReview(fieldKey, field);
  return <td className={review ? 'registry-review' : ''}>
    {ready ? children ?? formatFieldValue(fieldKey, field) : <span className="missing-value">—</span>}
    {review ? <span className="registry-hint">Стоит проверить</span> : null}
  </td>;
}

function Parties({ fields }) {
  const parties = getFieldValue('parties', fields.parties);
  return parties?.length ? <div className="registry-parties">{parties.map((party, index) => <div key={index}>
    <span>{party.name || 'Название не найдено'}</span><small>{party.role || 'Роль не определена'}</small>
  </div>)}</div> : <span className="missing-value">Не найдены</span>;
}

function RegistryRow({ document, opening, onOpen, onDragStart, ...actions }) {
  const fields = document.fields ?? {};
  return <tr data-document-id={document.id} draggable onDragStart={() => onDragStart(document.id)}>
    <td className="registry-document"><button data-open-document className="registry-file" type="button" disabled={opening} aria-busy={opening} onClick={() => onOpen(document)}>{document.filename || 'Без названия'}</button>
      <span className="registry-hint">{fileExtension(document.filename)} · {formatDate(document.created_at)}</span>
    </td>
    <td>{document.has_metadata ? <><span className="registry-number">{formatFieldValue('contract_number', fields.contract_number)}</span><span className="registry-hint">{formatFieldValue('contract_date', fields.contract_date)}</span></> : <span className="missing-value">—</span>}</td>
    <td>{document.has_metadata ? <Parties fields={fields} /> : <span className="missing-value">—</span>}</td>
    <RegistryValue fieldKey="total_amount" field={fields.total_amount} ready={document.has_metadata} reviewed={document.review_status === 'reviewed'} />
    <td><Status document={document} /></td>
    <td className="registry-actions"><button className="open-document" type="button" disabled={opening} onClick={() => onOpen(document)} aria-label={`Открыть ${document.filename}`}>{opening ? 'Открываем…' : 'Открыть'}</button><DocumentActions document={document} {...actions} /></td>
  </tr>;
}

function DocumentCard({ document, token, opening, onOpen, onDragStart, ...actions }) {
  const fields = document.fields ?? {};
  const parties = getFieldValue('parties', fields.parties) ?? [];
  const number = getFieldValue('contract_number', fields.contract_number);
  const amount = getFieldValue('total_amount', fields.total_amount);
  return <article data-document-id={document.id} className="document-card" draggable onDragStart={() => onDragStart(document.id)}>
    <button data-open-document className="document-card-main" type="button" disabled={opening} aria-busy={opening} onClick={() => onOpen(document)} aria-label={`Открыть ${document.filename}`}>
      <DocumentPreview document={document} token={token} />
      <span className="document-card-body">
        <span className="document-card-meta"><span className="document-card-type">{fileExtension(document.filename)}</span><Status document={document} /></span>
        <strong title={document.filename}>{document.filename || 'Без названия'}</strong>
        {document.has_metadata ? <span className="card-facts"><span>{number != null && number !== '' ? `№ ${formatFieldValue('contract_number', fields.contract_number)}` : 'Номер не найден'}</span><span>{amount != null && amount !== '' ? formatFieldValue('total_amount', fields.total_amount) : 'Сумма не найдена'}</span></span> : null}
        <span className="card-parties">{parties.map(party => party.name).filter(Boolean).join(' / ') || (document.status === 'processing' ? 'Извлекаем реквизиты и условия' : document.status === 'failed' ? 'Откройте документ, чтобы повторить обработку' : 'Реквизиты ещё не извлечены')}</span>
        <span className="document-card-date">{formatDate(document.created_at)}</span>
      </span>
    </button>
    <div className="document-card-actions"><button className="card-primary-action" type="button" disabled={opening} onClick={() => onOpen(document)}>{opening ? 'Открываем…' : document.has_metadata && document.review_status !== 'reviewed' ? 'Проверить данные' : 'Открыть документ'} <span aria-hidden="true">→</span></button><DocumentActions document={document} {...actions} /></div>
  </article>;
}

function FolderItem({ active, label, count, onClick, onDrop, onDelete }) {
  return <div className={`folder-item-wrap${active ? ' is-active' : ''}`} onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
    <button className="folder-item" type="button" aria-current={active ? 'true' : undefined} onClick={onClick}><span>{label}</span><span className="folder-count">{count}</span></button>
    {onDelete ? <button className="folder-delete" type="button" onClick={onDelete} aria-label={`Удалить папку ${label}`}>×</button> : null}
  </div>;
}

const SORT_OPTIONS = [['created_at', 'По дате загрузки'], ['contract_date', 'По дате договора'], ['total_amount', 'По сумме']];

function SortControl({ sortBy, sortOrder, onSort }) {
  const id = useId();
  const triggerRef = useRef(null);
  const optionsRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({});
  const label = SORT_OPTIONS.find(([value]) => value === sortBy)?.[1] ?? SORT_OPTIONS[0][1];
  const positionOptions = () => {
    const rect = triggerRef.current.getBoundingClientRect();
    const width = Math.min(230, window.innerWidth - 24);
    const below = window.innerHeight - rect.bottom - 12;
    const above = rect.top - 12;
    const down = below >= 150 || below >= above;
    setPosition({ left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
      maxHeight: Math.max(0, down ? below : above),
      ...(down ? { top: rect.bottom + 8, bottom: 'auto' } : { top: 'auto', bottom: window.innerHeight - rect.top + 8 }) });
  };
  useEffect(() => {
    if (!open) return undefined;
    const close = event => {
      if (!(event.target instanceof Node && optionsRef.current?.contains(event.target))) optionsRef.current?.hidePopover();
    };
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
    return () => { window.removeEventListener('resize', close); window.removeEventListener('scroll', close, true); };
  }, [open]);
  return <div className="sort-control" role="group" aria-label="Порядок документов">
    <button ref={triggerRef} type="button" className="sort-trigger" popoverTarget={id} aria-haspopup="dialog" aria-expanded={open} aria-controls={id} aria-label={`Сортировать по: ${label.replace('По ', '')}`} onClick={positionOptions} onKeyDown={event => {
      if (event.key === 'ArrowDown') { event.preventDefault(); positionOptions(); optionsRef.current.showPopover(); }
    }}><span>{label}</span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 7.5 5 5 5-5" /></svg></button>
    <button className="sort-direction" type="button" onClick={() => onSort(sortBy, sortOrder === 'asc' ? 'desc' : 'asc')} aria-label={sortOrder === 'asc' ? 'По возрастанию. Изменить на убывание' : 'По убыванию. Изменить на возрастание'}><svg viewBox="0 0 20 20" aria-hidden="true" style={sortOrder === 'asc' ? { transform: 'rotate(180deg)' } : undefined}><path d="M10 3v14m-5-5 5 5 5-5" /></svg></button>
    <div ref={optionsRef} id={id} popover="auto" role="dialog" aria-label="Сортировка документов" className="sort-options" style={position} onToggle={event => {
      const nextOpen = event.newState === 'open';
      setOpen(nextOpen);
      if (nextOpen) optionsRef.current.querySelector('[aria-pressed="true"]')?.focus({ preventScroll: true });
    }} onKeyDown={event => {
      const buttons = [...event.currentTarget.querySelectorAll('button')];
      const index = buttons.indexOf(document.activeElement);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : event.key === 'ArrowDown' ? (index + 1) % buttons.length : event.key === 'ArrowUp' ? (index - 1 + buttons.length) % buttons.length : null;
      if (next !== null) { event.preventDefault(); buttons[next]?.focus(); }
    }}>{SORT_OPTIONS.map(([value, name]) => <button type="button" key={value} aria-pressed={sortBy === value} onClick={() => {
      onSort(value, sortOrder); optionsRef.current.hidePopover(); triggerRef.current.focus({ preventScroll: true });
    }}><span>{name}</span><span className="sort-check" aria-hidden="true">{sortBy === value ? '✓' : ''}</span></button>)}</div>
  </div>;
}

function LibraryEmptyState({ error, search, filtered, inFolder, onRetry, onReset, onUpload }) {
  const title = error ? 'Список документов недоступен' : search ? 'Документы не найдены' : filtered ? 'В этом статусе документов нет' : inFolder ? 'В папке пока нет документов' : 'Загрузите первый договор';
  const message = error || (search ? 'Проверьте название, номер или сторону договора.' : filtered ? 'Выберите другой статус.' : inFolder ? 'Загрузите файлы или переместите их из общего списка.' : 'Реквизиты появятся после обработки.');
  return <div className="empty-state" role={error ? 'alert' : undefined}>
    <strong>{title}</strong><span>{message}</span>
    {error ? <button className="secondary-button" type="button" onClick={onRetry}>Повторить загрузку</button> : search || filtered ? <button className="secondary-button" type="button" onClick={onReset}>Сбросить поиск и фильтр</button> : <button className="primary-button" type="button" onClick={onUpload}>Выбрать документы</button>}
  </div>;
}

export default function DocumentLibrary({ token, folders, documents, openingDocumentId, totalDocuments, resultTotal, page, pageSize, onPage,
  selectedFolderId, search, sortBy, sortOrder, onSort, viewStatus, onFilter, loading, uploading, uploadMessage,
  error, onDismissError, libraryError, onRetry, onSearch, onSelectFolder, onUpload, onCreateFolder, onDeleteFolder, onMoveDocument, onOpen, onOpenFile, onDelete, onAnalyze }) {
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const cameraInputRef = useRef(null);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [showFolderForm, setShowFolderForm] = useState(false);
  const [draggedDocumentId, setDraggedDocumentId] = useState(null);
  const [view, setView] = useState(() => localStorage.getItem('contract_library_view') || (window.matchMedia('(max-width: 760px)').matches ? 'cards' : 'table'));
  const visibleDocuments = libraryError ? [] : documents;
  const selectedFolder = folders.find(folder => folder.id === selectedFolderId);
  const acceptFiles = files => { setIsDraggingFile(false); if (files?.length && !uploading) onUpload(Array.from(files)); };
  const actions = { folders, onOpenFile, onDelete, onAnalyze, onMove: onMoveDocument };
  const changePage = value => { onPage(value); listRef.current?.scrollIntoView({ block: 'start', behavior: 'instant' }); listRef.current?.focus({ preventScroll: true }); };
  const changeView = value => { setView(value); localStorage.setItem('contract_library_view', value); };
  const dropInFolder = (event, id) => { event.preventDefault(); if (draggedDocumentId) onMoveDocument(draggedDocumentId, id); setDraggedDocumentId(null); };
  const submitFolder = async event => {
    event.preventDefault();
    if (folderName.trim() && await onCreateFolder(folderName.trim())) { setFolderName(''); setShowFolderForm(false); }
  };
  return <section className="product-shell" id="main-content" tabIndex={-1} aria-labelledby="library-title">
    <header className="product-heading">
      <div><h1 id="library-title">Договоры</h1><p className="muted">{totalDocuments ? `${totalDocuments} в реестре` : 'Загрузите договор, чтобы извлечь и проверить данные'}</p></div>
      <div className="product-heading-actions"><button className="secondary-button camera-button" type="button" onClick={() => cameraInputRef.current?.click()} disabled={uploading}>Снять фото</button><button className="primary-button" type="button" aria-label={uploading ? 'Загружаем документы' : 'Загрузить документы'} aria-busy={uploading} onClick={() => inputRef.current?.click()} disabled={uploading}>{uploading ? 'Загружаем…' : <><span className="upload-label-full">Загрузить документы</span><span className="upload-label-short">Загрузить</span></>}</button></div>
      <input ref={inputRef} className="visually-hidden" tabIndex={-1} aria-hidden="true" type="file" multiple accept=".pdf,.docx,.jpg,.jpeg,.png" onChange={event => { acceptFiles(event.target.files); event.target.value = ''; }} />
      <input ref={cameraInputRef} className="visually-hidden" tabIndex={-1} aria-hidden="true" type="file" accept="image/jpeg,image/png" capture="environment" onChange={event => { acceptFiles(event.target.files); event.target.value = ''; }} />
    </header>
    <button type="button" className={`upload-strip${isDraggingFile ? ' is-dragging' : ''}`} disabled={uploading} onClick={() => inputRef.current?.click()}
      onDragEnter={event => { event.preventDefault(); if (event.dataTransfer.types.includes('Files')) setIsDraggingFile(true); }} onDragOver={event => event.preventDefault()}
      onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget)) setIsDraggingFile(false); }} onDrop={event => { event.preventDefault(); acceptFiles(event.dataTransfer.files); }}>
      <span className="upload-instruction">{uploading ? 'Загружаем документы…' : isDraggingFile ? 'Отпустите файлы для загрузки' : 'Перетащите файлы или выберите на компьютере'}</span><span>PDF, DOCX, JPG, PNG · до 50 МБ · PDF до 200 страниц</span>
    </button>
    {uploadMessage ? <p className="upload-message" role="status">{uploadMessage}</p> : null}
    {error ? <div className="error" role="alert">{error}<button className="text-button" type="button" onClick={onDismissError}>Закрыть сообщение</button></div> : null}
    <div className="library-layout">
      <aside className="folder-sidebar" aria-label="Папки документов">
        <div className="sidebar-heading"><h2>Папки</h2><button className="icon-button" type="button" onClick={() => setShowFolderForm(value => !value)} aria-expanded={showFolderForm} aria-label="Создать папку">+</button></div>
        <div className="folder-list"><FolderItem active={selectedFolderId === null} label="Все документы" count={totalDocuments} onClick={() => onSelectFolder(null)} onDrop={event => dropInFolder(event,null)} />
          {folders.map(folder => <FolderItem key={folder.id} active={selectedFolderId === folder.id} label={folder.name} count={folder.document_count} onClick={() => onSelectFolder(folder.id)} onDrop={event => dropInFolder(event,folder.id)} onDelete={() => onDeleteFolder(folder)} />)}
        </div>
        {showFolderForm ? <form className="folder-form" onSubmit={submitFolder}><label htmlFor="folder-name">Название папки</label><input id="folder-name" autoFocus value={folderName} onChange={event => setFolderName(event.target.value)} maxLength={120} required /><div><button className="small-button" type="submit">Создать</button><button className="text-button" type="button" onClick={() => setShowFolderForm(false)}>Отмена</button></div></form> : null}
      </aside>
      <section ref={listRef} tabIndex={-1} className="library-content" aria-busy={loading} aria-label="Список договоров">
        <div className="list-heading"><div><h2>{selectedFolder?.name ?? 'Все документы'}</h2></div><label className="search-box"><span className="visually-hidden">Найти документ</span><input type="search" value={search} onChange={event => onSearch(event.target.value)} placeholder="Название, номер или сторона" /></label></div>
        <div className="status-filters" role="group" aria-label="Статус документов">{DOCUMENT_FILTERS.map(([value,label]) => <button type="button" aria-pressed={viewStatus === value} className={viewStatus === value ? 'is-active' : ''} key={value} onClick={() => onFilter(value)}>{label}</button>)}</div>
        <div className="registry-toolbar"><span className="list-count" role="status">{libraryError ? 'Список не загружен' : openingDocumentId ? 'Открываем документ…' : loading ? 'Обновляем…' : resultTotal ? `${(page-1)*pageSize+1}–${Math.min(page*pageSize,resultTotal)} из ${resultTotal}` : '0 документов'}</span>
          <SortControl sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
          <div className="view-switch" role="group" aria-label="Вид списка"><button type="button" aria-pressed={view === 'table'} onClick={() => changeView('table')}>Реестр</button><button type="button" aria-pressed={view === 'cards'} onClick={() => changeView('cards')}>Карточки</button></div>
        </div>
        {loading && !visibleDocuments.length ? <div className="empty-state" role="status">Загружаем документы…</div> : visibleDocuments.length ? view === 'table' ? <div className="registry-scroll" tabIndex={0} aria-label="Таблица договоров, прокрутка по горизонтали"><table className="contract-registry"><caption className="visually-hidden">Реестр договоров</caption><thead><tr>{['Документ', 'Номер и дата', 'Стороны', 'Сумма', 'Статус', ''].map((label,index) => <th scope="col" key={index}>{label || <span className="visually-hidden">Действия</span>}</th>)}</tr></thead><tbody>{visibleDocuments.map(document => <RegistryRow key={document.id} opening={openingDocumentId === document.id} document={document} onOpen={onOpen} onDragStart={setDraggedDocumentId} {...actions} />)}</tbody></table></div> : <div className="documents-grid">{visibleDocuments.map(document => <DocumentCard key={document.id} opening={openingDocumentId === document.id} document={document} token={token} onOpen={onOpen} onDragStart={setDraggedDocumentId} {...actions} />)}</div> : <LibraryEmptyState error={libraryError} search={search} filtered={viewStatus !== 'all'} inFolder={Boolean(selectedFolder)} onRetry={onRetry} onReset={() => { onSearch(''); onFilter('all'); }} onUpload={() => inputRef.current?.click()} />}
        {!libraryError && resultTotal > pageSize ? <nav className="pagination" aria-label="Страницы документов"><button type="button" className="secondary-button" disabled={page === 1 || loading} onClick={() => changePage(page-1)}>← Назад</button><span>Страница {page} из {Math.ceil(resultTotal/pageSize)}</span><button type="button" className="secondary-button" disabled={page*pageSize >= resultTotal || loading} onClick={() => changePage(page+1)}>Далее →</button></nav> : null}
      </section>
    </div>
  </section>;
}
