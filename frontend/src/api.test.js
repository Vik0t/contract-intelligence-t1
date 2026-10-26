import assert from 'node:assert/strict';
import test from 'node:test';
import { request } from './api.js';

test('form validation errors explain the invalid field instead of showing an object', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail: [
    { loc: ['body', 'username'], msg: 'Value error, Username can not contain any special characters or spaces' },
  ] }), { status: 422, headers: { 'content-type': 'application/json' } }));
  await assert.rejects(() => request('/auth/register'), /имя пользователя: 3–50 букв и цифр без пробелов/);
});
