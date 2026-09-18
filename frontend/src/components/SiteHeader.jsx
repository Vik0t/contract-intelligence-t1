export default function SiteHeader({ user, onHome, onLogout }) {
  return (
    <header className="site-header">
      <button className="brand" type="button" onClick={onHome} aria-label="К списку договоров">
        <span className="brand-mark" aria-hidden="true">+I</span>
        <span className="brand-name">T1</span>
      </button>
      {user ? (
        <div className="header-account">
          <span className="header-product">Договоры</span>
          <span className="account-name">{user.username}</span>
          <button className="header-logout" type="button" onClick={onLogout}>Выйти</button>
        </div>
      ) : (
        <span className="header-product">Интеллектуальная проверка договоров</span>
      )}
    </header>
  );
}
