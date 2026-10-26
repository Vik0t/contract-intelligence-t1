import assert from 'node:assert/strict';
import test from 'node:test';
import { fieldsForSave, fieldsToPlainObject, getFieldValue, updateFieldValue } from './contractFields.js';

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
