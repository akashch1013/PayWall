import { useState } from 'react';
import { categoryIcon, categoryLabel } from '../constants.js';

/** Shows the listing photo, or a deliberate category placeholder if there is none or it fails to load. */
export default function ItemImage({ listing, className = 'card-img' }) {
  const [failed, setFailed] = useState(false);
  const src = listing.imageUrl ?? listing.item?.imageUrl;
  const category = listing.category ?? listing.item?.category;
  const title = listing.title ?? listing.item?.title;

  if (src && !failed) {
    return <img className={className} src={src} alt={title} loading="lazy" onError={() => setFailed(true)} />;
  }
  return (
    <div className={`${className} img-fallback`} role="img" aria-label={`${title}: no photo`}>
      <span className="img-fallback-icon" aria-hidden="true">
        {categoryIcon(category)}
      </span>
      <span className="img-fallback-text" aria-hidden="true">
        {categoryLabel(category)} · no photo
      </span>
    </div>
  );
}
