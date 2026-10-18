import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api.js';
import ListingCard from '../components/ListingCard.jsx';
import { EmptyState, ErrorState, GridSkeleton } from '../components/StateViews.jsx';
import { CATEGORIES, categoryLabel, SORTS } from '../constants.js';

export default function Browse() {
  const [params, setParams] = useSearchParams();
  const category = params.get('category') ?? '';
  const q = params.get('q') ?? '';
  const sort = params.get('sort') ?? 'newest';

  const [search, setSearch] = useState(q);
  const [state, setState] = useState({ status: 'loading', listings: [], error: '' });
  const [reloadKey, setReloadKey] = useState(0);
  const listingsRef = useRef(null);

  const updateParam = useCallback(
    (key, value) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value && !(key === 'sort' && value === 'newest')) next.set(key, value);
          else next.delete(key);
          return next;
        },
        { replace: true }
      );
    },
    [setParams]
  );

  // Keep the input in sync when the URL changes (back/forward, Clear filters).
  useEffect(() => setSearch((s) => (s.trim() === q ? s : q)), [q]);

  // Debounce typing into the URL; the URL drives the fetch.
  useEffect(() => {
    if (search.trim() === q) return undefined;
    const t = setTimeout(() => updateParam('q', search.trim()), 300);
    return () => clearTimeout(t);
  }, [search, q, updateParam]);

  useEffect(() => {
    const controller = new AbortController();
    const qs = new URLSearchParams();
    if (category) qs.set('category', category);
    if (q) qs.set('q', q);
    qs.set('sort', sort);
    setState((s) => ({ ...s, status: 'loading', error: '' }));
    api(`/api/listings?${qs}`, { signal: controller.signal })
      .then((data) => setState({ status: 'ready', listings: data.listings, error: '' }))
      .catch((err) => {
        if (err.name !== 'AbortError') setState({ status: 'error', listings: [], error: err.message });
      });
    return () => controller.abort();
  }, [category, q, sort, reloadKey]);

  const hasFilters = Boolean(category || q);
  const { status, listings, error } = state;
  const heading = category ? categoryLabel(category) : 'Latest listings';

  return (
    <>
      <section className="hero">
        <div className="hero-content">
          <div className="hero-tag">♻️ Sustainable fashion</div>
          <h1>
            Give clothes a<br />
            second story
          </h1>
          <p>
            Buy pre-loved fashion. Sell what no longer sparks joy.
            <br />
            Good for your wallet. Great for the planet.
          </p>
          <div className="hero-actions">
            <button
              type="button"
              className="btn btn-dark"
              onClick={() => listingsRef.current?.scrollIntoView({ behavior: 'smooth' })}
            >
              Browse listings
            </button>
            <Link to="/sell" className="btn btn-outline">
              Start selling
            </Link>
          </div>
        </div>
      </section>

      <section className="section" ref={listingsRef} aria-labelledby="listings-heading">
        <div className="section-header">
          <h2 className="section-title" id="listings-heading">
            {heading}
          </h2>
          <div className="toolbar">
            <div className="search-wrap">
              <label htmlFor="search" className="visually-hidden">
                Search listings
              </label>
              <input
                id="search"
                type="search"
                className="search-input"
                placeholder="Search listings…"
                value={search}
                maxLength={100}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <label htmlFor="sort" className="visually-hidden">
              Sort listings
            </label>
            <select id="sort" className="sort-select" value={sort} onChange={(e) => updateParam('sort', e.target.value)}>
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="filter-row" role="group" aria-label="Filter by category">
          {[{ value: '', label: 'All' }, ...CATEGORIES].map((c) => (
            <button
              key={c.value || 'all'}
              type="button"
              className={`filter-btn${category === c.value ? ' active' : ''}`}
              aria-pressed={category === c.value}
              onClick={() => updateParam('category', c.value)}
            >
              {c.label}
            </button>
          ))}
        </div>

        <div aria-live="polite" className="results-count">
          {status === 'ready' && listings.length > 0 && `${listings.length} ${listings.length === 1 ? 'item' : 'items'}`}
        </div>

        {status === 'loading' && <GridSkeleton />}
        {status === 'error' && <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />}
        {status === 'ready' && listings.length === 0 && (
          <EmptyState
            title={hasFilters ? 'No listings match' : 'No listings yet'}
            action={
              hasFilters ? (
                <button type="button" className="btn btn-outline" onClick={() => setParams({}, { replace: true })}>
                  Clear filters
                </button>
              ) : (
                <Link to="/sell" className="btn btn-sage">
                  List the first item
                </Link>
              )
            }
          >
            {hasFilters ? 'Try another category or search term.' : 'Be the first to list something.'}
          </EmptyState>
        )}
        {status === 'ready' && listings.length > 0 && (
          <div className="grid">
            {listings.map((l) => (
              <ListingCard key={l.id} listing={l} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}
