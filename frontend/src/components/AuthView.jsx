export default function AuthView({ authMode, authForm, loading, error, onChange, onSubmit, onToggle }) {
  const isLogin = authMode === 'login';
  return <section className="auth-layout" id="main-content">
    <div className="auth-intro"><h1>Анализ договоров</h1><p className="auth-lead">Реквизиты, сводка и риски рядом с оригиналом документа.</p><p className="auth-formats">PDF · DOCX · JPG · PNG</p></div>
    <div className="auth-panel"><h2>{isLogin ? 'Вход' : 'Регистрация'}</h2>
      <form className="form-stack" onSubmit={onSubmit} aria-busy={loading}>
        <label>Имя пользователя<input aria-describedby={!isLogin ? "username-hint" : undefined} maxLength={50} name="username" autoComplete="username" value={authForm.username} onChange={onChange} minLength={3} required />{!isLogin ? <span className="field-hint" id="username-hint">От 3 до 50 букв и цифр, без пробелов.</span> : null}</label>
        {!isLogin ? <label>Электронная почта<input name="email" type="email" autoComplete="email" value={authForm.email} onChange={onChange} required /></label> : null}
        <label>Пароль<input name="password" type="password" autoComplete={isLogin ? 'current-password' : 'new-password'} value={authForm.password} onChange={onChange} minLength={6} required />{!isLogin ? <span className="field-hint">От 6 символов: латиница, цифры, дефис и подчёркивание.</span> : null}</label>
        {error ? <p className="error" role="alert">{error}</p> : null}
        <button className="primary-button" disabled={loading}>{loading ? 'Подождите…' : isLogin ? 'Войти' : 'Зарегистрироваться'}</button>
      </form><button className="link-button auth-toggle" type="button" onClick={onToggle}>{isLogin ? 'Создать учётную запись' : 'Уже есть учётная запись? Войти'}</button>
    </div>
  </section>;
}
