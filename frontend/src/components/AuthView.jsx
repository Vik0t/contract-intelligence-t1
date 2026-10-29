export default function AuthView({ authMode, authForm, loading, error, onChange, onSubmit, onToggle }) {
  const isLogin = authMode === 'login';
  return <section className="auth-layout" id="main-content" tabIndex={-1}>
    <div className="auth-intro"><h1>Анализ договоров</h1><p className="auth-lead">Реквизиты, сводка и риски рядом с оригиналом документа.</p><p className="auth-formats">PDF · DOCX · JPG · PNG</p></div>
    <div className="auth-panel"><h2>{isLogin ? 'Вход' : 'Регистрация'}</h2>
      <form className="form-stack" onSubmit={onSubmit} aria-busy={loading}>
        <div className="auth-field">
          <label htmlFor="auth-username">Имя пользователя</label>
          <input id="auth-username" aria-describedby={!isLogin ? 'username-hint' : undefined} maxLength={50} name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} value={authForm.username} onChange={onChange} minLength={3} required disabled={loading} />
          {!isLogin ? <span className="field-hint" id="username-hint">От 3 до 50 букв и цифр, без пробелов.</span> : null}
        </div>
        {!isLogin ? <div className="auth-field"><label htmlFor="auth-email">Электронная почта</label><input id="auth-email" name="email" type="email" autoComplete="email" autoCapitalize="none" value={authForm.email} onChange={onChange} required disabled={loading} /></div> : null}
        <div className="auth-field">
          <label htmlFor="auth-password">Пароль</label>
          <input id="auth-password" name="password" type="password" aria-describedby={!isLogin ? 'password-hint' : undefined} autoComplete={isLogin ? 'current-password' : 'new-password'} value={authForm.password} onChange={onChange} minLength={6} required disabled={loading} />
          {!isLogin ? <span className="field-hint" id="password-hint">От 6 символов: латиница, цифры, дефис и подчёркивание.</span> : null}
        </div>
        {error ? <p className="error" role="alert">{error}</p> : null}
        <button className="primary-button" disabled={loading}>{loading ? 'Подождите…' : isLogin ? 'Войти' : 'Зарегистрироваться'}</button>
      </form><button className="link-button auth-toggle" type="button" disabled={loading} onClick={onToggle}>{isLogin ? 'Создать учётную запись' : 'Уже есть учётная запись? Войти'}</button>
    </div>
  </section>;
}
