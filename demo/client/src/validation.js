import { CATEGORIES, CONDITIONS, IMAGE_TYPES, MAX_PRICE, MAX_UPLOAD_BYTES } from './constants.js';

// These rules mirror the server's validation so users get instant feedback.

export function validateListing(v) {
  const errors = {};
  const title = v.title.trim();
  const price = v.price.toString().trim();
  if (!title) errors.title = 'Title is required.';
  else if (title.length > 120) errors.title = 'Title must be 120 characters or fewer.';
  if (!CATEGORIES.some((c) => c.value === v.category)) errors.category = 'Choose a category.';
  if (!CONDITIONS.some((c) => c.value === v.condition)) errors.condition = 'Choose a condition.';
  if (v.size.trim().length > 20) errors.size = 'Size must be 20 characters or fewer.';
  if (v.description.trim().length > 2000) errors.description = 'Description must be 2000 characters or fewer.';
  if (!price) errors.price = 'Price is required.';
  else if (!/^\d+$/.test(price)) errors.price = 'Price must be a whole number of rupees.';
  else if (Number(price) < 1 || Number(price) > MAX_PRICE)
    errors.price = `Price must be between ₹1 and ₹${MAX_PRICE.toLocaleString('en-IN')}.`;
  return errors;
}

export function validatePhoto(file) {
  if (!IMAGE_TYPES.includes(file.type)) return 'Photo must be a JPG, PNG, WEBP or GIF image.';
  if (file.size > MAX_UPLOAD_BYTES) return 'Image must be 5 MB or smaller.';
  return null;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateSignup({ name, email, password }) {
  const errors = {};
  if (!name.trim()) errors.name = 'Name is required.';
  if (!EMAIL_RE.test(email.trim())) errors.email = 'Enter a valid email address.';
  if (password.length < 8) errors.password = 'Password must be at least 8 characters.';
  return errors;
}

export function validateLogin({ email, password }) {
  const errors = {};
  if (!email.trim()) errors.email = 'Email is required.';
  if (!password) errors.password = 'Password is required.';
  return errors;
}
