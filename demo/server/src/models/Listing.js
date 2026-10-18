import mongoose from 'mongoose';

export const CATEGORIES = ['tops', 'bottoms', 'dresses', 'jackets', 'shoes', 'accessories', 'other'];
export const CONDITIONS = ['new', 'like_new', 'good', 'fair'];
export const MAX_PRICE = 1_000_000;

const listingSchema = new mongoose.Schema(
  {
    title: { type: String, required: true, trim: true, maxlength: 120 },
    description: { type: String, trim: true, maxlength: 2000, default: '' },
    category: { type: String, required: true, enum: CATEGORIES },
    condition: { type: String, required: true, enum: CONDITIONS },
    size: { type: String, trim: true, maxlength: 20, default: '' },
    price: { type: Number, required: true, min: 1, max: MAX_PRICE },
    imageUrl: { type: String, default: null },
    seller: { type: mongoose.Schema.Types.ObjectId, ref: 'User', required: true, index: true },
    status: { type: String, enum: ['available', 'sold'], default: 'available' },
    buyer: { type: mongoose.Schema.Types.ObjectId, ref: 'User', default: null },
    seedKey: { type: String, default: undefined },
  },
  { timestamps: true }
);

listingSchema.index({ status: 1, createdAt: -1 });
listingSchema.index({ category: 1 });
listingSchema.index({ seedKey: 1 }, { unique: true, sparse: true });

listingSchema.set('toJSON', {
  transform: (_doc, ret) => {
    ret.id = String(ret._id);
    delete ret._id;
    delete ret.__v;
    ret.isSample = Boolean(ret.seedKey);
    delete ret.seedKey;
    // Only the seller's name is public; never expose seller email.
    if (ret.seller && typeof ret.seller === 'object' && ret.seller.name) {
      ret.seller = { id: String(ret.seller._id ?? ret.seller.id), name: ret.seller.name };
    }
    // Who bought an item is not public information.
    delete ret.buyer;
    return ret;
  },
});

export const Listing = mongoose.models.Listing || mongoose.model('Listing', listingSchema);
