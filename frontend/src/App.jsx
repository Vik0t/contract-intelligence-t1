import { useState } from 'react';
import './App.css';

const API_PREFIX = '/api';

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { 'Content-Type': 'application/json' }),
      ...(options.headers ?? {}),
    },
  });

  const contentType = response.headers.get('content-type') ?? '';
  const data = contentType.includes('application/json')
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message = typeof data === 'object'
      ? data.detail || data.message || 'Request failed'
      : data || 'Request failed';
    throw new ApiError(message, response.status);
  }

  return data;
}

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

const fieldLabels = {
  contract_number: 'Номер договора',
  contract_date: 'Дата договора',
  contract_type: 'Вид договора',
  place: 'Место заключения',
  term: 'Срок действия',
  parties: 'Стороны',
  total_amount: 'Общая сумма',
  vat: 'НДС',
};

const currencyLabels = {
  RUB: '₽',
  USD: '$',
  EUR: '€',
};

function displayText(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет';
  if (typeof value === 'number') {
    return new Intl.NumberFormat('ru-RU').format(value);
  }
  return String(value);
}

function renderParties(parties) {
  return (
    <ul className="party-list">
      {parties.map((party, index) => (
        <li className="party-row" key={`${party.inn ?? party.name ?? index}`}>
          <strong>{displayText(party.name)}</strong>
          <span>{displayText(party.role)}</span>
          <span className="party-inn">ИНН {displayText(party.inn)}</span>
        </li>
      ))}
    </ul>
  );
}

function renderNestedValue(value) {
  if (Array.isArray(value)) {
    if (value.every((item) => item && typeof item === 'object' && ('name' in item || 'role' in item || 'inn' in item))) {
      return renderParties(value);
    }

    return (
      <ul className="field-list">
        {value.map((item, index) => (
          <li key={index}>{renderNestedValue(item)}</li>
        ))}
      </ul>
    );
  }

  if (value && typeof value === 'object') {
    return (
      <dl className="field-details">
        {Object.entries(value).map(([key, nestedValue]) => (
          <div className="detail-row" key={key}>
            <dt>{key.replaceAll('_', ' ')}</dt>
            <dd>{renderNestedValue(nestedValue)}</dd>
          </div>
        ))}
      </dl>
    );
  }

  return displayText(value);
}

function renderFieldValue(field) {
  const isStructuredField = field && typeof field === 'object' && !Array.isArray(field);
  const value = isStructuredField
    ? field.raw_value ?? field.value ?? field.name
    : field;
  const currency = isStructuredField ? currencyLabels[field.currency] : null;

  return (
    <>
      <div className="field-value">
        {renderNestedValue(value)}
        {currency && <span className="field-currency"> {currency}</span>}
      </div>
      {isStructuredField && field.evidence && (
        <p className="field-evidence">{field.evidence}</p>
      )}
      {isStructuredField && field.page_number !== undefined && field.page_number !== null && (
        <p className="field-page">Страница {displayText(field.page_number)}</p>
      )}
    </>
  );
}

function SiteHeader() {
  return (
    <header className="site-header">
      <a className="brand" href="#top" aria-label="Т1 — анализ договоров">
        <span className="brand-mark">+I</span>
        <span className="brand-name">T1</span>
      </a>
    </header>
  );
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('contract_token'));
  const [user, setUser] = useState(() => {
    const savedUser = localStorage.getItem('contract_user');
    return savedUser ? JSON.parse(savedUser) : null;
  });
  const [authMode, setAuthMode] = useState('login');
  const [authForm, setAuthForm] = useState({
    username: '',
    email: '',
    password: '',
  });
  const [file, setFile] = useState(null);
  const templateId = '1';
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const updateAuthField = (event) => {
    const { name, value } = event.target;
    setAuthForm((current) => ({ ...current, [name]: value }));
  };

  const saveSession = (session) => {
    localStorage.setItem('contract_token', session.session_token);
    localStorage.setItem('contract_user', JSON.stringify(session.user));
    setToken(session.session_token);
    setUser(session.user);
  };

  const handleAuth = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError('');

    try {
      if (authMode === 'register') {
        await request('/auth/register', {
          method: 'POST',
          body: JSON.stringify(authForm),
        });
      }

      const session = await request('/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          username: authForm.username,
          password: authForm.password,
        }),
      });
      saveSession(session);
      setAuthForm({ username: '', email: '', password: '' });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    try {
      if (token) {
        await request('/auth/logout', {
          method: 'POST',
          body: JSON.stringify({ session_token: token }),
        });
      }
    } catch {
      // The local session is cleared even if the server is unavailable.
    }
    localStorage.removeItem('contract_token');
    localStorage.removeItem('contract_user');
    setToken(null);
    setUser(null);
    setResult(null);
  };

  const handleUpload = async (event) => {
    event.preventDefault();
    if (!file || !token) return;

    setLoading(true);
    setError('');
    setResult(null);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('template_id', templateId);

      const upload = await request('/documents', {
        method: 'POST',
        headers: authHeaders(token),
        body: formData,
      });

      const metadata = await request(`/documents/${upload.document_id}/metadata`, {
        method: 'POST',
        headers: authHeaders(token),
      });

      setResult({ upload, metadata: metadata.metadata?.fields ?? {} });
    } catch (requestError) {
      if (requestError.status === 401) {
        await logout();
      }
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <main className="page-shell" id="top">
        <SiteHeader />
        <section className="card auth-card">
          <p className="eyebrow">Т1 / Анализ договоров</p>
          <h1>{authMode === 'login' ? 'Войти' : 'Создать аккаунт'}</h1>
          <p className="muted">Войдите, чтобы загрузить договор и получить его реквизиты.</p>

          <form className="form-stack" onSubmit={handleAuth}>
            <label>
              Имя пользователя
              <input
                name="username"
                value={authForm.username}
                onChange={updateAuthField}
                minLength={3}
                required
              />
            </label>

            {authMode === 'register' && (
              <label>
                Электронная почта
                <input
                  name="email"
                  type="email"
                  value={authForm.email}
                  onChange={updateAuthField}
                  required
                />
              </label>
            )}

            <label>
              Пароль
              <input
                name="password"
                type="password"
                value={authForm.password}
                onChange={updateAuthField}
                minLength={6}
                required
              />
            </label>

            <button className="primary-button" disabled={loading}>
              {loading ? 'Подождите…' : authMode === 'login' ? 'Войти' : 'Зарегистрироваться'}
            </button>
          </form>

          {error && <p className="error">{error}</p>}

          <button
            className="link-button"
            onClick={() => {
              setAuthMode((mode) => (mode === 'login' ? 'register' : 'login'));
              setError('');
            }}
          >
            {authMode === 'login' ? 'Создать аккаунт' : 'У меня уже есть аккаунт'}
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="page-shell" id="top">
      <SiteHeader />
      <section className="card">
        <header className="topbar">
          <div>
            <p className="eyebrow">Т1 / Анализ договоров</p>
            <h1>Анализ договора</h1>
          </div>
          <div className="user-actions">
            <span className="muted">{user?.username}</span>
            <button className="secondary-button" onClick={logout}>Выйти</button>
          </div>
        </header>

        <form className="upload-form" onSubmit={handleUpload}>
          <label className="file-picker">
            <span>{file ? file.name : 'Выберите файл PDF или DOCX'}</span>
            <input
              type="file"
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setResult(null);
                setError('');
              }}
              required
            />
          </label>

          <button className="primary-button" disabled={!file || loading}>
            {loading ? 'Извлекаем данные…' : 'Загрузить договор'}
          </button>
        </form>

        {error && <p className="error">{error}</p>}

        {result && (
          <section className="result-section">
            <div className="success-banner">
              Данные договора извлечены
            </div>
            <h2>Реквизиты договора</h2>
            <div className="metadata-list">
              {Object.entries(result.metadata).map(([key, value]) => (
                <div className="metadata-row" key={key}>
                  <h3 className="metadata-key">{fieldLabels[key] ?? key}</h3>
                  <div className="metadata-content">{renderFieldValue(value)}</div>
                </div>
              ))}
            </div>
          </section>
        )}
      </section>
    </main>
  );
}

export default App;
