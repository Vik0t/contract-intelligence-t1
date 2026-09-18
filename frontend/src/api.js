export const API_PREFIX = '/api';

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') ?? '';
  return contentType.includes('application/json') ? response.json() : response.text();
}

export async function request(path, options = {}) {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(options.headers ?? {}),
    },
  });
  const data = await parseResponse(response);
  if (!response.ok) {
    const message = typeof data === 'object'
      ? data.detail || data.message || 'Не удалось выполнить запрос'
      : data || 'Не удалось выполнить запрос';
    throw new ApiError(message, response.status);
  }
  return data;
}

export async function requestBlob(path, token, signal) {
  const response = await fetch(`${API_PREFIX}${path}`, {
    headers: authHeaders(token),
    signal,
  });
  if (!response.ok) {
    const data = await parseResponse(response);
    const message = typeof data === 'object' ? data.detail || data.message : data;
    throw new ApiError(message || 'Не удалось загрузить файл', response.status);
  }
  return response.blob();
}

export function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

export function friendlyError(error) {
  if (error?.status === 401) return 'Сессия закончилась. Войдите снова.';
  if (error?.status === 404) return 'Документ или папка не найдены.';
  if (error?.status === 409) {
    if (error.message?.includes('prepared')) return 'Документ ещё подготавливается.';
    if (error.message?.includes('running')) return 'Анализ этого документа уже выполняется.';
    return 'Папка с таким названием уже существует.';
  }
  if (error?.status === 413) return 'Файл больше 50 МБ. Выберите документ меньшего размера.';
  if (error?.status >= 500) return 'Сервис временно недоступен. Попробуйте ещё раз.';
  return error?.message || 'Не удалось выполнить действие.';
}
