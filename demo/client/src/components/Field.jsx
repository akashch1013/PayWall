import { cloneElement, useId } from 'react';

/** Label + control + error message, wired together with ids for screen readers. */
export default function Field({ label, required, error, hint, prefix, children }) {
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const describedBy = [hint && hintId, error && errorId].filter(Boolean).join(' ') || undefined;
  const control = cloneElement(children, {
    id,
    'aria-invalid': error ? 'true' : undefined,
    'aria-describedby': describedBy,
    'aria-required': required || undefined,
  });
  return (
    <div className={`form-group${error ? ' has-error' : ''}`}>
      <label htmlFor={id}>
        {label}
        {required && (
          <span className="required" aria-hidden="true">
            {' '}
            *
          </span>
        )}
      </label>
      {prefix ? (
        <div className="prefix-input-wrap">
          <span className="input-prefix" aria-hidden="true">
            {prefix}
          </span>
          {control}
        </div>
      ) : (
        control
      )}
      {hint && (
        <p id={hintId} className="field-hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}
