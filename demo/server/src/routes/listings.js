import { Router } from 'express';
import mongoose from 'mongoose';
import { CATEGORIES, CONDITIONS, Listing, MAX_PRICE } from '../models/Listing.js';
import { asyncHandler, HttpError } from '../middleware/errors.js';
import { requireAuth } from '../middleware/auth.js';
import { photoUpload, removeFile, removeUploadByUrl, uploadUrlFor } from '../middleware/upload.js';

export const router = Router();

const SORTS = {
  newest: { createdAt: -1, _id: -1 },
  price_asc: { price: 1, createdAt: -1 },
  price_desc: { price: -1, createdAt: -1 },
};
const SELLER_FIELDS = 'name';
const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const str = (v) => (typeof v === 'string' ? v.trim() : '');

/** Validates and normalises listing fields; throws 400 with per-field messages. */
export function validateListingInput(body = {}) {
  const fields = {};
  const title = str(body.title);
  const description = str(body.description);
  const category = str(body.category);
  const condition = str(body.condition);
  const size = str(body.size);
  const rawPrice = str(String(body.price ?? ''));
  const price = Number(rawPrice);

  if (!title) fields.title = 'Title is required.';
  else if (title.length > 120) fields.title = 'Title must be 120 characters or fewer.';
  if (description.length > 2000) fields.description = 'Description must be 2000 characters or fewer.';
  if (!CATEGORIES.includes(category)) fields.category = 'Choose a category.';
  if (!CONDITIONS.includes(condition)) fields.condition = 'Choose a condition.';
  if (size.length > 20) fields.size = 'Size must be 20 characters or fewer.';
  if (!rawPrice) fields.price = 'Price is required.';
  else if (!Number.isInteger(price)) fields.price = 'Price must be a whole number of rupees.';
  else if (price < 1 || price > MAX_PRICE) fields.price = `Price must be between ₹1 and ₹${MAX_PRICE.toLocaleString('en-IN')}.`;

  if (Object.keys(fields).length) throw new HttpError(400, 'Please fix the highlighted fields.', fields);
  return { title, description, category, condition, size, price };
}

async function findOwnedListing(id, user) {
  if (!mongoose.isValidObjectId(id)) throw new HttpError(404, 'Listing not found.');
  const listing = await Listing.findById(id);
  if (!listing) throw new HttpError(404, 'Listing not found.');
  if (!listing.seller.equals(user._id)) throw new HttpError(403, 'You can only manage your own listings.');
  return listing;
}

/** Ensures an uploaded file is removed if the request fails after multer saved it. */
const cleanupUploadOnError = (handler) =>
  asyncHandler(async (req, res, next) => {
    try {
      await handler(req, res, next);
    } catch (err) {
      if (req.file) await removeFile(req.file.path);
      throw err;
    }
  });

router.get(
  '/',
  asyncHandler(async (req, res) => {
    const category = str(req.query.category);
    const q = str(req.query.q);
    const sort = str(req.query.sort) || 'newest';
    if (category && !CATEGORIES.includes(category)) throw new HttpError(400, 'Unknown category.');
    if (!SORTS[sort]) throw new HttpError(400, 'Unknown sort option.');
    if (q.length > 100) throw new HttpError(400, 'Search text is too long.');

    const filter = {};
    if (category) filter.category = category;
    if (q) {
      const re = new RegExp(escapeRegex(q), 'i');
      filter.$or = [{ title: re }, { description: re }];
    }
    const listings = await Listing.find(filter).sort(SORTS[sort]).limit(200).populate('seller', SELLER_FIELDS);
    res.json({ listings });
  })
);

router.get(
  '/mine',
  requireAuth,
  asyncHandler(async (req, res) => {
    const listings = await Listing.find({ seller: req.user._id }).sort(SORTS.newest).populate('seller', SELLER_FIELDS);
    res.json({ listings });
  })
);

router.get(
  '/:id',
  asyncHandler(async (req, res) => {
    if (!mongoose.isValidObjectId(req.params.id)) throw new HttpError(404, 'Listing not found.');
    const listing = await Listing.findById(req.params.id).populate('seller', SELLER_FIELDS);
    if (!listing) throw new HttpError(404, 'Listing not found.');
    res.json({ listing });
  })
);

router.post(
  '/',
  requireAuth,
  photoUpload,
  cleanupUploadOnError(async (req, res) => {
    const data = validateListingInput(req.body);
    const listing = await Listing.create({
      ...data,
      imageUrl: req.file ? uploadUrlFor(req.file) : null,
      seller: req.user._id,
    });
    await listing.populate('seller', SELLER_FIELDS);
    res.status(201).json({ listing });
  })
);

router.patch(
  '/:id',
  requireAuth,
  photoUpload,
  cleanupUploadOnError(async (req, res) => {
    const listing = await findOwnedListing(req.params.id, req.user);
    if (listing.status === 'sold') throw new HttpError(409, 'This item has been sold and can no longer be edited.');
    const data = validateListingInput(req.body);

    const oldImage = listing.imageUrl;
    let newImage = oldImage;
    if (req.file) newImage = uploadUrlFor(req.file);
    else if (req.body.removePhoto === 'true') newImage = null;

    // Conditional update so a purchase that lands mid-edit can't be overwritten.
    const updated = await Listing.findOneAndUpdate(
      { _id: listing._id, status: 'available' },
      { ...data, imageUrl: newImage },
      { new: true, runValidators: true }
    ).populate('seller', SELLER_FIELDS);
    if (!updated) throw new HttpError(409, 'This item has been sold and can no longer be edited.');

    if (oldImage !== newImage) await removeUploadByUrl(oldImage);
    res.json({ listing: updated });
  })
);

router.delete(
  '/:id',
  requireAuth,
  asyncHandler(async (req, res) => {
    const listing = await findOwnedListing(req.params.id, req.user);
    const deleted = await Listing.findOneAndDelete({ _id: listing._id, status: 'available' });
    if (!deleted) throw new HttpError(409, 'Sold items stay in order history and cannot be deleted.');
    await removeUploadByUrl(deleted.imageUrl);
    res.status(204).end();
  })
);
