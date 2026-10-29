import assert from 'node:assert/strict';
import test from 'node:test';
import { request } from './api.js';

test('form validation errors explain the invalid field instead of showing an object', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail: [
    { loc: ['body', 'username'], msg: 'Value error, Username can not contain any special characters or spaces' },
  ] }), { status: 422, headers: { 'content-type': 'application/json' } }));
  await assert.rejects(() => request('/auth/register'), /имя пользователя: 3–50 букв и цифр без пробелов/);
});

test('HTML proxy errors never appear as a successful API result', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response('<html>Gateway</html>', { headers: { 'content-type': 'text/html' } }));
  await assert.rejects(() => request('/documents'), error => error.status === 502);
});

test('invalid JSON keeps the HTTP status for session recovery', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response('{', { status: 401, headers: { 'content-type': 'application/json' } }));
  await assert.rejects(() => request('/documents'), error => error.status === 401);
});

test('structured backend details do not become object text', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({detail:{reason:'invalid'}}), { status: 400, headers: { 'content-type': 'application/json' } }));
  await assert.rejects(() => request('/documents'), error => !error.message.includes('[object Object]'));
});

test('offline and forbidden errors give the operator a useful next step', async () => {
  const {friendlyError,ApiError} = await import('./api.js');
  assert.match(friendlyError(new TypeError('Failed to fetch')), /Проверьте подключение/);
  assert.match(friendlyError(new ApiError('Access denied',403)), /Нет доступа/);
});

test('document conflicts are not described as duplicate folders', async () => {
  const {friendlyError,ApiError}=await import('./api.js');
  assert.equal(friendlyError(new ApiError('Сначала дождитесь извлечения данных',409)),'Сначала дождитесь извлечения данных');
  assert.match(friendlyError(new ApiError('Folder already exists',409)), /Папка/);
  assert.match(friendlyError(new ApiError('Conflict',409)), /Данные изменились/);
});
