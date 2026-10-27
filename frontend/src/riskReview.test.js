import assert from 'node:assert/strict';
import test from 'node:test';
import { sameRiskProfile } from './riskReview.js';

test('server key order does not hide a completed review for the same side', () => {
  const draft = { contract_type: 'supply', user_side: 'customer', jurisdiction: 'RU', scope_confirmed: true };
  const saved = { contract_type: 'supply', user_side: 'customer', scope_confirmed: true, jurisdiction: 'RU' };
  assert.equal(sameRiskProfile(draft, saved), true);
  assert.equal(sameRiskProfile({ ...draft, user_side: 'provider' }, saved), false);
  assert.equal(sameRiskProfile({ ...draft, contract_type: 'services' }, saved), false);
  assert.equal(sameRiskProfile({ ...draft, scope_confirmed: false }, saved), false);
});
