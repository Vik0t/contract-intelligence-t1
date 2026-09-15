export default function AuthView({ authMode, authForm, loading, error, onChange, onSubmit, onToggle }) {
  const isLogin = authMode === 'login';
  return (
    <section className="auth-layout">
      <div className="auth-intro">
        <p className="eyebrow">Т1 / Договоры</p>
        <h1>Договор под контролем</h1>
        <p className="auth-lead">
          Загрузите PDF или DOCX, получите ключевые условия и проверьте каждое значение по тексту документа.
        </p>
        <ol className="auth-steps">
          <li><span>01</span> Загружаете договор</li>
          <li><span>02</span> Проверяете поля и возможные риски</li>
          <li><span>03</span> Сохраняете готовые данные</li>
        </ol>
      </div>
      <div className="auth-panel">
        <p className="eyebrow">Рабочее пространство</p>
        <h2>{isLogin ? 'Войти' : 'Создать аккаунт'}</h2>
        <p className="muted">
          {isLogin ? 'Продолжите работу с вашими договорами.' : 'Создайте доступ к локальной библиотеке договоров.'}
        </p>
        <form className="form-stack" onSubmit={onSubmit}>
          <label>
            Имя пользователя
            <input name="username" autoComplete="username" value={authForm.username} onChange={onChange} minLength={3} required />
          </label>
          {!isLogin ? (
            <label>
              Электронная почта
              <input name="email" type="email" autoComplete="email" value={authForm.email} onChange={onChange} required />
            </label>
          ) : null}
          <label>
            Пароль
            <input name="password" type="password" autoComplete={isLogin ? 'current-password' : 'new-password'} value={authForm.password} onChange={onChange} minLength={6} required />
          </label>
          <button className="primary-button" disabled={loading}>
            {loading ? 'Подождите…' : isLogin ? 'Войти' : 'Создать аккаунт'}
          </button>
        </form>
        {error ? <p className="error" role="alert">{error}</p> : null}
        <button className="link-button auth-toggle" type="button" onClick={onToggle}>
          {isLogin ? 'Нет аккаунта? Создать' : 'Уже есть аккаунт? Войти'}
        </button>
      </div>
    </section>
  );
}
