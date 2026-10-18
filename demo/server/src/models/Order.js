import mongoose from 'mongoose';

const orderSchema = new mongoose.Schema(
  {
    // Unique: a listing can be ordered at most once.
    listing: { type: mongoose.Schema.Types.ObjectId, ref: 'Listing', required: true, unique: true },
    buyer: { type: mongoose.Schema.Types.ObjectId, ref: 'User', required: true, index: true },
    seller: { type: mongoose.Schema.Types.ObjectId, ref: 'User', required: true },
    // Snapshot so order history stays readable even if listing details change later.
    item: {
      title: { type: String, required: true },
      price: { type: Number, required: true },
      imageUrl: { type: String, default: null },
      category: { type: String, required: true },
    },
    status: { type: String, enum: ['placed'], default: 'placed' },
  },
  { timestamps: true }
);

orderSchema.set('toJSON', {
  transform: (_doc, ret) => {
    ret.id = String(ret._id);
    delete ret._id;
    delete ret.__v;
    for (const key of ['seller', 'buyer']) {
      const v = ret[key];
      if (v && typeof v === 'object' && v.name) ret[key] = { id: String(v._id ?? v.id), name: v.name };
    }
    if (ret.listing && typeof ret.listing === 'object' && ret.listing._id) ret.listing = String(ret.listing._id);
    return ret;
  },
});

export const Order = mongoose.models.Order || mongoose.model('Order', orderSchema);
