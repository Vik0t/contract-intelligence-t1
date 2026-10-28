export const DOCUMENT_FILTERS = [
  ['all', 'Все'], ['pending', 'На проверку'], ['reviewed', 'Проверены'],
  ['processing', 'В обработке'], ['failed', 'С ошибками'],
];

export function documentStatus(document) {
  if (document.status === 'processing' || document.status === 'uploaded') return { label: 'Обрабатывается', tone: 'processing' };
  if (document.status === 'failed') return { label: 'Ошибка обработки', tone: 'error' };
  if (document.has_metadata && document.review_status === 'reviewed') return { label: 'Реквизиты проверены', tone: 'ready' };
  if (document.has_metadata) return { label: 'На проверку', tone: 'attention' };
  return { label: 'Нужен анализ', tone: 'neutral' };
}
