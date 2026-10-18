export function Loading({ label = 'Loading…' }) {
  return (
    <div className="state-view" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="state-view state-error" role="alert">
      <p className="state-title">Something went wrong</p>
      <p>{message}</p>
      {onRetry && (
        <button type="button" className="btn btn-outline" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="state-view">
      <p className="state-title">{title}</p>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function GridSkeleton({ count = 8 }) {
  return (
    <div className="grid" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div className="card skeleton-card" key={i}>
          <div className="skeleton skeleton-img" />
          <div className="card-body">
            <div className="skeleton skeleton-line" />
            <div className="skeleton skeleton-line short" />
          </div>
        </div>
      ))}
    </div>
  );
}
