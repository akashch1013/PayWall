import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api.js';
import ConfirmDialog from '../components/ConfirmDialog.jsx';
import ItemImage from '../components/ItemImage.jsx';
import { EmptyState, ErrorState, Loading } from '../components/StateViews.jsx';
import { useToast } from '../components/Toast.jsx';
import { categoryLabel, conditionLabel, formatDate, formatPrice } from '../constants.js';
import { useApiData } from '../useApiData.js';

export default function Dashboard() {
  const { status, data, error, reload, setData } = useApiData('/api/listings/mine');
  const toast = useToast();
  const [pendingDelete, setPendingDelete] = useState(null);
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  async function confirmDelete() {
    setBusy(true);
    setDeleteError('');
    try {
      await api(`/api/listings/${pendingDelete.id}`, { method: 'DELETE' });
      setData((d) => ({ listings: d.listings.filter((l) => l.id !== pendingDelete.id) }));
      toast(`Deleted "${pendingDelete.title}".`);
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const listings = data?.listings ?? [];
  const soldCount = listings.filter((l) => l.status === 'sold').length;

  return (
    <div className="section">
      <div className="section-header">
        <div>
          <h1 className="section-title">My listings</h1>
          {status === 'ready' && listings.length > 0 && (
            <p className="section-sub">
              {listings.length - soldCount} available · {soldCount} sold
            </p>
          )}
        </div>
        <Link to="/sell" className="btn btn-sage">
          + New listing
        </Link>
      </div>

      {status === 'loading' && <Loading label="Loading your listings…" />}
      {status === 'error' && <ErrorState message={error.message} onRetry={reload} />}
      {status === 'ready' && listings.length === 0 && (
        <EmptyState title="You haven't listed anything yet" action={<Link to="/sell" className="btn btn-sage">List your first item</Link>}>
          Items you list for sale will appear here.
        </EmptyState>
      )}
      {status === 'ready' && listings.length > 0 && (
        <ul className="row-list">
          {listings.map((l) => {
            const sold = l.status === 'sold';
            return (
              <li key={l.id} className="row-item">
                <ItemImage listing={l} className="row-thumb" />
                <div className="row-main">
                  <Link to={`/listings/${l.id}`} className="row-title">
                    {l.title}
                  </Link>
                  <div className="row-meta">
                    {categoryLabel(l.category)} · {conditionLabel(l.condition)}
                    {l.size && ` · Size ${l.size}`} · Listed {formatDate(l.createdAt)}
                  </div>
                  {sold && <div className="row-note">Sold. Sold items can't be edited or deleted.</div>}
                </div>
                <div className="row-price">{formatPrice(l.price)}</div>
                <span className={`tag ${sold ? 'tag-sold' : 'tag-available'}`}>{sold ? 'Sold' : 'Available'}</span>
                <div className="row-actions">
                  {sold ? (
                    <Link to={`/listings/${l.id}`} className="btn btn-outline btn-sm">
                      View
                    </Link>
                  ) : (
                    <>
                      <Link to={`/listings/${l.id}/edit`} className="btn btn-outline btn-sm" aria-label={`Edit ${l.title}`}>
                        Edit
                      </Link>
                      <button
                        type="button"
                        className="btn btn-outline-danger btn-sm"
                        aria-label={`Delete ${l.title}`}
                        onClick={() => {
                          setDeleteError('');
                          setPendingDelete(l);
                        }}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {pendingDelete && (
        <ConfirmDialog
          title="Delete this listing?"
          confirmLabel="Delete listing"
          tone="danger"
          onConfirm={confirmDelete}
          onCancel={() => setPendingDelete(null)}
          busy={busy}
          error={deleteError}
        >
          <p>
            <strong>{pendingDelete.title}</strong> will be removed permanently.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
