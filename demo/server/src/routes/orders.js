import { Router } from 'express';
import mongoose from 'mongoose';
import { Listing } from '../models/Listing.js';
import { Order } from '../models/Order.js';
import { asyncHandler, HttpError } from '../middleware/errors.js';
import { requireAuth } from '../middleware/auth.js';

export const router = Router();

router.use(requireAuth);

router.post(
  '/',
  asyncHandler(async (req, res) => {
    const listingId = req.body?.listingId;
    if (!mongoose.isValidObjectId(listingId)) throw new HttpError(404, 'Listing not found.');
    const buyerId = req.user._id;

    // Claim the item atomically: only one request can flip it from available to sold.
    const listing = await Listing.findOneAndUpdate(
      { _id: listingId, status: 'available', seller: { $ne: buyerId } },
      { status: 'sold', buyer: buyerId },
      { new: true }
    );

    if (!listing) {
      const current = await Listing.findById(listingId);
      if (!current) throw new HttpError(404, 'Listing not found.');
      if (current.seller.equals(buyerId)) throw new HttpError(400, "You can't order your own listing.");
      if (current.buyer?.equals(buyerId)) throw new HttpError(409, 'You have already ordered this item.');
      throw new HttpError(409, 'Sorry, this item has already been sold.');
    }

    let order;
    try {
      order = await Order.create({
        listing: listing._id,
        buyer: buyerId,
        seller: listing.seller,
        item: { title: listing.title, price: listing.price, imageUrl: listing.imageUrl, category: listing.category },
      });
    } catch (err) {
      // Keep listing and orders consistent: release the item if the order couldn't be recorded.
      await Listing.updateOne({ _id: listing._id, buyer: buyerId }, { status: 'available', buyer: null });
      if (err.code === 11000) throw new HttpError(409, 'Sorry, this item has already been sold.');
      throw err;
    }

    await order.populate('seller', 'name');
    res.status(201).json({ order });
  })
);

router.get(
  '/',
  asyncHandler(async (req, res) => {
    const orders = await Order.find({ buyer: req.user._id }).sort({ createdAt: -1 }).populate('seller', 'name');
    res.json({ orders });
  })
);
