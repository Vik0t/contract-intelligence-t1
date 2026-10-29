import assert from 'node:assert/strict';
import test from 'node:test';
import { fieldNeedsReview, fieldsForSave, fieldsToPlainObject, getFieldValue, updateFieldValue } from './contractFields.js';

test('operator amount with Russian decimal separator is exported as a number', () => {
  const original = { total_amount: { value: '100 000,50', currency: 'RUB' } };
  const saved = fieldsForSave(original);
  assert.equal(saved.total_amount.value, 100000.5);
  assert.equal(saved.total_amount.currency, 'RUB');
  assert.equal(original.total_amount.value, '100 000,50');
});

test('zero amount and zero VAT remain valid numeric values', () => {
  const saved = fieldsForSave({ total_amount: { value: '0' }, vat: { rate: '0', mode: 'included' } });
  assert.equal(saved.total_amount.value, 0);
  assert.equal(saved.vat.rate, 0);
});

test('invalid numeric edits cannot be silently saved as JSON null', () => {
  assert.throws(() => fieldsForSave({ total_amount: { value: '1e999' } }), /Сумма/);
  assert.throws(() => fieldsForSave({ vat: { rate: '101' } }), /от 0 до 100/);
});

test('edited values no longer claim that an old citation confirms them', () => {
  const fields = { contract_number: { value: '17', evidence: 'Договор №17', page_number: 1 } };
  const updated = updateFieldValue(fields, 'contract_number', '18');
  assert.equal(updated.contract_number.evidence, null);
  assert.equal(updated.contract_number.page_number, null);
  assert.equal(fields.contract_number.evidence, 'Договор №17');
});

test('VAT edits are readable even without original source wording', () => {
  assert.equal(getFieldValue('vat', { mode: 'not_subject', rate: null }), 'Не облагается НДС');
  assert.equal(getFieldValue('vat', { mode: 'excluded', rate: 20 }), 'НДС сверх суммы 20%');
});

test('copy and JSON export preserve the currency of a contract amount', () => {
  const result = fieldsToPlainObject({ total_amount: { value: 100000, currency: 'USD' } });
  assert.equal(result['Общая сумма'], 100000);
  assert.equal(result['Валюта'], 'USD');
});

test('currency edits normalize codes and reject unreadable symbols', () => {
  assert.equal(fieldsForSave({ total_amount: { value: 100, currency: ' usd ' } }).total_amount.currency, 'USD');
  assert.throws(() => fieldsForSave({ total_amount: { value: 100, currency: '$' } }), /код валюты/);
});

test('PMI consistency failures and explicit backend statuses remain visible', () => {
  assert.equal(fieldNeedsReview('total_amount', { value: 0, evidence: '0 рублей' }), true);
  assert.equal(fieldNeedsReview('total_amount', { value: -100, evidence: '-100 рублей' }), true);
  assert.equal(fieldNeedsReview('total_amount', { value: 100, evidence: '100', currency: null, status: 'found' }), false);
  assert.equal(fieldNeedsReview('contract_date', { value: '2099-01-01', evidence: '01.01.2099' }), true);
  assert.equal(fieldNeedsReview('total_amount', { value: 100, evidence: '100 рублей', status: 'needs_review', reason: 'Конфликт' }), true);
});

test('missing amount does not show a currency as if an amount was extracted', async () => {
  const {formatFieldValue}=await import('./contractFields.js');
  assert.equal(formatFieldValue('total_amount',{value:null,currency:'RUB'}),'Не найдено');
  assert.equal(formatFieldValue('total_amount',{value:0,currency:'RUB'}),'0 ₽');
});

test('invalid calendar dates are not silently changed to another day', async () => {
  const {formatFieldValue}=await import('./contractFields.js');
  assert.equal(formatFieldValue('contract_date',{value:'2026-02-31'}),'2026-02-31');
  assert.equal(formatFieldValue('contract_date',{value:'2024-02-29'}),'29.02.2024');
});

test('export includes visible extra fields but excludes internal provenance', () => {
  assert.deepEqual(fieldsToPlainObject({custom_reference:{value:'A-5'},_provenance:{backend:'fixture'}}),{custom_reference:'A-5'});
});

test('operator can replace an end date with a contractual condition', () => {
  const edited=updateFieldValue({term:{value:'2026-12-31',semantic_type:'end_date',evidence:'до 31.12.2026'}},'term','До полного исполнения обязательств');
  const saved=fieldsForSave(edited);
  assert.equal(saved.term.value,null);
  assert.equal(saved.term.raw_value,'До полного исполнения обязательств');
  assert.equal(saved.term.semantic_type,null);
  assert.equal(saved.term.evidence,null);
});

test('operator end dates normalize Russian notation and reject impossible days', () => {
  const edit=value=>updateFieldValue({term:{value:'2026-12-31'}},'term',value);
  assert.equal(fieldsForSave(edit('31.12.2027')).term.value,'2027-12-31');
  assert.equal(fieldsForSave(edit('2027-12-31')).term.value,'2027-12-31');
  assert.throws(()=>fieldsForSave(edit('31.02.2027')),/проверьте дату/);
});
