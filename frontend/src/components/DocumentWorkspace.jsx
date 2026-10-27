import { useEffect, useMemo, useRef, useState } from 'react';
import { authHeaders, request, requestBlob } from '../api.js';
import RiskReviewPanel from './RiskReviewPanel.jsx';
import {
  cloneFields,
  FIELD_ORDER,
  fieldLabels,
  fieldNeedsReview,
  fieldsToPlainObject,
  fieldValueForEdit,
  formatDate,
  formatFieldValue,
  getFieldEvidence,
  getFieldPage,
  getFieldValue,
  isStructuredField,
  updateFieldValue,
} from '../contractFields.js';

function orderedEntries(fields) {
  const keys = [...FIELD_ORDER, ...Object.keys(fields ?? {}).filter((key) => !FIELD_ORDER.includes(key))];
  return keys.filter((key) => Object.hasOwn(fields ?? {}, key)).map((key) => [key, fields[key]]);
}

function partyEvidence(party) {
  return party?.name_evidence || party?.inn_evidence || null;
}

function partyPage(party) {
  return party?.name_page_number ?? party?.inn_page_number ?? null;
}

function SourceButton({ evidence, page, onSelect }) {
  if (!evidence) return <span className="source-missing">Источник не найден</span>;
  return (
    <button className="source-button" type="button" onClick={() => onSelect({ evidence, page })}>
      Показать в документе{page ? ` · стр. ${page}` : ''}
    </button>
  );
}

function PartiesValue({ parties, onSelectSource }) {
  if (!Array.isArray(parties) || !parties.length) return <span className="missing-value">Не найдены</span>;
  return (
    <div className="party-list">
      {parties.map((party, index) => (
        <div className="party-row" key={`${party.inn ?? party.name ?? index}`}>
          <div><strong>{party.name || 'Название не найдено'}</strong><span>{party.role || 'Роль не определена'}</span></div>
          <span>{party.inn ? `ИНН ${party.inn}` : 'ИНН не найден'}</span>
          <SourceButton evidence={partyEvidence(party)} page={partyPage(party)} onSelect={onSelectSource} />
        </div>
      ))}
    </div>
  );
}

function FieldRow({ fieldKey, field, active, reviewed, onSelectSource, onCopy }) {
  const evidence = getFieldEvidence(fieldKey, field);
  const page = getFieldPage(fieldKey, field);
  const needsReview = fieldNeedsReview(fieldKey, field);
  const value = getFieldValue(fieldKey, field);
  return (
    <section className={`field-row${active ? ' is-active' : ''}`}>
      <div className="field-row-heading">
        <span>{fieldLabels[fieldKey] ?? fieldKey.replaceAll('_', ' ')}</span>
        {needsReview && !reviewed ? <strong className="review-flag">Стоит проверить</strong> : <strong className="verified-flag">{needsReview ? 'Проверено оператором' : 'Источник найден'}</strong>}
      </div>
      <div className="field-row-value">
        {fieldKey === 'parties' ? <PartiesValue parties={value} onSelectSource={(source) => onSelectSource({ ...source, fieldKey })} /> : <span className={value === null || value === undefined || value === '' ? 'missing-value' : ''}>{formatFieldValue(fieldKey, field)}</span>}
        {fieldKey !== 'parties' ? <button className="copy-field" type="button" onClick={() => onCopy(formatFieldValue(fieldKey, field), fieldLabels[fieldKey])} aria-label={`Копировать: ${fieldLabels[fieldKey] ?? fieldKey}`}>Копировать</button> : null}
      </div>
      {fieldKey !== 'parties' ? (
        <div className="field-source">
          <SourceButton evidence={evidence} page={page} onSelect={(source) => onSelectSource({ ...source, fieldKey })} />
          {active && evidence ? <blockquote>{evidence}</blockquote> : null}
        </div>
      ) : null}
    </section>
  );
}

function MetadataEditor({ fields, onChange }) {
  const updateParty = (index, name, value) => {
    const next = cloneFields(fields);
    const structured = isStructuredField(next.parties);
    const parties = structured ? [...(next.parties.value ?? [])] : [...(next.parties ?? [])];
    parties[index] = { ...(parties[index] ?? {}), [name]: value };
    if (name === 'inn') {
      parties[index].inn_evidence = null;
      parties[index].inn_page_number = null;
    } else {
      parties[index].name_evidence = null;
      parties[index].name_page_number = null;
    }
    if (structured) next.parties.value = parties;
    else next.parties = parties;
    onChange(next);
  };
  const addParty = () => {
    const next = cloneFields(fields);
    const structured = isStructuredField(next.parties);
    const parties = structured ? [...(next.parties.value ?? [])] : [...(next.parties ?? [])];
    parties.push({ name: '', role: '', inn: '' });
    if (structured) next.parties.value = parties;
    else next.parties = parties;
    onChange(next);
  };
  const removeParty = (index) => {
    const next = cloneFields(fields);
    const structured = isStructuredField(next.parties);
    const parties = (structured ? next.parties.value ?? [] : next.parties ?? []).filter((_, itemIndex) => itemIndex !== index);
    if (structured) next.parties.value = parties;
    else next.parties = parties;
    onChange(next);
  };

  return (
    <div className="metadata-editor">
      {orderedEntries(fields).map(([key, field]) => {
        if (key === 'parties') {
          const parties = fieldValueForEdit(key, field);
          return (
            <fieldset className="editor-fieldset" key={key}>
              <legend>{fieldLabels[key]}</legend>
              {(parties.length ? parties : [{ name: '', role: '', inn: '' }]).map((party, index) => (
                <div className="party-editor-row" key={index}>
                  <label>Сторона<input value={party.name ?? ''} onChange={(event) => updateParty(index, 'name', event.target.value)} /></label>
                  <label>Роль<input value={party.role ?? ''} onChange={(event) => updateParty(index, 'role', event.target.value)} /></label>
                  <label>ИНН<input inputMode="numeric" value={party.inn ?? ''} onChange={(event) => updateParty(index, 'inn', event.target.value)} /></label>
                  <button className="text-button danger-link" type="button" onClick={() => removeParty(index)}>Удалить сторону</button>
                </div>
              ))}
              <button className="text-button" type="button" onClick={addParty}>+ Добавить сторону</button>
            </fieldset>
          );
        }
        if (key === 'total_amount' && isStructuredField(field)) {
          return (
            <fieldset className="editor-fieldset" key={key}>
              <legend>Общая сумма</legend>
              <label className="editor-field">Сумма<input inputMode="decimal" value={field.value ?? ''} onChange={(event) => onChange(updateFieldValue(fields, key, event.target.value))} /></label>
              <label className="editor-field">Валюта<input value={field.currency ?? ''} maxLength={3} placeholder="RUB" list="contract-currencies" onChange={(event) => {
                const next = cloneFields(fields);
                next.total_amount = { ...next.total_amount, currency: event.target.value.toUpperCase(), evidence: null, page_number: null };
                onChange(next);
              }} /></label>
              <datalist id="contract-currencies"><option value="RUB">Рубли</option><option value="USD">Доллары США</option><option value="EUR">Евро</option><option value="CNY">Юани</option><option value="KZT">Тенге</option><option value="BYN">Белорусские рубли</option></datalist>
              <span className="field-hint">Код из трёх букв: RUB — рубли, USD — доллары, EUR — евро.</span>
            </fieldset>
          );
        }
        if (key === 'vat' && isStructuredField(field)) {
          const updateVat = (name, value) => {
            const next = cloneFields(fields);
            next.vat = { ...next.vat, [name]: value, evidence: null, page_number: null, raw_value: null };
            if (name === 'mode' && value === 'not_subject') next.vat.rate = null;
            onChange(next);
          };
          return (
            <fieldset className="editor-fieldset" key={key}>
              <legend>НДС</legend>
              <label className="editor-field">Условие
                <select value={field.mode ?? 'not_stated'} onChange={(event) => updateVat('mode', event.target.value)}>
                  <option value="included">Включён в сумму</option>
                  <option value="excluded">Начисляется сверх суммы</option>
                  <option value="not_subject">Не облагается</option>
                  <option value="not_stated">Не указан</option>
                </select>
              </label>
              <label className="editor-field">Ставка, %<input inputMode="decimal" value={field.rate ?? ''} disabled={field.mode === 'not_subject'} onChange={(event) => updateVat('rate', event.target.value)} /></label>
            </fieldset>
          );
        }
        const value = fieldValueForEdit(key, field);
        const simple = typeof value !== 'object' || value === null;
        return (
          <label className="editor-field" key={key} htmlFor={`metadata-${key}`}>
            {fieldLabels[key] ?? key}
            {simple ? (
              <input id={`metadata-${key}`} type={key === 'contract_date' || key === 'term' ? 'date' : 'text'} value={value ?? ''} onChange={(event) => onChange(updateFieldValue(fields, key, event.target.value))} />
            ) : (
              <textarea id={`metadata-${key}`} rows={5} value={JSON.stringify(value, null, 2)} readOnly aria-describedby={`metadata-${key}-hint`} />
            )}
            {!simple ? <span id={`metadata-${key}-hint`} className="field-hint">Сложное значение пока доступно только для просмотра.</span> : null}
          </label>
        );
      })}
    </div>
  );
}

function highlightEvidence(text, evidence) {
  if (!evidence) return text;
  const index = text.toLocaleLowerCase('ru').indexOf(evidence.toLocaleLowerCase('ru'));
  if (index < 0) return text;
  return <>{text.slice(0, index)}<mark data-evidence="true">{text.slice(index, index + evidence.length)}</mark>{text.slice(index + evidence.length)}</>;
}

function DocumentPhoto({ document, token }) {
  const [imageUrl, setImageUrl] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = '';
    setImageUrl('');
    requestBlob(`/documents/${document.id}/file`, token, controller.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setImageUrl(objectUrl);
      })
      .catch((requestError) => {
        if (requestError.name !== 'AbortError' && !controller.signal.aborted) setImageUrl('');
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [document.id, token]);

  if (!imageUrl) return <div className="photo-loading">Открываем фотографию…</div>;
  return <img className="document-photo" src={imageUrl} alt={`Фотография документа ${document.filename || ''}`} />;
}

function RenderedPage({ documentId, number, token, location, onPageRef }) {
  const pageRef = useRef(null);
  const markRef = useRef(null);
  const [visible, setVisible] = useState(false);
  const [imageUrl, setImageUrl] = useState('');
  const [imageLoaded, setImageLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

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
  }, [documentId, number, token, visible]);

  useEffect(() => {
    if (!location || !imageLoaded || !markRef.current) return;
    const frame = requestAnimationFrame(() => markRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' }));
    return () => cancelAnimationFrame(frame);
  }, [imageLoaded, location]);

  return (
    <article className="document-page rendered-page" ref={(node) => { pageRef.current = node; onPageRef(number, node); }}>
      <div className="page-number">Страница {number}</div>
      <div className="rendered-page-canvas">
        {imageUrl ? <img src={imageUrl} onLoad={() => setImageLoaded(true)} alt={`Страница ${number} исходного документа`} /> : <div className="rendered-page-placeholder">{failed ? 'Не удалось показать страницу' : 'Открываем страницу…'}</div>}
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

function DocumentPages({ content, document, loading, selectedSource, location, token }) {
  const pageRefs = useRef(new Map());
  useEffect(() => {
    if (location?.page) {
      pageRefs.current.get(location.page)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    if (!selectedSource || content?.visual_page_count) return;
    const page = pageRefs.current.get(Number(selectedSource.page) || 1);
    if (!page) return;
    if (content?.source_format === 'image') page.querySelector('.photo-transcript')?.setAttribute('open', '');
    requestAnimationFrame(() => {
      (page.querySelector('[data-evidence]') || page).scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }, [selectedSource, content, location]);

  if (loading) return <div className="document-loading">Открываем текст документа…</div>;
  if (!content?.pages?.length) return <div className="document-loading">Текст для просмотра недоступен. Откройте оригинал документа.</div>;
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
          <p className="panel-note">Автоматическая сводка недоступна — показана сводка по извлечённым полям.</p>
        </>
      )}
    </div>
  );
}

export default function DocumentWorkspace({ document, token, error, onBack, onOpenFile, onAnalyze, onSaveMetadata, onReview, onRefreshInsights, onReviewRisks }) {
  const [activeTab, setActiveTab] = useState('fields');
  const [selectedSource, setSelectedSource] = useState(null);
  const [sourceLocation, setSourceLocation] = useState(null);
  const [sourceError, setSourceError] = useState('');
  const [refreshingInsights, setRefreshingInsights] = useState(false);
  const [insightError, setInsightError] = useState('');
  const [content, setContent] = useState(null);
  const [contentLoading, setContentLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [draftFields, setDraftFields] = useState(() => cloneFields(document.metadata?.fields));
  const [notice, setNotice] = useState('');
  const noticeTimeoutRef = useRef(null);
  const fields = document.metadata?.fields ?? {};
  const reviewCount = useMemo(() => document.review_status === 'reviewed' ? 0 : orderedEntries(fields).filter(([key, field]) => fieldNeedsReview(key, field)).length, [fields, document.review_status]);
  const riskCount = document.metadata?.risk_review?.status === 'complete' ? document.metadata.risk_review.findings.length : 0;

  useEffect(() => {
    setEditing(false);
  }, [document.id]);

  useEffect(() => {
    const controller = new AbortController();
    setContentLoading(true);
    request(`/documents/${document.id}/content`, { headers: authHeaders(token), signal: controller.signal })
      .then(setContent)
      .catch((requestError) => { if (requestError.name !== 'AbortError') setContent(null); })
      .finally(() => { if (!controller.signal.aborted) setContentLoading(false); });
    return () => controller.abort();
  }, [document.has_metadata, document.id, document.status, token]);

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
      showNotice(`${label || 'Значение'} скопировано`);
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
    try {
      await onSaveMetadata(document, draftFields);
      setEditing(false);
      showNotice('Изменения сохранены');
    } catch {
      // The parent displays the actionable request error.
    } finally {
      setSaving(false);
    }
  };

  const updateReview = async (confirmed) => {
    setReviewing(true);
    try {
      await onReview(document, confirmed);
      showNotice(confirmed ? 'Проверка подтверждена и сохранена' : 'Документ возвращён на проверку');
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
  return (
    <section className="workspace-shell">
      <header className="workspace-header">
        <button className="back-button" type="button" onClick={() => { if (!editing || window.confirm('Есть несохранённые изменения. Вернуться к списку без сохранения?')) onBack(); }}><span aria-hidden="true">←</span> К списку договоров</button>
        <div className="workspace-titlebar">
          <div className="workspace-title">
            <p className="eyebrow">Проверка договора</p>
            <h1>{document.filename || 'Документ'}</h1>
            <p className="workspace-meta">Добавлен {formatDate(document.created_at)}</p>
          </div>
          <div className="workspace-actions">
            {hasMetadata && !editing ? <button className="secondary-button" type="button" onClick={copyAll}>Копировать всё</button> : null}
            {hasMetadata && !editing ? <button className="secondary-button" type="button" onClick={exportJson}>Скачать JSON</button> : null}
            {document.has_file ? <button className="secondary-button" type="button" onClick={() => onOpenFile(document)}>Открыть оригинал</button> : null}
            {hasMetadata && !editing ? <button className="secondary-button compact-button" type="button" onClick={() => { setDraftFields(cloneFields(fields)); setActiveTab('fields'); setEditing(true); }}>Редактировать</button> : null}
            {hasMetadata && !editing && document.review_status !== 'reviewed' ? <button className="primary-button compact-button" type="button" disabled={reviewing} onClick={() => updateReview(true)}>{reviewing ? 'Сохраняем…' : 'Подтвердить поля'}</button> : null}
            {hasMetadata && !editing && document.review_status === 'reviewed' ? <button className="secondary-button compact-button" type="button" disabled={reviewing} onClick={() => updateReview(false)}>Вернуть поля на проверку</button> : null}
            {editing ? <button className="secondary-button" type="button" onClick={() => { setEditing(false); setDraftFields(cloneFields(fields)); }}>Отменить</button> : null}
            {editing ? <button className="primary-button compact-button" type="button" disabled={saving} onClick={saveMetadata}>{saving ? 'Сохраняем…' : 'Сохранить'}</button> : null}
          </div>
        </div>
      </header>
      {notice ? <div className="toast" role="status">{notice}</div> : null}
      {error ? <p className="error" role="alert">{error}</p> : null}

      {hasMetadata ? (
        <div className={`review-state${document.review_status === 'reviewed' ? ' is-reviewed' : ''}`}>
          <span aria-hidden="true" />
          <strong>{document.review_status === 'reviewed' ? 'Поля проверены оператором' : 'Поля ожидают проверки оператора'}</strong>
          {document.review_status === 'reviewed' && document.reviewed_at ? <time dateTime={document.reviewed_at}>{new Date(document.reviewed_at).toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' })}</time> : <small>Проверьте сомнительные значения и подтвердите результат.</small>}
        </div>
      ) : null}

      {!hasMetadata ? (
        <div className={`processing-state is-${document.status}`}>
          <div className="processing-line" />
          <strong>{document.status === 'processing' ? 'Извлекаем данные из договора…' : document.status === 'failed' ? 'Не удалось обработать документ' : 'Документ готов к анализу'}</strong>
          <span>{document.processing_error || (document.status === 'processing' ? 'Можно вернуться в библиотеку — обработка продолжится в фоне.' : 'Запустите анализ, чтобы получить ключевые условия.')}</span>
          {canStartAnalysis ? <button className="primary-button" type="button" onClick={() => onAnalyze(document)}>{document.status === 'failed' ? 'Повторить анализ' : 'Начать анализ'}</button> : null}
        </div>
      ) : (
        <div className="workspace-grid">
          <aside className="review-panel">
            <nav className="workspace-tabs" aria-label="Разделы анализа">
              <button type="button" aria-pressed={activeTab === 'fields'} className={activeTab === 'fields' ? 'is-active' : ''} onClick={() => setActiveTab('fields')}>Поля{reviewCount ? <span>{reviewCount} проверить</span> : null}</button>
              <button type="button" aria-pressed={activeTab === 'summary'} className={activeTab === 'summary' ? 'is-active' : ''} onClick={() => setActiveTab('summary')}>Кратко</button>
              <button type="button" aria-pressed={activeTab === 'risks'} className={activeTab === 'risks' ? 'is-active' : ''} onClick={() => setActiveTab('risks')}>Риски{riskCount ? <span>{riskCount}</span> : null}</button>
            </nav>
            <div className="review-content">
              {editing ? <MetadataEditor fields={draftFields} onChange={setDraftFields} /> : null}
              {!editing && activeTab === 'fields' ? orderedEntries(fields).map(([key, field]) => <FieldRow key={key} fieldKey={key} field={field} active={selectedSource?.fieldKey === key} reviewed={document.review_status === 'reviewed'} onSelectSource={setSelectedSource} onCopy={copyValue} />) : null}
              {!editing && activeTab === 'summary' ? <SummaryPanel fields={fields} summary={document.metadata?.summary} onRefresh={refreshInsights} refreshing={refreshingInsights} insightError={insightError} /> : null}
              {!editing && activeTab === 'risks' ? <RiskReviewPanel key={document.id} fields={fields} review={document.metadata?.risk_review} legacyRisks={document.metadata?.risks} onSelectSource={setSelectedSource} onRun={(profile) => onReviewRisks(document, profile)} /> : null}
            </div>
          </aside>
          <section className="document-panel" aria-label="Текст договора">
            <div className="document-panel-heading"><strong>Документ</strong><span>{content?.visual_page_count || content?.page_count ? `${content.visual_page_count || content.page_count} стр.` : ''}</span></div>
            {sourceError ? <p className="source-location-error" role="status">{sourceError}</p> : null}
            {content?.visual_error ? <p className="source-location-error" role="status">{content.visual_error}. Показан извлечённый текст.</p> : null}
            <DocumentPages content={content} document={document} loading={contentLoading} selectedSource={selectedSource} location={sourceLocation} token={token} />
          </section>
        </div>
      )}
    </section>
  );
}
