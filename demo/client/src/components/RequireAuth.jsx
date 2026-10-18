import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../AuthContext.jsx';
import { Loading } from './StateViews.jsx';

export default function RequireAuth({ children }) {
  const { user, ready } = useAuth();
  const location = useLocation();
  if (!ready) return <Loading label="Checking your session…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location, reason: 'Please log in to continue.' }} />;
  return children;
}
