import { cloneFields, FIELD_ORDER, fieldLabels, fieldNeedsReview, fieldValueForEdit,
  formatFieldValue, getFieldEvidence, getFieldPage, getFieldValue, isStructuredField, updateFieldValue } from '../contractFields.js';

export function orderedEntries(fields) {
  const order = fields?._provenance?.backend === 'rules' ? ['contract_number', 'contract_date', 'parties', 'total_amount'] : FIELD_ORDER;
  const keys = [...order, ...Object.keys(fields ?? {}).filter((key) => !key.startsWith('_') && !FIELD_ORDER.includes(key))];
  return keys.filter((key) => Object.hasOwn(fields ?? {}, key)).map((key) => [key, fields[key]]);
}

function SourceButton({ evidence, page, paragraph, onSelect, showPages = true, manual = false, label = 'В документе' }) {
  if (!evidence) return <span className="source-missing">{manual ? 'Изменено оператором' : 'Источник не найден'}</span>;
  return (
    <button className="source-button" type="button" onClick={() => onSelect({ evidence, page })}>
      {label}{paragraph ? ` · абз. ${paragraph}` : showPages && page ? ` · стр. ${page}` : ''}
    </button>
  );
}

function PartiesValue({ parties, onSelectSource, showPages }) {
  if (!Array.isArray(parties) || !parties.length) return <span className="missing-value">Не найдены</span>;
  return (
    <div className="party-list">
      {parties.map((party, index) => (
        <div className="party-row" key={index}>
          <div><strong>{party.name || 'Название не найдено'}</strong><span>{party.role || 'Роль не определена'}</span>{party.reason ? <span className="missing-value">{party.reason}</span> : null}</div>
          <span>{party.inn ? `ИНН ${party.inn}` : 'ИНН не найден'}</span>
          <div className="party-sources"><SourceButton showPages={showPages} manual={party.method === 'manual'} label="Название в документе" evidence={party.name_evidence} page={party.name_page_number} paragraph={party.paragraph_number} onSelect={onSelectSource} />
          {party.inn_evidence ? <SourceButton showPages={showPages} label="ИНН в документе" evidence={party.inn_evidence} page={party.inn_page_number} onSelect={onSelectSource} /> : null}</div>
        </div>
      ))}
    </div>
  );
}

export function FieldRow({ fieldKey, field, active, reviewed, onSelectSource, onCopy, onEdit, disabled, showPages }) {
  const evidence = getFieldEvidence(fieldKey, field);
  const page = getFieldPage(fieldKey, field);
  const needsReview = fieldNeedsReview(fieldKey, field);
  const value = getFieldValue(fieldKey, field);
  const hasValue = value !== null && value !== undefined && value !== '' && (!Array.isArray(value) || value.length > 0);
  return (
    <section id={`field-${fieldKey}`} className={`field-row${active ? ' is-active' : ''}${needsReview && !reviewed ? ' needs-review' : ''}`}>
      <div className="field-row-heading">
        <span>{fieldLabels[fieldKey] ?? fieldKey.replaceAll('_', ' ')}</span>
        {needsReview && !reviewed && hasValue ? <strong className="review-flag">Проверить</strong> : null}
      </div>
      {field?.reason && !(field.method === 'manual' && field.reason === 'Значение изменено вручную') ? <p className="field-review-reason">{field.reason}</p> : null}
      {field?.candidates?.map((candidate, index) => <div className="field-source" key={index}><span>{candidate.value}{candidate.currency ? ` ${candidate.currency}` : ''}</span><SourceButton showPages={showPages} evidence={candidate.evidence} page={candidate.page_number} paragraph={candidate.paragraph_number} onSelect={(source) => onSelectSource({ ...source, fieldKey })} /><blockquote>{candidate.evidence}</blockquote></div>)}
      <div className="field-row-value">
        {fieldKey === 'parties' ? <PartiesValue showPages={showPages} parties={value} onSelectSource={(source) => onSelectSource({ ...source, fieldKey })} /> : <span className={value === null || value === undefined || value === '' ? 'missing-value' : ''}>{formatFieldValue(fieldKey, field)}</span>}
      </div>
      <div className="field-tools">
      {fieldKey !== 'parties' && (hasValue || field?.method === 'manual') ? (
        <div className="field-source">
          <SourceButton showPages={showPages} manual={field?.method === 'manual'} evidence={evidence} page={page} paragraph={field?.paragraph_number} onSelect={(source) => onSelectSource({ ...source, fieldKey })} />
        </div>
      ) : null}
      <div className="field-actions">{fieldKey !== 'parties' && value != null && value !== '' ? <button className="copy-field" type="button" onClick={() => onCopy(formatFieldValue(fieldKey, field), fieldLabels[fieldKey])} aria-label={`Копировать: ${fieldLabels[fieldKey] ?? fieldKey}`}>Копировать</button> : null}
      <button className="text-button edit-field-button" type="button" disabled={disabled} onClick={() => onEdit(fieldKey)} aria-label={`Изменить: ${fieldLabels[fieldKey] ?? fieldKey}`}>Изменить</button></div>
      </div>
      {active && evidence ? <div className="field-source"><blockquote>{evidence}</blockquote></div> : null}
      {active && field?.method ? <details className="field-details"><summary>Сведения об источнике</summary><span>{field.method === 'manual' ? 'Исправлено вручную' : field.method === 'rule' ? 'Найдено по тексту документа' : 'Извлечено автоматически'}</span></details> : null}
    </section>
  );
}

export function MetadataEditor({ fields, onChange, onlyKey }) {
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
      {orderedEntries(fields).filter(([key]) => !onlyKey || key === onlyKey).map(([key, field]) => {
        if (key === 'parties') {
          const parties = fieldValueForEdit(key, field);
          return (
            <fieldset className="editor-fieldset" key={key}>
              <legend>{fieldLabels[key]}</legend>
              {!parties.length ? <p className="muted">Стороны не добавлены.</p> : null}
              {parties.map((party, index) => (
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
              <input id={`metadata-${key}`} type={key === 'contract_date' ? 'date' : 'text'} placeholder={key === 'term' ? 'Дата или условие окончания договора' : undefined} value={value ?? ''} onChange={(event) => onChange(updateFieldValue(fields, key, event.target.value))} />
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
