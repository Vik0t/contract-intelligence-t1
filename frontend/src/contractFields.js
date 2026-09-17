export const FIELD_ORDER = [
  'contract_number',
  'contract_date',
  'contract_type',
  'place',
  'term',
  'parties',
  'total_amount',
  'vat',
];

export const fieldLabels = {
  contract_number: 'Номер договора',
  contract_date: 'Дата договора',
  contract_type: 'Вид договора',
  place: 'Место заключения',
  term: 'Срок действия',
  parties: 'Стороны',
  total_amount: 'Общая сумма',
  vat: 'НДС',
};

const currencyLabels = { RUB: '₽', USD: '$', EUR: '€' };

export function cloneFields(fields) {
  return JSON.parse(JSON.stringify(fields ?? {}));
}

export function isStructuredField(field) {
  return Boolean(field && typeof field === 'object' && !Array.isArray(field));
}

export function fieldValueForEdit(key, field) {
  if (key === 'parties') return isStructuredField(field) ? field.value ?? [] : field ?? [];
  if (!isStructuredField(field)) return field ?? '';
  if (key === 'vat') return field.raw_value ?? '';
  return field.value ?? field.raw_value ?? field.name ?? '';
}

export function updateFieldValue(fields, key, value) {
  const next = cloneFields(fields);
  const current = next[key];
  if (isStructuredField(current)) {
    if (key === 'vat' || (!Object.hasOwn(current, 'value') && Object.hasOwn(current, 'raw_value'))) {
      current.raw_value = value;
    } else {
      current.value = value;
    }
  } else {
    next[key] = value;
  }
  return next;
}

export function getFieldValue(key, field) {
  if (key === 'parties') {
    return isStructuredField(field) ? field.value ?? [] : Array.isArray(field) ? field : [];
  }
  if (!isStructuredField(field)) return field;
  if (key === 'contract_type') return field.value ?? field.raw_value;
  if (key === 'contract_date') return field.value ?? field.raw_value;
  if (key === 'term') return field.value ?? field.raw_value;
  if (key === 'total_amount') return field.value ?? field.raw_value;
  if (key === 'vat') return field.raw_value ?? field.rate;
  return field.value ?? field.raw_value ?? field.name;
}

export function getFieldEvidence(key, field) {
  if (key === 'parties') return null;
  return isStructuredField(field) ? field.evidence ?? null : null;
}

export function getFieldPage(key, field) {
  if (key === 'parties') return null;
  return isStructuredField(field) ? field.page_number ?? null : null;
}

export function displayText(value, emptyLabel = 'Не найдено') {
  if (value === null || value === undefined || value === '') return emptyLabel;
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет';
  if (typeof value === 'number') return new Intl.NumberFormat('ru-RU').format(value);
  return String(value);
}

export function formatFieldValue(key, field) {
  const value = getFieldValue(key, field);
  if (key === 'contract_date' || key === 'term') {
    const date = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
      ? new Date(`${value}T00:00:00`)
      : null;
    if (date && !Number.isNaN(date.getTime())) {
      return new Intl.DateTimeFormat('ru-RU').format(date);
    }
  }
  if (key === 'total_amount' && isStructuredField(field)) {
    const amount = typeof field.value === 'number'
      ? new Intl.NumberFormat('ru-RU').format(field.value)
      : displayText(value);
    const currency = currencyLabels[field.currency] ?? field.currency ?? '';
    return `${amount}${currency ? ` ${currency}` : ''}`;
  }
  return displayText(value);
}

export function partyNeedsReview(party) {
  return !party?.name || !party?.inn || (!party?.name_evidence && !party?.inn_evidence);
}

export function fieldNeedsReview(key, field) {
  const value = getFieldValue(key, field);
  if (key === 'parties') {
    return !Array.isArray(value) || value.length < 2 || value.some(partyNeedsReview);
  }
  if (value === null || value === undefined || value === '') return true;
  if (!getFieldEvidence(key, field)) return true;
  if (key === 'vat' && isStructuredField(field)) {
    return field.mode === 'not_stated' || /при наличии|если применим/i.test(field.raw_value ?? '');
  }
  return false;
}

export function formatDate(value) {
  if (!value) return 'Дата не указана';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Дата не указана';
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  }).format(date);
}

export function fileExtension(filename) {
  return filename?.split('.').pop()?.toUpperCase() || 'FILE';
}

export function fieldsToPlainObject(fields) {
  const result = {};
  for (const key of FIELD_ORDER) {
    if (Object.hasOwn(fields ?? {}, key)) result[fieldLabels[key] ?? key] = getFieldValue(key, fields[key]);
  }
  return result;
}
