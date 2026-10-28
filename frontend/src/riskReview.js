import { getFieldValue } from './contractFields.js';

export function sameRiskProfile(left, right) {
  return Boolean(left && right) && ['contract_type', 'user_side', 'jurisdiction', 'scope_confirmed'].every((key) => left[key] === right[key]);
}

export function riskContractKind(field) {
  const value = String(getFieldValue('contract_type', field) ?? '').toLocaleLowerCase('ru');
  const supply = /поставк|^supply$/.test(value);
  const services = /услуг|^services$/.test(value);
  return supply !== services ? (supply ? 'supply' : 'services') : '';
}

export function riskCompanies(fields) {
  const parties = getFieldValue('parties', fields?.parties);
  if (!Array.isArray(parties)) return [];
  const result = parties.filter(party => typeof party?.name === 'string' && party.name.trim()).map((party, index) => {
    const role = String(party.canonical_role || party.role || '').trim().toLocaleLowerCase('ru');
    const side = ['заказчик', 'покупатель', 'customer'].includes(role) ? 'customer'
      : ['исполнитель', 'поставщик', 'provider'].includes(role) ? 'provider' : '';
    return { key: String(index), name: party.name.trim(), role: party.role || '', inn: party.inn || '', side };
  });
  return result.map(company => ({ ...company, selectable: Boolean(company.side) && result.filter(other => other.side === company.side).length === 1 }));
}

export function companyForSide(companies, side) {
  return companies.find(company => company.side === side && company.selectable);
}
