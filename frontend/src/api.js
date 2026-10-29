export const API_PREFIX = '/api';

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') ?? '';
  if (response.status === 204) return null;
  if (!contentType.includes('application/json') && !contentType.includes('+json')) {
    throw new ApiError('Сервис вернул неожиданный ответ. Повторите действие.', response.ok ? 502 : response.status);
  }
  try {
    return await response.json();
  } catch {
    throw new ApiError('Не удалось прочитать ответ сервиса. Повторите действие.', response.ok ? 502 : response.status);
  }
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
    let message = data && typeof data === 'object'
      ? data.detail || data.message || 'Не удалось выполнить запрос'
      : data || 'Не удалось выполнить запрос';
    if (Array.isArray(message)) {
      const fields = { username: 'имя пользователя: 3–50 букв и цифр без пробелов', email: 'электронную почту', password: 'пароль: от 6 знаков, латинские буквы, цифры, дефис или подчёркивание' };
      const hints = [...new Set(message.map((item) => fields[item.loc?.at(-1)]).filter(Boolean))];
      message = hints.length ? `Проверьте ${hints.join('; ')}.` : 'Проверьте введённые данные.';
    }
    if (typeof message !== 'string') message = 'Не удалось выполнить запрос. Проверьте введённые данные.';
    throw new ApiError(message, response.status);
  }
  return data;
}

export async function requestBlob(path, token, signal, cache = 'default') {
  const response = await fetch(`${API_PREFIX}${path}`, {
    headers: authHeaders(token),
    signal,
    cache,
  });
  if (!response.ok) {
    const data = await parseResponse(response);
    const message = data && typeof data === 'object' ? data.detail || data.message : data;
    throw new ApiError(typeof message === 'string' ? message : 'Не удалось загрузить файл', response.status);
  }
  return response.blob();
}

export function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

export function friendlyError(error) {
  if (error?.message === 'Username already exists') return 'Это имя пользователя уже занято.';
  if (error?.message === 'Email already exists') return 'Эта электронная почта уже зарегистрирована.';
  if (error?.message === 'Invalid username or password') return 'Неверное имя пользователя или пароль.';
  if (error?.status === 401) return 'Сессия закончилась. Войдите снова.';
  if (error?.status === 403) return 'Нет доступа к этому документу или действию.';
  if (error?.status === 404) return 'Документ или папка не найдены.';
  if (error?.status === 409) {
    if (/[А-Яа-яЁё]/.test(error.message ?? '')) return error.message;
    if (error.message?.includes('prepared')) return 'Документ ещё подготавливается.';
    if (error.message?.includes('running')) return 'Анализ этого документа уже выполняется.';
    if (error.message === 'Folder already exists') return 'Папка с таким названием уже существует.';
    return 'Данные изменились. Обновите список и повторите действие.';
  }
  if (error?.status === 429) return 'Слишком много запросов. Повторите действие немного позже.';
  if (error?.status === 413) return 'Файл больше 50 МБ. Выберите документ меньшего размера.';
  if (error?.status >= 500) return 'Сервис временно недоступен. Попробуйте ещё раз.';
  if (error instanceof TypeError) return 'Не удалось связаться с сервисом. Проверьте подключение и повторите действие.';
  return error?.message || 'Не удалось выполнить действие.';
}
