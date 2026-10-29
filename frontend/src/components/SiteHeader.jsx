import logo from '../assets/t1-logo.svg';

export default function SiteHeader({ user, onHome, onLogout }) {
  return <header className="site-header">
    <div className="header-identity">{onHome ? <button className="brand" type="button" onClick={onHome} aria-label="Т1 — к списку договоров"><img src={logo} alt="Т1" width="82" height="32" /></button> : <span className="brand"><img src={logo} alt="Т1" width="82" height="32" /></span>}<span className="header-divider" aria-hidden="true" /><span className="header-product">Анализ договоров</span></div>
    {user ? <div className="header-account"><span className="account-name">{user.username}</span><button className="header-logout" type="button" onClick={onLogout}>Выйти</button></div> : null}
  </header>;
}
