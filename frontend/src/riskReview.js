export function sameRiskProfile(left, right) {
  return Boolean(left && right) && ['contract_type', 'user_side', 'jurisdiction', 'scope_confirmed'].every((key) => left[key] === right[key]);
}
