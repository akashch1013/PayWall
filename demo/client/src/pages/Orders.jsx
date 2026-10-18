import { Link } from 'react-router-dom';
import ItemImage from '../components/ItemImage.jsx';
import { EmptyState, ErrorState, Loading } from '../components/StateViews.jsx';
import { formatDate, formatPrice } from '../constants.js';
import { useApiData } from '../useApiData.js';

export default function Orders() {
  const { status, data, error, reload } = useApiData('/api/orders');
  const orders = data?.orders ?? [];

  return (
    <div className="section">
      <div className="section-header">
        <div>
          <h1 className="section-title">My orders</h1>
          <p className="section-sub">Demo orders only. No payments are processed on ReWear.</p>
        </div>
      </div>

      {status === 'loading' && <Loading label="Loading your orders…" />}
      {status === 'error' && <ErrorState message={error.message} onRetry={reload} />}
      {status === 'ready' && orders.length === 0 && (
        <EmptyState title="No orders yet" action={<Link to="/" className="btn btn-dark">Browse listings</Link>}>
          Items you order will appear here.
        </EmptyState>
      )}
      {status === 'ready' && orders.length > 0 && (
        <ul className="row-list">
          {orders.map((o) => (
            <li key={o.id} className="row-item">
              <ItemImage listing={o} className="row-thumb" />
              <div className="row-main">
                <Link to={`/listings/${o.listing}`} className="row-title">
                  {o.item.title}
                </Link>
                <div className="row-meta">
                  Sold by {o.seller?.name ?? 'a former member'} · Ordered {formatDate(o.createdAt)}
                </div>
                <div className="row-note">Demo order: no payment processed.</div>
              </div>
              <div className="row-price">{formatPrice(o.item.price)}</div>
              <span className="tag tag-available">Placed</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
