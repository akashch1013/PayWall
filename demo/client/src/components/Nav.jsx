import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext.jsx';
import { useToast } from './Toast.jsx';

const linkClass = ({ isActive }) => `nav-btn${isActive ? ' active' : ''}`;

export default function Nav() {
  const { user, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  async function onLogout() {
    try {
      await logout();
      toast('You have been logged out.');
      navigate('/');
    } catch (err) {
      toast(err.message);
    }
  }

  return (
    <header className="site-header">
      <nav className="nav" aria-label="Main">
        <Link to="/" className="logo" aria-label="ReWear home">
          Re<span>Wear</span>
        </Link>
        <div className="nav-links">
          <NavLink to="/" end className={linkClass}>
            Browse
          </NavLink>
          <NavLink to="/sell" className={({ isActive }) => `nav-btn sell${isActive ? ' active' : ''}`}>
            + Sell
          </NavLink>
          {user ? (
            <>
              <NavLink to="/dashboard" className={linkClass}>
                My listings
              </NavLink>
              <NavLink to="/orders" className={linkClass}>
                My orders
              </NavLink>
              <span className="nav-greeting">Hi, {user.name.split(' ')[0]}</span>
              <button type="button" className="nav-btn" onClick={onLogout}>
                Log out
              </button>
            </>
          ) : (
            <>
              <NavLink to="/login" className={linkClass}>
                Log in
              </NavLink>
              <NavLink to="/signup" className={({ isActive }) => `nav-btn primary${isActive ? ' active' : ''}`}>
                Sign up
              </NavLink>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}
