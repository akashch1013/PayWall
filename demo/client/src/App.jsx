import { useEffect } from 'react';
import { Link, Route, Routes, useLocation } from 'react-router-dom';
import Nav from './components/Nav.jsx';
import RequireAuth from './components/RequireAuth.jsx';
import { EmptyState } from './components/StateViews.jsx';
import Browse from './pages/Browse.jsx';
import ListingDetail from './pages/ListingDetail.jsx';
import { Login, Signup } from './pages/AuthPages.jsx';
import { EditListing, Sell } from './pages/SellPages.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Orders from './pages/Orders.jsx';

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    if (typeof window.scrollTo === 'function') window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

function NotFound() {
  return (
    <div className="page-narrow">
      <EmptyState title="Page not found" action={<Link to="/" className="btn btn-dark">Go to listings</Link>} />
    </div>
  );
}

const protect = (el) => <RequireAuth>{el}</RequireAuth>;

export default function App() {
  return (
    <>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <ScrollToTop />
      <Nav />
      <main id="main">
        <Routes>
          <Route path="/" element={<Browse />} />
          <Route path="/listings/:id" element={<ListingDetail />} />
          <Route path="/listings/:id/edit" element={protect(<EditListing />)} />
          <Route path="/sell" element={protect(<Sell />)} />
          <Route path="/dashboard" element={protect(<Dashboard />)} />
          <Route path="/orders" element={protect(<Orders />)} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="site-footer">ReWear demo · Orders are for demonstration only. No payments are processed.</footer>
    </>
  );
}
