import { useEffect, useId, useRef } from 'react';

/** Accessible modal: focuses the confirm button, traps Tab, closes on Escape, restores focus. */
export default function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel = 'Cancel',
  onConfirm,
  onCancel,
  busy = false,
  error,
  tone = 'dark',
}) {
  const ref = useRef(null);
  const confirmRef = useRef(null);
  const titleId = useId();
  const bodyId = useId();

  useEffect(() => {
    const previous = document.activeElement;
    confirmRef.current?.focus();
    return () => previous?.focus?.();
  }, []);

  function onKeyDown(e) {
    if (e.key === 'Escape' && !busy) {
      e.stopPropagation();
      onCancel();
      return;
    }
    if (e.key !== 'Tab') return;
    const focusable = ref.current.querySelectorAll('button:not([disabled]), a[href]');
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onCancel()}>
      <div
        ref={ref}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        onKeyDown={onKeyDown}
      >
        <h2 id={titleId} className="modal-title">
          {title}
        </h2>
        <div id={bodyId} className="modal-body">
          {children}
        </div>
        {error && (
          <p className="alert alert-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button type="button" className="btn btn-outline" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={`btn ${tone === 'danger' ? 'btn-danger' : 'btn-dark'}`}
            onClick={onConfirm}
            disabled={busy}
            aria-busy={busy}
          >
            {busy ? 'Please wait…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
