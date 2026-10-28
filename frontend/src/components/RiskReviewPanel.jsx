import { useState } from 'react';
import { companyForSide, riskCompanies, riskContractKind, sameRiskProfile } from '../riskReview.js';

const kinds = { supply: 'Поставка', services: 'Услуги' };
const sides = (kind) => kind === 'supply' ? { customer: 'Покупатель', provider: 'Поставщик' } : { customer: 'Заказчик', provider: 'Исполнитель' };
const statuses = { risk: 'Есть замечание', mitigated: 'Учтено защитное условие', not_found: 'Основания не найдены', needs_context: 'Нужно уточнение' };

function SourcePassages({ items, onSelectSource, label, showPages }) {
  if (!items?.length) return null;
  return <div className="risk-passages"><strong>{label}</strong>{items.map((item) => <div key={item.id}><blockquote>{item.evidence.replace(/\s+/g, ' ').trim()}</blockquote><button type="button" className="source-button" onClick={() => onSelectSource(item)}>Показать в документе{showPages && item.page ? ` · стр. ${item.page}` : ''}</button></div>)}</div>;
}

export default function RiskReviewPanel({ fields, review, legacyRisks, onRun, onSelectSource, onOpenFields, showPages = true }) {
  const companies = riskCompanies(fields);
  const [companyKey, setCompanyKey] = useState(() => companyForSide(riskCompanies(fields), review?.profile?.user_side)?.key ?? '');
  const [kindOverride, setKindOverride] = useState(review?.profile?.contract_type ?? null);
  const [kindOpen, setKindOpen] = useState(false);
  const kind = kindOverride ?? riskContractKind(fields.contract_type);
  const company = companies.find(item => item.key === companyKey);
  const savedCompany = companyForSide(companies, review?.profile?.user_side);
  // This selects the existing, bounded server catalog. The server verifies the
  // actual document scope; the operator is not asked to attest legal facts.
  const profile = { contract_type: kind, user_side: company?.selectable ? company.side : '', jurisdiction: 'RU', scope_confirmed: true };
  const [running, setRunning] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const busy = running || review?.status === 'running';
  const [error, setError] = useState('');
  const dirty = review?.profile && !sameRiskProfile(profile, review.profile);
  const completed = review?.status === 'complete' && !dirty;
  const findings = completed ? review.findings ?? [] : [];
  const unresolved = completed ? (review.checks ?? []).filter((item) => item.status === 'needs_context') : [];
  const canRun = Boolean(kind && company?.selectable);
  const restore = () => {
    setCompanyKey(savedCompany?.key ?? '');
    setKindOverride(review.profile.contract_type);
    setError('');
    setProfileOpen(false);
  };
  const run = async (event) => {
    event.preventDefault();
    if (!canRun || busy) return;
    setRunning(true); setError('');
    try { await onRun(profile); setProfileOpen(false); } catch (requestError) { setError(requestError.message || 'Не удалось проверить договор. Повторите попытку.'); }
    finally { setRunning(false); }
  };
  return <div className="risks-panel">
    {completed && !busy ? <div className="risk-review-heading"><div><span className="risk-context-label">Риски для компании</span><strong>{savedCompany?.name ?? sides(review.profile.contract_type)[review.profile.user_side]}</strong><span className="risk-context-label">{savedCompany?.role || sides(review.profile.contract_type)[review.profile.user_side]} · {kinds[review.profile.contract_type]}</span></div><button type="button" className="source-button" aria-expanded={profileOpen} aria-controls="risk-profile" onClick={() => setProfileOpen(value => !value)}>{profileOpen ? 'Закрыть выбор' : 'Сменить компанию'}</button></div> : null}
    <form id="risk-profile" className="risk-profile" hidden={completed && !profileOpen && !busy} onSubmit={run}>
      <fieldset disabled={busy}>
        <legend>Какую компанию вы представляете?</legend>
        <div className="risk-company-list">{companies.map(item => <label className={`risk-company-choice${item.key === companyKey ? ' is-selected' : ''}`} key={item.key}>
          <input type="radio" name="risk-company" value={item.key} checked={companyKey === item.key} onChange={() => { setCompanyKey(item.key); setError(''); }} />
          <span><strong>{item.name}</strong><span>{item.role || 'Роль не определена'}{item.inn ? ` · ИНН ${item.inn}` : ''}</span>{!item.selectable ? <span className="risk-company-issue">{item.side ? 'Роль относится к нескольким компаниям — уточните реквизиты' : 'Сначала уточните роль в реквизитах'}</span> : null}</span>
        </label>)}</div>
        {!companies.length ? <p className="panel-note">Стороны договора не определены. Уточните названия и роли в реквизитах.</p> : null}
        {onOpenFields ? <button type="button" className="source-button risk-edit-parties" onClick={onOpenFields}>Исправить компании в реквизитах</button> : null}
        {kind && !kindOpen ? <div className="risk-detected-kind"><span>Тип договора: {kinds[kind]}</span><button type="button" className="source-button" onClick={() => setKindOpen(true)}>Изменить</button></div> : <label htmlFor="risk-contract-kind">Уточните тип договора<select id="risk-contract-kind" required value={kind} onChange={event => { setKindOverride(event.target.value); setError(''); }}><option value="">Выберите тип</option>{Object.entries(kinds).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>}
        <button type="submit" className="primary-button" disabled={!canRun || busy}>{busy ? 'Проверяем условия договора…' : review?.profile && !dirty ? 'Проверить повторно' : 'Найти риски для компании'}</button>
        <details className="risk-scope"><summary>Что проверяется</summary><p>Условия оплаты, ответственности, приёмки и прекращения договора с учётом интересов выбранной компании. Проверка предназначена для поставки и услуг между организациями или ИП по праву РФ; потребительские договоры и закупки по 44-ФЗ/223-ФЗ требуют другой проверки.</p></details>
      </fieldset>
    </form>
    {busy ? <p role="status" className="panel-note">Проверяем условия всего договора для {company?.name || 'выбранной компании'}. Можно вернуться к списку — результат сохранится.</p> : null}
    {error ? <p role="alert" className="insights-error">{error}</p> : null}
    {!running && !dirty && review?.error ? <p role="alert" className="insights-error">{review.error}</p> : null}
    {dirty && review?.status === 'complete' ? <div className="empty-panel"><strong>Для выбранной компании нужна новая проверка</strong><span>Сохранённый результат относится к {savedCompany?.name ?? sides(review.profile.contract_type)[review.profile.user_side]}.</span><button type="button" className="source-button" onClick={restore}>Вернуться к сохранённому результату</button></div> : null}
    {!review && legacyRisks?.length ? <p className="panel-note">Предыдущие замечания не привязаны к компании. Выберите свою компанию и запустите проверку.</p> : null}
    {completed && !busy ? <>
      <div className="risk-review-context"><strong>{findings.length ? `Замечаний: ${findings.length}` : 'Замечаний не найдено'}{unresolved.length ? ` · Нужно уточнить: ${unresolved.length}` : ''}</strong><span>{review.coverage.chunks_scanned === review.coverage.chunks_total ? 'Обработан весь текст договора' : 'Текст обработан частично'}</span></div>
      <p className="risk-disclaimer">Замечания требуют проверки юристом.</p>
      {findings.length ? findings.map((risk) => <section className="risk-row" key={risk.rule_id}>
        <span className="risk-level">{risk.category === 'legal_review' ? 'Проверить с юристом' : 'Коммерческий риск'}</span>
        <h3>{risk.title}</h3><p>{risk.body}</p>
        <div className="risk-recommendation"><strong>Что согласовать</strong><p>{risk.recommendation}</p></div>
        {risk.supporting_clauses?.[0] ? <button type="button" className="source-button" onClick={() => onSelectSource(risk.supporting_clauses[0])}>Открыть условие в документе{showPages && risk.supporting_clauses[0].page ? ` · стр. ${risk.supporting_clauses[0].page}` : ''}</button> : null}
        <details className="risk-basis"><summary>Цитаты и связанные условия</summary><SourcePassages showPages={showPages} items={risk.supporting_clauses} label="Основание замечания" onSelectSource={onSelectSource} /><SourcePassages showPages={showPages} items={risk.related_clauses} label="Связанные условия и исключения" onSelectSource={onSelectSource} /></details>
        <details className="risk-basis"><summary>Основание замечания</summary><p>{risk.basis.criterion}</p><p>{risk.basis.caveats}</p><p>Нормы для проверки применимости; сами по себе не доказывают нарушение:</p><ul>{risk.basis.legal_references.map((source) => <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}{source.articles ? ` · ${source.articles}` : ''}</a></li>)}</ul></details>
      </section>) : <div className="empty-panel"><strong>По выполненным проверкам замечания не найдены</strong><span>{unresolved.length ? 'Остаются вопросы, требующие уточнения.' : 'Это не подтверждение юридической безопасности договора.'}</span></div>}
      {unresolved.length ? <section className="risk-questions"><h3>Нужно уточнить</h3>{unresolved.map((item) => <div key={item.rule_id}><strong>{item.title}</strong><p>{item.body}</p><SourcePassages showPages={showPages} items={item.evidence} label="Источник вопроса" onSelectSource={onSelectSource} /></div>)}</section> : null}
      <details className="risk-basis"><summary>Все проверки и ограничения</summary><ul>{review.checks.map((item) => <li key={item.rule_id}><strong>{item.title}: {statuses[item.status]}</strong>{item.body ? <p>{item.body}</p> : null}{item.status === 'mitigated' ? <SourcePassages showPages={showPages} items={[...item.evidence, ...item.related_clauses]} label="Учтённые условия" onSelectSource={onSelectSource} /> : null}</li>)}</ul><p>Каталог {review.catalog_version}; источники сверены {review.catalog_checked_at}. Независимая юридическая валидация каталога ещё не завершена. Полнота распознавания и выводов модели не гарантирована. Редакцию нормы на дату договора и специальные правила проверяет юрист.</p></details>
    </> : null}
  </div>;
}
