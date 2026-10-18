import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api.js';
import { useAuth } from '../AuthContext.jsx';
import ListingForm from '../components/ListingForm.jsx';
import { EmptyState, ErrorState, Loading } from '../components/StateViews.jsx';
import { useToast } from '../components/Toast.jsx';
import { useApiData } from '../useApiData.js';

function FormCard({ title, subtitle, children }) {
  return (
    <div className="upload-wrap">
      <div className="upload-card">
        <h1 className="upload-title">{title}</h1>
        <p className="upload-sub">{subtitle}</p>
        {children}
      </div>
    </div>
  );
}

export function Sell() {
  const navigate = useNavigate();
  const toast = useToast();

  async function create(form) {
    const { listing } = await api('/api/listings', { method: 'POST', form });
    toast('Your listing is live.');
    navigate(`/listings/${listing.id}`);
  }

  return (
    <FormCard title="List a clothing item" subtitle="Add a photo and the details buyers need. Fields marked * are required.">
      <ListingForm submitLabel="Publish listing" busyLabel="Publishing…" onSubmit={create} />
    </FormCard>
  );
}

export function EditListing() {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const { status, data, error, reload } = useApiData(`/api/listings/${id}`);

  if (status === 'loading') return <Loading label="Loading listing…" />;
  if (status === 'error') {
    return (
      <div className="page-narrow">
        {error.status === 404 ? (
          <EmptyState title="Listing not found" action={<Link to="/dashboard" className="btn btn-outline">Back to my listings</Link>} />
        ) : (
          <ErrorState message={error.message} onRetry={reload} />
        )}
      </div>
    );
  }

  const { listing } = data;
  if (listing.seller?.id !== user.id) {
    return (
      <div className="page-narrow">
        <EmptyState title="You can only edit your own listings" action={<Link to={`/listings/${id}`} className="btn btn-outline">View listing</Link>} />
      </div>
    );
  }
  if (listing.status === 'sold') {
    return (
      <div className="page-narrow">
        <EmptyState title="This item has sold" action={<Link to="/dashboard" className="btn btn-outline">Back to my listings</Link>}>
          Sold items stay in order history and can't be edited.
        </EmptyState>
      </div>
    );
  }

  async function save(form) {
    await api(`/api/listings/${id}`, { method: 'PATCH', form });
    toast('Changes saved.');
    navigate(`/listings/${id}`);
  }

  return (
    <FormCard title="Edit listing" subtitle="Update the details or photo. Fields marked * are required.">
      <ListingForm listing={listing} submitLabel="Save changes" busyLabel="Saving…" onSubmit={save} />
    </FormCard>
  );
}
