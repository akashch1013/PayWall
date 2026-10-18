import { useEffect, useRef, useState } from 'react';
import Field from './Field.jsx';
import { CATEGORIES, CONDITIONS } from '../constants.js';
import { validateListing, validatePhoto } from '../validation.js';

const EMPTY = { title: '', category: '', condition: '', size: '', price: '', description: '' };

function initialValues(listing) {
  if (!listing) return EMPTY;
  return {
    title: listing.title,
    category: listing.category,
    condition: listing.condition,
    size: listing.size ?? '',
    price: String(listing.price),
    description: listing.description ?? '',
  };
}

/**
 * Create/edit form for a listing. `onSubmit(formData)` must return a promise;
 * if it throws an ApiError, its message and field errors are shown here.
 */
export default function ListingForm({ listing, submitLabel, busyLabel, onSubmit }) {
  const [values, setValues] = useState(() => initialValues(listing));
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [removeExisting, setRemoveExisting] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef(null);
  const errorSummary = useRef(null);

  const existingUrl = listing?.imageUrl && !removeExisting ? listing.imageUrl : null;
  const shownImage = previewUrl ?? existingUrl;

  useEffect(() => {
    if (!file || typeof URL.createObjectURL !== 'function') return undefined;
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const set = (key) => (e) => {
    setValues((v) => ({ ...v, [key]: e.target.value }));
    if (errors[key]) setErrors(({ [key]: _removed, ...rest }) => rest);
  };

  function choosePhoto(candidate) {
    if (!candidate) return;
    const problem = validatePhoto(candidate);
    if (fileInput.current) fileInput.current.value = '';
    if (problem) {
      setErrors((e) => ({ ...e, photo: problem }));
      return;
    }
    setErrors(({ photo: _removed, ...rest }) => rest);
    setFile(candidate);
  }

  function clearPhoto() {
    setFile(null);
    setPreviewUrl(null);
    if (listing?.imageUrl) setRemoveExisting(true);
    setErrors(({ photo: _removed, ...rest }) => rest);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setFormError('');
    const found = validateListing(values);
    if (errors.photo) found.photo = errors.photo;
    setErrors(found);
    if (Object.keys(found).length) {
      setFormError('Please fix the highlighted fields.');
      errorSummary.current?.focus();
      return;
    }

    const form = new FormData();
    for (const [k, v] of Object.entries(values)) form.append(k, v.trim());
    if (file) form.append('photo', file);
    else if (removeExisting) form.append('removePhoto', 'true');

    setSubmitting(true);
    try {
      await onSubmit(form);
    } catch (err) {
      setErrors(err.fields ?? {});
      setFormError(err.message);
      errorSummary.current?.focus();
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <div ref={errorSummary} tabIndex={-1} className="error-summary-anchor">
        {formError && (
          <p className="alert alert-error" role="alert">
            {formError}
          </p>
        )}
      </div>

      <div className={`form-group${errors.photo ? ' has-error' : ''}`}>
        <span className="label-text" id="photo-label">
          Photo <span className="optional">(optional)</span>
        </span>
        {shownImage ? (
          <div className="photo-preview">
            <img src={shownImage} alt="Selected item photo preview" />
            <div className="photo-preview-actions">
              <button type="button" className="btn btn-outline btn-sm" onClick={() => fileInput.current?.click()}>
                Change photo
              </button>
              <button type="button" className="btn btn-outline btn-sm" onClick={clearPhoto}>
                Remove photo
              </button>
            </div>
          </div>
        ) : file ? (
          <p className="photo-chosen">
            Selected: {file.name}{' '}
            <button type="button" className="link-btn" onClick={clearPhoto}>
              Remove
            </button>
          </p>
        ) : null}
        <label
          className={`drop-zone${dragOver ? ' drag-over' : ''}${shownImage || file ? ' visually-hidden-zone' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            choosePhoto(e.dataTransfer.files?.[0]);
          }}
        >
          <input
            ref={fileInput}
            type="file"
            name="photo"
            accept="image/jpeg,image/png,image/webp,image/gif"
            className="visually-hidden"
            aria-labelledby="photo-label"
            aria-describedby={errors.photo ? 'photo-error' : 'photo-hint'}
            aria-invalid={errors.photo ? 'true' : undefined}
            onChange={(e) => choosePhoto(e.target.files?.[0])}
          />
          <span className="drop-icon" aria-hidden="true">
            📸
          </span>
          <span className="drop-text">
            <strong>Click to upload</strong> or drag &amp; drop
          </span>
          <span className="drop-text small" id="photo-hint">
            JPG, PNG, WEBP or GIF, up to 5 MB
          </span>
        </label>
        {errors.photo && (
          <p id="photo-error" className="field-error">
            {errors.photo}
          </p>
        )}
      </div>

      <Field label="Item title" required error={errors.title}>
        <input type="text" value={values.title} onChange={set('title')} maxLength={120} placeholder="e.g. Floral Midi Dress" />
      </Field>

      <div className="form-row">
        <Field label="Category" required error={errors.category}>
          <select value={values.category} onChange={set('category')}>
            <option value="">Select category</option>
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Condition" required error={errors.condition}>
          <select value={values.condition} onChange={set('condition')}>
            <option value="">Select condition</option>
            {CONDITIONS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="form-row">
        <Field label="Size" error={errors.size} hint="For example S, M, 32 or EU 38">
          <input type="text" value={values.size} onChange={set('size')} maxLength={20} />
        </Field>
        <Field label="Price (₹)" required error={errors.price} prefix="₹">
          <input type="number" inputMode="numeric" min="1" step="1" value={values.price} onChange={set('price')} placeholder="0" />
        </Field>
      </div>

      <Field label="Description" error={errors.description}>
        <textarea
          value={values.description}
          onChange={set('description')}
          maxLength={2000}
          placeholder="Fabric, brand, measurements, any flaws…"
        />
      </Field>

      <button type="submit" className="submit-btn" disabled={submitting} aria-busy={submitting}>
        {submitting ? busyLabel : submitLabel}
      </button>
    </form>
  );
}
