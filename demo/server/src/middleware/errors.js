import multer from 'multer';
import mongoose from 'mongoose';

export class HttpError extends Error {
  constructor(status, message, fields) {
    super(message);
    this.status = status;
    this.fields = fields;
  }
}

/** Wrap async route handlers so rejected promises reach the error handler. */
export const asyncHandler = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);

export function notFound(req, res) {
  res.status(404).json({ error: 'Not found' });
}

// eslint-disable-next-line no-unused-vars
export function errorHandler(err, req, res, next) {
  if (err instanceof HttpError) {
    return res.status(err.status).json({ error: err.message, ...(err.fields && { fields: err.fields }) });
  }
  if (err instanceof multer.MulterError) {
    const message =
      err.code === 'LIMIT_FILE_SIZE'
        ? 'Image must be 5 MB or smaller.'
        : err.code === 'LIMIT_UNEXPECTED_FILE'
          ? 'Only one image can be uploaded, in the "photo" field.'
          : 'The upload could not be processed.';
    return res.status(400).json({ error: message, fields: { photo: message } });
  }
  if (err.type === 'entity.parse.failed') {
    return res.status(400).json({ error: 'Request body must be valid JSON.' });
  }
  if (err instanceof mongoose.Error.ValidationError) {
    const fields = Object.fromEntries(Object.entries(err.errors).map(([k, v]) => [k, v.message]));
    return res.status(400).json({ error: 'Please fix the highlighted fields.', fields });
  }
  if (err instanceof mongoose.Error.CastError) {
    return res.status(404).json({ error: 'Not found' });
  }
  if (err.name === 'MongooseServerSelectionError' || err.name === 'MongoNetworkError') {
    console.error('[db]', err.message);
    return res.status(503).json({ error: 'The database is unavailable. Please try again shortly.' });
  }
  console.error(err);
  res.status(500).json({ error: 'Something went wrong on our side. Please try again.' });
}
