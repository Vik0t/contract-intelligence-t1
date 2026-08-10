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

function formatValue(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
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
  const [templateId, setTemplateId] = useState('1');
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
      <main className="page-shell">
        <section className="card auth-card">
          <p className="eyebrow">Contract Intelligence</p>
          <h1>{authMode === 'login' ? 'Sign in' : 'Create an account'}</h1>
          <p className="muted">Use the backend API running on port 8000.</p>

          <form className="form-stack" onSubmit={handleAuth}>
            <label>
              Username
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
                Email
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
              Password
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
              {loading ? 'Working…' : authMode === 'login' ? 'Sign in' : 'Register'}
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
            {authMode === 'login' ? 'Create a new account' : 'I already have an account'}
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="page-shell">
      <section className="card">
        <header className="topbar">
          <div>
            <p className="eyebrow">Contract Intelligence</p>
            <h1>Contract extraction</h1>
          </div>
          <div className="user-actions">
            <span className="muted">{user?.username}</span>
            <button className="secondary-button" onClick={logout}>Sign out</button>
          </div>
        </header>

        <form className="upload-form" onSubmit={handleUpload}>
          <label className="file-picker">
            <span>{file ? file.name : 'Choose a PDF or DOCX file'}</span>
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

          <label>
            Template ID
            <input
              type="number"
              min="1"
              value={templateId}
              onChange={(event) => setTemplateId(event.target.value)}
              required
            />
          </label>

          <button className="primary-button" disabled={!file || loading}>
            {loading ? 'Parsing and extracting…' : 'Upload contract'}
          </button>
        </form>

        {error && <p className="error">{error}</p>}

        {result && (
          <section className="result-section">
            <div className="success-banner">
              {result.upload.message} Document ID: {result.upload.document_id}.
            </div>
            <h2>Extracted metadata</h2>
            <div className="metadata-grid">
              {Object.entries(result.metadata).map(([key, value]) => (
                <div className="metadata-item" key={key}>
                  <span className="metadata-key">{key}</span>
                  <pre>{formatValue(value)}</pre>
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
