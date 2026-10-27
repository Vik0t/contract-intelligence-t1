import { useState } from 'react';
import { formatFieldValue } from '../contractFields.js';
import { sameRiskProfile } from '../riskReview.js';

const kinds = { supply: 'Поставка', services: 'Услуги' };
const sides = (kind) => kind === 'supply' ? { customer: 'Покупатель', provider: 'Поставщик' } : { customer: 'Заказчик', provider: 'Исполнитель' };
const statuses = { risk: 'Есть замечание', mitigated: 'Учтено защитное условие', not_found: 'Основания не найдены', needs_context: 'Нужно уточнение' };

function SourcePassages({ items, onSelectSource, label }) {
  if (!items?.length) return null;
  return <div className="risk-passages"><strong>{label}</strong>{items.map((item) => <div key={item.id}><blockquote>{item.evidence.replace(/\s+/g, ' ').trim()}</blockquote><button type="button" className="source-button" onClick={() => onSelectSource(item)}>Показать в документе{item.page ? ` · стр. ${item.page}` : ''}</button></div>)}</div>;
}

export default function RiskReviewPanel({ fields, review, legacyRisks, onRun, onSelectSource }) {
  const suggestedType = /постав/i.test(formatFieldValue('contract_type', fields.contract_type)) ? 'supply' : /услуг/i.test(formatFieldValue('contract_type', fields.contract_type)) ? 'services' : '';
  const [profile, setProfile] = useState(review?.profile ?? { contract_type: suggestedType, user_side: '', jurisdiction: 'RU', scope_confirmed: false });
  const [running, setRunning] = useState(false);
  const busy = running || review?.status === 'running';
  const [error, setError] = useState('');
  const dirty = review?.profile && !sameRiskProfile(profile, review.profile);
  const completed = review?.status === 'complete' && !dirty;
  const findings = completed ? review.findings : [];
  const unresolved = completed ? review.checks.filter((item) => item.status === 'needs_context') : [];
  const update = (name, value) => { setProfile((current) => ({ ...current, [name]: value })); setError(''); };
  const run = async (event) => {
    event.preventDefault();
    setRunning(true); setError('');
    try { await onRun(profile); } catch (requestError) { setError(requestError.message || 'Не удалось проверить договор. Повторите попытку.'); }
    finally { setRunning(false); }
  };
  return <div className="risks-panel">
    <p className="panel-kicker">Проверка условий договора</p>
    <form className="risk-profile" onSubmit={run}>
      <fieldset disabled={busy}>
        <label htmlFor="risk-contract-kind">Тип договора<select id="risk-contract-kind" required value={profile.contract_type} onChange={(event) => update('contract_type', event.target.value)}><option value="">Выберите тип</option>{Object.entries(kinds).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
        <label htmlFor="risk-user-side">Наша сторона<select id="risk-user-side" required value={profile.user_side} onChange={(event) => update('user_side', event.target.value)}><option value="">Чьи интересы проверяем?</option>{Object.entries(sides(profile.contract_type)).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
        <label className="risk-profile-confirmation"><input type="checkbox" required checked={profile.scope_confirmed} onChange={(event) => update('scope_confirmed', event.target.checked)} /><span>Договор между организациями или ИП по праву РФ, без потребительских отношений и закупок по 44-ФЗ/223-ФЗ.</span></label>
        <button type="submit" className="primary-button" disabled={!profile.contract_type || !profile.user_side || !profile.scope_confirmed}>{busy ? 'Проверяем весь договор…' : completed ? 'Повторить проверку' : 'Проверить договор'}</button>
      </fieldset>
    </form>
    {busy ? <p role="status" className="panel-note">Собираем условия со всех страниц и сопоставляем ограничения и исключения. Можно вернуться к списку — результат сохранится.</p> : null}
    {error ? <p role="alert" className="insights-error">{error}</p> : null}
    {!running && !dirty && review?.error ? <p role="alert" className="insights-error">{review.error}</p> : null}
    {dirty ? <div className="empty-panel"><strong>Параметры проверки изменены</strong><span>Запустите проверку для выбранной стороны.</span><button type="button" className="source-button" onClick={() => setProfile(review.profile)}>Вернуть параметры сохранённого результата</button></div> : null}
    {!review && legacyRisks?.length ? <p className="panel-note">Предыдущие замечания получены без выбора стороны. Выполните новую проверку по каталогу.</p> : null}
    {!review && !running ? <p className="panel-note">Система проверит условия по каталогу для выбранной стороны. Незаполненные поля проверяются отдельно во вкладке «Поля».</p> : null}
    {completed && !busy ? <>
      <div className="risk-review-context"><strong>{kinds[review.profile.contract_type]} · {sides(review.profile.contract_type)[review.profile.user_side]}</strong><span>Обработано фрагментов: {review.coverage.chunks_scanned} из {review.coverage.chunks_total}. Выполнено проверок: {review.coverage.rules_checked}. Связанные условия сопоставлены.</span></div>
      <p className="risk-disclaimer">Предварительные замечания требуют проверки юристом. Каталог первой версии ещё не прошёл независимую юридическую валидацию. Подтверждение полей оператором не подтверждает правовую оценку.</p>
      {findings.length ? findings.map((risk) => <section className="risk-row" key={risk.rule_id}>
        <span className="risk-level">{risk.category === 'legal_review' ? 'Проверить с юристом' : 'Коммерческий риск'}</span>
        <h3>{risk.title}</h3><p>{risk.body}</p>
        <SourcePassages items={risk.supporting_clauses} label="Условия договора" onSelectSource={onSelectSource} />
        <SourcePassages items={risk.related_clauses} label="Связанные условия и исключения" onSelectSource={onSelectSource} />
        <div className="risk-recommendation"><strong>Что согласовать или проверить</strong><p>{risk.recommendation}</p></div>
        <details className="risk-basis"><summary>Основание замечания</summary><p>{risk.basis.criterion}</p><p>{risk.basis.caveats}</p><p>Нормы для проверки применимости; сами по себе не доказывают нарушение:</p><ul>{risk.basis.legal_references.map((source) => <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}{source.articles ? ` · ${source.articles}` : ''}</a></li>)}</ul></details>
      </section>) : <div className="empty-panel"><strong>По выполненным проверкам замечания не найдены</strong><span>{unresolved.length ? 'Остаются вопросы, требующие уточнения.' : 'Это не подтверждение юридической безопасности договора.'}</span></div>}
      {unresolved.length ? <section className="risk-questions"><h3>Нужно уточнить</h3>{unresolved.map((item) => <div key={item.rule_id}><strong>{item.title}</strong><p>{item.body}</p><SourcePassages items={item.evidence} label="Источник вопроса" onSelectSource={onSelectSource} /></div>)}</section> : null}
      <details className="risk-basis"><summary>Все проверки и ограничения</summary><ul>{review.checks.map((item) => <li key={item.rule_id}><strong>{item.title}: {statuses[item.status]}</strong>{item.body ? <p>{item.body}</p> : null}{item.status === 'mitigated' ? <SourcePassages items={[...item.evidence, ...item.related_clauses]} label="Учтённые условия" onSelectSource={onSelectSource} /> : null}</li>)}</ul><p>Каталог {review.catalog_version}; источники сверены {review.catalog_checked_at}. Полнота распознавания и выводов модели не гарантирована. Редакцию нормы на дату договора и специальные правила проверяет юрист.</p></details>
    </> : null}
  </div>;
}
