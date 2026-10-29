import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { authHeaders, friendlyError, request, requestBlob } from '../api.js';
import RiskReviewPanel from './RiskReviewPanel.jsx';
import ActionMenu from './ActionMenu.jsx';
import { FieldRow, MetadataEditor, orderedEntries } from './ContractFields.jsx';
import { cloneFields, fieldLabels, fieldNeedsReview, fieldsToPlainObject, formatDate, formatFieldValue, getFieldValue } from '../contractFields.js';

function scrollToSource(node) {
  const panel = node?.closest('.document-panel');
  if (!panel) return;
  const bounds = panel.getBoundingClientRect();
  const target = node.getBoundingClientRect();
  panel.scrollTo({
    top: Math.max(0, panel.scrollTop + target.top - bounds.top - (panel.clientHeight - target.height) / 2),
    left: Math.max(0, panel.scrollLeft + target.left - bounds.left - (panel.clientWidth - target.width) / 2),
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
  });
}

function highlightEvidence(text, evidence) {
  if (!evidence) return text;
  const index = text.toLocaleLowerCase('ru').indexOf(evidence.toLocaleLowerCase('ru'));
  if (index < 0) return text;
  return <>{text.slice(0, index)}<mark data-evidence="true">{text.slice(index, index + evidence.length)}</mark>{text.slice(index + evidence.length)}</>;
}

function DocumentPhoto({ document, token }) {
  const [imageUrl, setImageUrl] = useState('');
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = '';
    setImageUrl('');
    setFailed(false);
    requestBlob(`/documents/${document.id}/file`, token, controller.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setImageUrl(objectUrl);
      })
      .catch((requestError) => {
        if (requestError.name !== 'AbortError' && !controller.signal.aborted) setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [document.id, token, attempt]);

  if (failed) return <div className="photo-loading" role="alert"><p>Не удалось открыть фотографию.</p><button className="secondary-button" type="button" onClick={() => setAttempt(value => value+1)}>Повторить</button></div>;
  if (!imageUrl) return <div className="photo-loading">Открываем фотографию…</div>;
  return <img className="document-photo" src={imageUrl} onError={() => { setImageUrl(''); setFailed(true); }} alt={`Фотография документа ${document.filename || ''}`} />;
}

function RenderedPage({ documentId, number, token, location, onPageRef }) {
  const pageRef = useRef(null);
  const markRef = useRef(null);
  const [visible, setVisible] = useState(false);
  const [imageUrl, setImageUrl] = useState('');
  const [imageLoaded, setImageLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: '800px' });
    if (pageRef.current) observer.observe(pageRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return undefined;
    setFailed(false);
    setImageUrl('');
    setImageLoaded(false);
    const controller = new AbortController();
    let url = '';
    requestBlob(`/documents/${documentId}/pages/${number}/image`, token, controller.signal)
      .then((blob) => {
        url = URL.createObjectURL(blob);
        setImageUrl(url);
      })
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') setFailed(true);
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [documentId, number, token, visible, attempt]);

  useEffect(() => {
    if (!location || !imageLoaded || !markRef.current) return;
    const frame = requestAnimationFrame(() => scrollToSource(markRef.current));
    return () => cancelAnimationFrame(frame);
  }, [imageLoaded, location]);

  return (
    <article className="document-page rendered-page" ref={(node) => { pageRef.current = node; onPageRef(number, node); }}>
      <div className="page-number">Страница {number}</div>
      <div className="rendered-page-canvas">
        {imageUrl ? <img src={imageUrl} onLoad={() => setImageLoaded(true)} onError={() => { setImageUrl(''); setImageLoaded(false); setFailed(true); }} alt={`Страница ${number} исходного документа`} /> : <div className="rendered-page-placeholder">{failed ? <div role="alert"><p>Не удалось показать страницу.</p><button className="secondary-button" type="button" onClick={() => setAttempt(value => value+1)}>Повторить</button></div> : 'Открываем страницу…'}</div>}
        {imageUrl && location?.rects?.map((rect, index) => (
          <mark
            key={index}
            ref={index === 0 ? markRef : undefined}
            className="source-highlight"
            style={{ left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.width * 100}%`, height: `${rect.height * 100}%` }}
            aria-label={index === 0 ? 'Найденный фрагмент' : undefined}
          />
        ))}
      </div>
    </article>
  );
}

function DocumentPages({ content, document, loading, selectedSource, location, token, onRetry, onOpenFile }) {
  const pageRefs = useRef(new Map());
  useEffect(() => {
    if (location?.page) {
      scrollToSource(pageRefs.current.get(location.page));
      return;
    }
    if (!selectedSource || content?.visual_page_count) return;
    const page = pageRefs.current.get(Number(selectedSource.page) || 1);
    if (!page) return;
    if (content?.source_format === 'image') page.querySelector('.photo-transcript')?.setAttribute('open', '');
    requestAnimationFrame(() => {
      scrollToSource(page.querySelector('[data-evidence]') || page);
    });
  }, [selectedSource, content, location]);

  if (loading) return <div className="document-loading">Открываем текст документа…</div>;
  if (!content?.pages?.length) return <div className="document-loading" role="alert"><p>Не удалось открыть документ для просмотра.</p><div className="processing-actions"><button className="secondary-button" type="button" onClick={onRetry}>Повторить</button>{document.has_file ? <button className="text-button" type="button" onClick={() => onOpenFile(document)}>Скачать оригинал</button> : null}</div></div>;
  if (content.visual_page_count) {
    return (
      <div className="document-pages visual-document-pages">
        {Array.from({ length: content.visual_page_count }, (_, index) => (
          <RenderedPage key={index + 1} documentId={document.id} number={index + 1} token={token} location={location?.page === index + 1 ? location : null} onPageRef={(number, node) => { if (node) pageRefs.current.set(number, node); else pageRefs.current.delete(number); }} />
        ))}
      </div>
    );
  }
  if (content.source_format === 'image') {
    const page = content.pages[0];
    return (
      <div className="document-pages photo-document-pages">
        <article className="document-page photo-document-page" ref={(node) => { if (node) pageRefs.current.set(1, node); }}>
          <div className="page-number">Фотография документа</div>
          <DocumentPhoto document={document} token={token} />
          <details className="photo-transcript">
            <summary>Распознанный текст</summary>
            <div className="page-text">{highlightEvidence(page.text, selectedSource?.evidence)}</div>
          </details>
        </article>
      </div>
    );
  }
  return (
    <div className="document-pages">
      {content.pages.map((page) => (
        <article className="document-page" key={page.number} ref={(node) => { if (node) pageRefs.current.set(page.number, node); }}>
          <div className="page-number">Страница {page.number}</div>
          <div className="page-text">{highlightEvidence(page.text, Number(selectedSource?.page) === page.number ? selectedSource.evidence : null)}</div>
        </article>
      ))}
    </div>
  );
}

function buildSummary(fields) {
  const number = formatFieldValue('contract_number', fields.contract_number);
  const date = formatFieldValue('contract_date', fields.contract_date);
  const type = formatFieldValue('contract_type', fields.contract_type);
  const amount = formatFieldValue('total_amount', fields.total_amount);
  const term = formatFieldValue('term', fields.term);
  const parties = getFieldValue('parties', fields.parties);
  const partyNames = Array.isArray(parties) ? parties.map((party) => party.name).filter(Boolean) : [];
  return {
    intro: `${type !== 'Не найдено' ? type : 'Договор'}${number !== 'Не найдено' ? ` № ${number}` : ''}${date !== 'Не найдено' ? ` от ${date}` : ''}.`,
    facts: [
      partyNames.length ? ['Стороны', partyNames.join(' и ')] : null,
      amount !== 'Не найдено' ? ['Сумма', amount] : null,
      term !== 'Не найдено' ? ['Срок', term] : null,
    ].filter(Boolean),
  };
}

function SummaryPanel({ fields, summary, onRefresh, refreshing, insightError }) {
  const derived = buildSummary(fields);
  return (
    <div className="summary-panel">
      <div className="insights-heading"><p className="panel-kicker">Краткая сводка</p><button type="button" className="source-button" onClick={onRefresh} disabled={refreshing}>{refreshing ? 'Анализируем…' : summary ? 'Обновить сводку' : 'Создать сводку'}</button></div>
      {insightError ? <p className="insights-error" role="alert">{insightError}</p> : null}
      {summary ? (
        <p className="summary-ai-text">{summary}</p>
      ) : (
        <>
          <p className="summary-intro">{derived.intro}</p>
          <dl>{derived.facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
          <p className="panel-note">Сводка ещё не создана. Показаны реквизиты договора.</p>
        </>
      )}
    </div>
  );
}

export default function DocumentWorkspace({ document, token, error, onClearError, onBack, onNext, onDirtyChange, onConfirm, onOpenFile, onAnalyze, onSaveMetadata, onReview, onRefreshInsights, onReviewRisks }) {
  const [activeTab, setActiveTab] = useState('fields');
  const [fieldFilter, setFieldFilter] = useState('all');
  const [mobilePane, setMobilePane] = useState('review');
  const [zoom, setZoom] = useState(1);
  const [nextLoading, setNextLoading] = useState(false);
  const [queueEmpty, setQueueEmpty] = useState(false);
  const [selectedSource, setSelectedSource] = useState(null);
  const [sourceLocation, setSourceLocation] = useState(null);
  const [sourceError, setSourceError] = useState('');
  const [refreshingInsights, setRefreshingInsights] = useState(false);
  const [insightError, setInsightError] = useState('');
  const [content, setContent] = useState(null);
  const [contentLoading, setContentLoading] = useState(true);
  const [contentAttempt, setContentAttempt] = useState(0);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [startingAnalysis, setStartingAnalysis] = useState(false);
  const [editError, setEditError] = useState('');
  const [reviewing, setReviewing] = useState(false);
  const [draftFields, setDraftFields] = useState(() => cloneFields(document.metadata?.fields));
  const [notice, setNotice] = useState('');
  const noticeTimeoutRef = useRef(null);
  const reviewContentRef = useRef(null);
  const lastEditedFieldRef = useRef(null);
  useLayoutEffect(() => {
    reviewContentRef.current?.scrollTo({ top: 0, behavior: 'instant' });
  }, [activeTab]);
  const fields = document.metadata?.fields ?? {};
  const reviewCount = useMemo(() => document.review_status === 'reviewed' ? 0 : orderedEntries(fields).filter(([key, field]) => fieldNeedsReview(key, field)).length, [fields, document.review_status]);
  const riskCount = document.metadata?.risk_review?.status === 'complete' ? document.metadata.risk_review.findings.length : 0;
  const dirty = Boolean(editing && JSON.stringify(draftFields) !== JSON.stringify(fields));
  const isProcessing = document.status === 'processing' || document.status === 'uploaded';
  const selectSource = (source) => { setSelectedSource(source); setMobilePane('document'); };
  const startEditing = (key) => { onClearError(); setEditError(''); setDraftFields(cloneFields(fields)); setActiveTab('fields'); setEditing(key); setMobilePane('review'); };
  const updateDraft = (next) => { setDraftFields(next); setEditError(''); };
  const cancelEditing = async () => {
    if (!dirty || await onConfirm({title:'Отменить изменения?',description:'Правки этого поля не будут сохранены.',confirmLabel:'Отменить изменения',cancelLabel:'Продолжить редактирование'})) { onClearError(); setEditError(''); setEditing(false); setDraftFields(cloneFields(fields)); }
  };
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = event => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);


  useEffect(() => {
    setEditing(false);
    const frame = requestAnimationFrame(() => window.document.querySelector('.workspace-title h1')?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(frame);
  }, [document.id]);

  useEffect(() => {
    if (editing) lastEditedFieldRef.current = editing;
    const previous = lastEditedFieldRef.current;
    if (!editing) lastEditedFieldRef.current = null;
    if (!editing && !previous) return undefined;
    const frame = requestAnimationFrame(() => {
      const target = editing
        ? window.document.querySelector('.inline-editor input, .inline-editor select')
        : previous === 'all'
          ? window.document.querySelector('.edit-field-button')
          : window.document.getElementById(`field-${previous}`)?.querySelector('.edit-field-button');
      target?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [editing]);

  useEffect(() => {
    const controller = new AbortController();
    setContentLoading(true);
    request(`/documents/${document.id}/content`, { headers: authHeaders(token), signal: controller.signal })
      .then(setContent)
      .catch((requestError) => { if (requestError.name !== 'AbortError') setContent(null); })
      .finally(() => { if (!controller.signal.aborted) setContentLoading(false); });
    return () => controller.abort();
  }, [document.has_metadata, document.id, document.status, token, contentAttempt]);

  useEffect(() => {
    setSourceLocation(null);
    setSourceError('');
    if (!selectedSource?.evidence || !content?.visual_page_count) return undefined;
    const controller = new AbortController();
    request(`/documents/${document.id}/source-location`, {
      method: 'POST', headers: authHeaders(token), signal: controller.signal,
      body: JSON.stringify({ evidence: selectedSource.evidence, page: selectedSource.page || null }),
    })
      .then(setSourceLocation)
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') setSourceError('Цитату не удалось точно найти на странице. Проверьте исходный документ вручную.');
      });
    return () => controller.abort();
  }, [selectedSource, content, document.id, token]);

  useEffect(() => () => {
    if (noticeTimeoutRef.current) window.clearTimeout(noticeTimeoutRef.current);
  }, []);

  const showNotice = (message) => {
    setNotice(message);
    if (noticeTimeoutRef.current) window.clearTimeout(noticeTimeoutRef.current);
    noticeTimeoutRef.current = window.setTimeout(() => setNotice(''), 2200);
  };
  const copyValue = async (value, label) => {
    try {
      await navigator.clipboard.writeText(String(value));
      showNotice(label ? `Скопировано: ${label}` : 'Значение скопировано');
    } catch {
      showNotice('Не удалось скопировать значение');
    }
  };
  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(fieldsToPlainObject(fields), null, 2));
      showNotice('Все поля скопированы');
    } catch {
      showNotice('Не удалось скопировать поля');
    }
  };
  const exportJson = () => {
    const blob = new Blob([JSON.stringify(fieldsToPlainObject(fields), null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement('a');
    anchor.href = url;
    anchor.download = `${document.filename || 'contract'}-fields.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  const saveMetadata = async () => {
    setSaving(true);
    setEditError('');
    try {
      await onSaveMetadata(document, draftFields);
      setSelectedSource(null);
      setSourceLocation(null);
      setSourceError('');
      setEditing(false);
      showNotice('Изменения сохранены');
    } catch (requestError) {
      setEditError(friendlyError(requestError));
    } finally {
      setSaving(false);
    }
  };

  const updateReview = async (confirmed) => {
    setReviewing(true);
    try {
      await onReview(document, confirmed);
      showNotice(confirmed ? 'Проверка подтверждена и сохранена' : 'Документ возвращён на проверку');
      requestAnimationFrame(() => reviewContentRef.current?.parentElement?.querySelector('.review-footer button')?.focus());
    } catch {
      // The parent displays the actionable request error.
    } finally {
      setReviewing(false);
    }
  };

  const refreshInsights = async () => {
    setRefreshingInsights(true);
    setInsightError('');
    try {
      const result = await onRefreshInsights(document);
      if (result.errors?.length) setInsightError(result.errors.join(' '));
      else showNotice('Сводка обновлена');
    } catch {
      setInsightError('Не удалось обновить анализ. Повторите попытку позже.');
    } finally {
      setRefreshingInsights(false);
    }
  };

  const hasMetadata = document.has_metadata && document.metadata?.fields;
  const canStartAnalysis = document.status === 'ready' || document.status === 'failed';
  const isReviewed = document.review_status === 'reviewed';
  const visibleFieldKeys = new Set(orderedEntries(fields).map(([key]) => key));
  const fieldGroups = [
    ['Реквизиты', ['contract_number', 'contract_date', 'contract_type', 'place']],
    ['Стороны', ['parties']],
    ['Условия', ['total_amount', 'vat', 'term']],
    ['Другие сведения', orderedEntries(fields).map(([key]) => key).filter(key => !['contract_number','contract_date','contract_type','place','parties','total_amount','vat','term'].includes(key))],
  ];
  const nextDocument = async () => {
    setNextLoading(true);
    try {
      if (!await onNext()) { setQueueEmpty(true); showNotice('Договоров, готовых к проверке, больше нет'); }
    } catch { showNotice('Не удалось открыть следующий документ. Попробуйте ещё раз.'); }
    finally { setNextLoading(false); }
  };
  const repeatAnalysis = async () => {
    if (startingAnalysis) return;
    setStartingAnalysis(true);
    try { await onAnalyze(document); } finally { setStartingAnalysis(false); }
  };
  return (
    <section className="workspace-shell" id="main-content" tabIndex={-1}>
      <header className="workspace-header">
        <div className="workspace-navigation"><button className="back-button" type="button" onClick={onBack}><span aria-hidden="true">←</span> Назад к списку</button><span className="workspace-file-type">{document.filename?.split('.').pop()?.toUpperCase()}</span><span className="workspace-meta">Добавлен {formatDate(document.created_at)}</span></div>
        <div className="workspace-titlebar"><div className="workspace-title"><h1 tabIndex={-1} title={document.filename || 'Документ'}>{document.filename || 'Документ'}</h1></div>
          <div className="workspace-actions">
            {hasMetadata && !editing ? <button className="secondary-button compact-button" type="button" aria-label="Скачать JSON" onClick={exportJson}>Скачать JSON <span aria-hidden="true">↓</span></button> : null}
            <ActionMenu label="Другие действия с договором">
              {document.has_file ? <button type="button" onClick={() => onOpenFile(document)}>Скачать оригинал</button> : null}
              {hasMetadata && !editing ? <><button type="button" onClick={copyAll}>Копировать все данные</button><button type="button" disabled={isProcessing || startingAnalysis} onClick={() => startEditing('all')}>Редактировать все поля</button><button type="button" disabled={isProcessing || startingAnalysis} onClick={repeatAnalysis}>Извлечь заново…</button>{isReviewed ? <button type="button" disabled={reviewing || isProcessing || startingAnalysis} onClick={() => updateReview(false)}>Вернуть на проверку</button> : null}</> : null}
            </ActionMenu>
          </div>
        </div>
      </header>
      {notice ? <div className="toast" role="status">{notice}</div> : null}
      {error && !editing ? <p className="error" role="alert">{error}</p> : null}
      {hasMetadata ? <div className={`review-state${isReviewed ? ' is-reviewed' : ''}`} role="status"><span aria-hidden="true" />
        <strong>{isProcessing ? 'Извлекаем данные заново…' : isReviewed ? 'Реквизиты проверены' : 'Реквизиты на проверке'}</strong>
        {isReviewed && document.reviewed_at && !isProcessing ? <time dateTime={document.reviewed_at}>{new Date(document.reviewed_at).toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' })}</time> : reviewCount && !isProcessing ? <small>Требуют внимания: {reviewCount}</small> : null}
      </div> : null}
      {hasMetadata && document.status === 'failed' ? <div className="error" role="alert"><strong>Не удалось извлечь данные заново. Показан сохранённый результат.</strong><span>{document.processing_error || 'Повторите обработку.'}</span><button className="text-button" type="button" disabled={startingAnalysis} onClick={repeatAnalysis}>{startingAnalysis ? 'Запускаем…' : 'Повторить обработку'}</button></div> : null}
      {!hasMetadata ? <div className={`processing-state is-${document.status}`} role="status"><div className="processing-line" />
        <strong>{isProcessing ? 'Извлекаем данные из договора…' : document.status === 'failed' ? 'Не удалось обработать документ' : 'Документ загружен'}</strong>
        <span>{document.processing_error || (isProcessing ? 'Можно вернуться к списку. Обработка продолжится, результат сохранится.' : 'Запустите обработку, чтобы получить реквизиты и условия договора.')}</span>
        <div className="processing-actions">{canStartAnalysis ? <button className="primary-button" type="button" disabled={startingAnalysis} aria-busy={startingAnalysis} onClick={repeatAnalysis}>{startingAnalysis ? 'Запускаем…' : document.status === 'failed' ? 'Повторить обработку' : 'Извлечь данные'}</button> : null}<button className="secondary-button" type="button" onClick={onBack}>К списку документов</button></div>
      </div> : <>
        <nav className="mobile-pane-switch" aria-label="Разделы договора">
          <button type="button" aria-pressed={mobilePane === 'review' && activeTab === 'fields'} onClick={() => { setMobilePane('review'); setActiveTab('fields'); }}>Реквизиты{reviewCount ? <span>{reviewCount}</span> : null}</button>
          {document.metadata?.processing?.backend !== 'rules' ? <><button type="button" disabled={Boolean(editing)} aria-pressed={mobilePane === 'review' && activeTab === 'summary'} onClick={() => { setMobilePane('review'); setActiveTab('summary'); }}>Сводка</button><button type="button" disabled={Boolean(editing)} aria-pressed={mobilePane === 'review' && activeTab === 'risks'} onClick={() => { setMobilePane('review'); setActiveTab('risks'); }}>Риски{riskCount ? <span>{riskCount}</span> : null}</button></> : null}
          <button type="button" aria-pressed={mobilePane === 'document'} onClick={() => setMobilePane('document')}>Документ</button>
        </nav>
        <div className={`workspace-grid show-${mobilePane}`}>
          <aside className="review-panel" aria-label="Данные договора">
            <nav className="workspace-tabs" aria-label="Разделы анализа">
              <button type="button" disabled={Boolean(editing)} aria-pressed={activeTab === 'fields'} className={activeTab === 'fields' ? 'is-active' : ''} onClick={() => setActiveTab('fields')}>Реквизиты{reviewCount ? <span>{reviewCount}</span> : null}</button>
              {document.metadata?.processing?.backend !== 'rules' ? <><button type="button" disabled={Boolean(editing)} aria-pressed={activeTab === 'summary'} className={activeTab === 'summary' ? 'is-active' : ''} onClick={() => setActiveTab('summary')}>Сводка</button><button type="button" disabled={Boolean(editing)} aria-pressed={activeTab === 'risks'} className={activeTab === 'risks' ? 'is-active' : ''} onClick={() => setActiveTab('risks')}>Риски{riskCount ? <span>{riskCount}</span> : null}</button></> : null}
            </nav>
            <div ref={reviewContentRef} className="review-content">
              {activeTab === 'fields' && !editing ? <div className="field-filter" role="group" aria-label="Показать поля"><button type="button" aria-pressed={fieldFilter === 'all'} onClick={() => setFieldFilter('all')}>Все поля</button><button type="button" aria-pressed={fieldFilter === 'attention'} onClick={() => setFieldFilter('attention')}>Проверить{reviewCount ? ` · ${reviewCount}` : ''}</button></div> : null}
              {editing === 'all' ? <form className="inline-editor" onSubmit={event => { event.preventDefault(); void saveMetadata(); }}><h2>Редактирование реквизитов</h2><MetadataEditor fields={draftFields} onChange={updateDraft} />{editError ? <p className="error" role="alert">{editError}</p> : null}<div className="inline-editor-actions"><button className="primary-button" disabled={saving || !dirty}>Сохранить изменения</button><button className="text-button" type="button" disabled={saving} onClick={cancelEditing}>Отмена</button></div></form> : null}
              {editing !== 'all' && activeTab === 'fields' ? fieldGroups.map(([label,keys]) => {
                const entries = keys.filter(key => visibleFieldKeys.has(key) && (fieldFilter !== 'attention' || (!isReviewed && fieldNeedsReview(key,fields[key])) || editing === key));
                return entries.length ? <div className="field-group" key={label}><h2>{label}</h2>{entries.map(key => editing === key ? <form className="inline-editor" key={key} onSubmit={event => { event.preventDefault(); void saveMetadata(); }}><MetadataEditor fields={draftFields} onlyKey={key} onChange={updateDraft} />{editError ? <p className="error" role="alert">{editError}</p> : null}<div className="inline-editor-actions"><button className="primary-button compact-button" disabled={saving || !dirty}>{saving ? 'Сохраняем…' : 'Сохранить'}</button><button className="text-button" disabled={saving} type="button" onClick={cancelEditing}>Отмена</button></div></form> : <FieldRow showPages={content?.source_format !== 'docx'} key={key} fieldKey={key} field={fields[key]} active={selectedSource?.fieldKey === key} reviewed={isReviewed} onSelectSource={selectSource} onCopy={copyValue} onEdit={startEditing} disabled={isProcessing || startingAnalysis || Boolean(editing)} />)}</div> : null;
              }) : null}
              {activeTab === 'fields' && fieldFilter === 'attention' && !reviewCount && !editing ? <div className="empty-panel"><strong>{isReviewed ? 'Проверка завершена' : 'Сомнительных полей не отмечено'}</strong><span>{isReviewed ? 'Результат сохранён. Можно перейти к следующему договору.' : 'Перед подтверждением просмотрите все поля и оригинал.'}</span><button type="button" className="text-button" onClick={() => setFieldFilter('all')}>Показать все поля</button></div> : null}
              {!editing && activeTab === 'summary' ? <SummaryPanel fields={fields} summary={document.metadata?.summary} onRefresh={refreshInsights} refreshing={refreshingInsights} insightError={insightError} /> : null}
              {!editing && activeTab === 'risks' ? <RiskReviewPanel showPages={content?.source_format !== 'docx'} key={document.id} fields={fields} review={document.metadata?.risk_review} legacyRisks={document.metadata?.risks} onSelectSource={selectSource} onOpenFields={() => setActiveTab('fields')} onRun={profile => onReviewRisks(document,profile)} /> : null}
            </div>
            <footer className="review-footer">
              {editing ? <span className="save-status" role="status">{dirty ? 'Есть несохранённые изменения' : 'Измените значение и сохраните'}</span> : isReviewed ? <button className="primary-button" type="button" disabled={reviewing || nextLoading || isProcessing || startingAnalysis} onClick={queueEmpty ? onBack : nextDocument}>{nextLoading ? 'Открываем…' : queueEmpty ? 'К списку договоров' : 'Следующий на проверку →'}</button> : activeTab === 'fields' ? <button className="primary-button" type="button" disabled={reviewing || isProcessing || startingAnalysis} onClick={() => updateReview(true)}>{reviewing ? 'Сохраняем…' : 'Подтвердить реквизиты'}</button> : <button className="secondary-button" type="button" onClick={() => setActiveTab('fields')}>Проверить реквизиты <span aria-hidden="true">→</span></button>}
            </footer>
          </aside>
          <section className="document-panel" aria-label="Оригинал договора">
            <div className="document-panel-heading"><strong>{content?.visual_page_count ? 'Оригинал документа' : 'Текст документа'}</strong><span>{content?.visual_page_count || content?.page_count ? `${content.visual_page_count || content.page_count} стр.` : ''}</span>{content?.visual_page_count ? <div className="document-zoom"><button type="button" aria-label="Уменьшить документ" disabled={zoom <= 0.75} onClick={() => setZoom(value => Math.max(0.75,value-0.25))}>−</button><button type="button" onClick={() => setZoom(1)} aria-label="Сбросить масштаб">{Math.round(zoom*100)}%</button><button type="button" aria-label="Увеличить документ" disabled={zoom >= 2} onClick={() => setZoom(value => Math.min(2,value+0.25))}>+</button></div> : null}</div>
            {selectedSource ? <div className="selected-source-note">{selectedSource.fieldKey ? fieldLabels[selectedSource.fieldKey] : 'Условие договора'}<span>{sourceLocation ? `Страница ${sourceLocation.page}` : sourceError ? 'Проверьте источник вручную' : content?.visual_page_count ? 'Ищем фрагмент…' : 'Источник выбран'}</span><button type="button" className="text-button" onClick={() => { setSelectedSource(null); setSourceLocation(null); }}>Снять выделение</button></div> : null}
            {sourceError ? <p className="source-location-error" role="status">{sourceError}</p> : null}
            {content?.visual_error ? <p className="source-location-error" role="status">{content.visual_error}. Показан извлечённый текст.</p> : null}
            <div style={{ '--document-scale':zoom }}><DocumentPages content={content} document={document} loading={contentLoading} selectedSource={selectedSource} location={sourceLocation} token={token} onRetry={() => setContentAttempt(value => value+1)} onOpenFile={onOpenFile} /></div>
          </section>
        </div>
      </>}
    </section>
  );
}
