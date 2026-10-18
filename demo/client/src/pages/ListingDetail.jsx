import { useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api.js';
import { useAuth } from '../AuthContext.jsx';
import ConfirmDialog from '../components/ConfirmDialog.jsx';
import ItemImage from '../components/ItemImage.jsx';
import { EmptyState, ErrorState, Loading } from '../components/StateViews.jsx';
import { useToast } from '../components/Toast.jsx';
import { categoryLabel, conditionLabel, formatDate, formatPrice } from '../constants.js';
import { useApiData } from '../useApiData.js';

export default function ListingDetail() {
  const { id } = useParams();
  const { user, ready } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const { status, data, error, reload, setData } = useApiData(`/api/listings/${id}`);

  const [dialog, setDialog] = useState(null); // 'order' | 'delete' | null
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState('');
  const [order, setOrder] = useState(null);

  if (status === 'loading') return <Loading label="Loading item…" />;
  if (status === 'error') {
    if (error.status === 404) {
      return (
        <div className="page-narrow">
          <EmptyState title="Item not found" action={<Link to="/" className="btn btn-outline">Back to listings</Link>}>
            It may have been removed by the seller.
          </EmptyState>
        </div>
      );
    }
    return (
      <div className="page-narrow">
        <ErrorState message={error.message} onRetry={reload} />
      </div>
    );
  }

  const listing = data.listing;
  const isOwner = user && listing.seller?.id === user.id;
  const sold = listing.status === 'sold';

  function openDialog(kind) {
    setDialogError('');
    setDialog(kind);
  }

  async function placeOrder() {
    setBusy(true);
    setDialogError('');
    try {
      const res = await api('/api/orders', { method: 'POST', body: { listingId: listing.id } });
      setOrder(res.order);
      setData((d) => ({ listing: { ...d.listing, status: 'sold' } }));
      setDialog(null);
    } catch (err) {
      setDialogError(err.message);
      if (err.status === 409) setData((d) => ({ listing: { ...d.listing, status: 'sold' } }));
    } finally {
      setBusy(false);
    }
  }

  async function deleteListing() {
    setBusy(true);
    setDialogError('');
    try {
      await api(`/api/listings/${listing.id}`, { method: 'DELETE' });
      toast('Listing deleted.');
      navigate('/dashboard');
    } catch (err) {
      setDialogError(err.message);
      setBusy(false);
    }
  }

  let action;
  if (isOwner) {
    action = sold ? (
      <p className="alert alert-info">This item has sold. Sold items stay in order history and can't be edited.</p>
    ) : (
      <div className="detail-actions">
        <Link to={`/listings/${listing.id}/edit`} className="btn btn-dark">
          Edit listing
        </Link>
        <button type="button" className="btn btn-outline-danger" onClick={() => openDialog('delete')}>
          Delete
        </button>
      </div>
    );
  } else if (order) {
    action = (
      <div className="alert alert-success" role="status">
        <strong>Demo order placed.</strong> No real payment was processed.{' '}
        <Link to="/orders">View my orders</Link>
      </div>
    );
  } else if (sold) {
    action = (
      <button type="button" className="btn btn-dark btn-block" disabled>
        Sold
      </button>
    );
  } else if (!ready) {
    action = null;
  } else if (!user) {
    action = (
      <Link to="/login" state={{ from: location, reason: 'Log in to place a demo order.' }} className="btn btn-sage btn-block">
        Log in to order
      </Link>
    );
  } else {
    action = (
      <>
        <button type="button" className="btn btn-sage btn-block" onClick={() => openDialog('order')}>
          Place demo order
        </button>
        <p className="fine-print">Demo only: no payment is taken and nothing is shipped.</p>
      </>
    );
  }

  return (
    <div className="detail-wrap">
      <Link to="/" className="back-link">
        ← Back to listings
      </Link>
      <article className="detail">
        <div className="detail-media">
          <ItemImage listing={listing} className="detail-img" />
        </div>
        <div className="detail-info">
          <div className="detail-tags">
            <span className="tag">{categoryLabel(listing.category)}</span>
            <span className={`tag ${sold ? 'tag-sold' : 'tag-available'}`}>{sold ? 'Sold' : 'Available'}</span>
            {listing.isSample && <span className="tag tag-muted">Sample listing</span>}
          </div>
          <h1 className="detail-title">{listing.title}</h1>
          <div className="detail-price">{formatPrice(listing.price)}</div>
          <dl className="detail-facts">
            <div>
              <dt>Condition</dt>
              <dd>{conditionLabel(listing.condition)}</dd>
            </div>
            <div>
              <dt>Size</dt>
              <dd>{listing.size || 'Not specified'}</dd>
            </div>
            <div>
              <dt>Seller</dt>
              <dd>{listing.seller?.name ?? 'Unknown'}{isOwner && ' (you)'}</dd>
            </div>
            <div>
              <dt>Listed</dt>
              <dd>{formatDate(listing.createdAt)}</dd>
            </div>
          </dl>
          <h2 className="detail-subtitle">Description</h2>
          <p className="detail-desc">{listing.description || 'The seller has not added a description.'}</p>
          <div className="detail-cta">{action}</div>
        </div>
      </article>

      {dialog === 'order' && (
        <ConfirmDialog
          title="Place a demo order?"
          confirmLabel="Place demo order"
          onConfirm={placeOrder}
          onCancel={() => setDialog(null)}
          busy={busy}
          error={dialogError}
        >
          <p>
            You're ordering <strong>{listing.title}</strong> ({formatPrice(listing.price)}) from {listing.seller?.name}.
          </p>
          <p className="demo-note">This is a demo order. No payment will be taken and nothing will be charged.</p>
        </ConfirmDialog>
      )}
      {dialog === 'delete' && (
        <ConfirmDialog
          title="Delete this listing?"
          confirmLabel="Delete listing"
          tone="danger"
          onConfirm={deleteListing}
          onCancel={() => setDialog(null)}
          busy={busy}
          error={dialogError}
        >
          <p>
            <strong>{listing.title}</strong> will be removed permanently.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
