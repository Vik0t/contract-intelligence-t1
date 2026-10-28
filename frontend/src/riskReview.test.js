import assert from 'node:assert/strict';
import test from 'node:test';
import { companyForSide, riskCompanies, riskContractKind, sameRiskProfile } from './riskReview.js';

test('server key order does not hide a completed review for the same side', () => {
  const draft = { contract_type: 'supply', user_side: 'customer', jurisdiction: 'RU', scope_confirmed: true };
  const saved = { contract_type: 'supply', user_side: 'customer', scope_confirmed: true, jurisdiction: 'RU' };
  assert.equal(sameRiskProfile(draft, saved), true);
  assert.equal(sameRiskProfile({ ...draft, user_side: 'provider' }, saved), false);
  assert.equal(sameRiskProfile({ ...draft, contract_type: 'services' }, saved), false);
  assert.equal(sameRiskProfile({ ...draft, scope_confirmed: false }, saved), false);
});

test('company identity comes from extracted parties and maps to the existing risk profile', () => {
  const companies = riskCompanies({ parties: { value: [
    { name: 'ООО Альфа', role: 'Покупатель', canonical_role: 'Заказчик', inn: '1234567890' },
    { name: 'ООО Бета', role: 'Поставщик', canonical_role: 'Исполнитель' },
  ] } });
  assert.equal(companyForSide(companies, 'customer').name, 'ООО Альфа');
  assert.equal(companyForSide(companies, 'provider').name, 'ООО Бета');
  assert.equal(companies[0].inn, '1234567890');
  assert.ok(companies.every(company => company.selectable));
});

test('multiple companies on the same side cannot be presented as a review of one company', () => {
  const companies = riskCompanies({ parties: [
    { name: 'ООО Альфа', role: 'Заказчик' },
    { name: 'ООО Бета', role: 'Заказчик' },
    { name: 'ООО Гамма', role: 'Исполнитель' },
  ] });
  assert.equal(companyForSide(companies, 'customer'), undefined);
  assert.equal(companyForSide(companies, 'provider').name, 'ООО Гамма');
});

test('unknown roles and missing company names are never guessed', () => {
  assert.deepEqual(riskCompanies({}), []);
  const companies = riskCompanies({ parties: [{ name: '' }, { name: 'ООО Альфа', role: 'Участник' }] });
  assert.equal(companies.length, 1);
  assert.equal(companies[0].selectable, false);
  assert.equal(companyForSide(companies, 'customer'), undefined);
});

test('only an unambiguous supported contract kind is prefilled', () => {
  assert.equal(riskContractKind({ value: 'Договор поставки' }), 'supply');
  assert.equal(riskContractKind({ raw_value: 'Договор оказания услуг' }), 'services');
  assert.equal(riskContractKind({ value: 'Поставка и оказание услуг' }), '');
  assert.equal(riskContractKind({ value: 'Договор аренды' }), '');
  assert.equal(riskContractKind(null), '');
});
