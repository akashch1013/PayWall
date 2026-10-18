import { Link } from 'react-router-dom';
import ItemImage from './ItemImage.jsx';
import { categoryLabel, conditionLabel, formatPrice } from '../constants.js';

export default function ListingCard({ listing }) {
  const sold = listing.status === 'sold';
  return (
    <Link to={`/listings/${listing.id}`} className="card" aria-label={`${listing.title}, ${formatPrice(listing.price)}${sold ? ', sold' : ''}`}>
      <div className="card-media">
        <ItemImage listing={listing} />
        <span className="card-badge">{categoryLabel(listing.category)}</span>
        {sold ? <span className="card-sold-badge">Sold</span> : <span className="card-avail-badge">Available</span>}
      </div>
      <div className="card-body">
        <div className="card-title">{listing.title}</div>
        <div className="card-meta">
          {conditionLabel(listing.condition)}
          {listing.size && ` · Size ${listing.size}`}
        </div>
        <div className="card-footer">
          <div className="card-price">{formatPrice(listing.price)}</div>
          <div className="card-seller">{listing.seller?.name}</div>
        </div>
      </div>
    </Link>
  );
}
