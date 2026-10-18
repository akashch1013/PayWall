import path from 'node:path';
import { fileURLToPath } from 'node:url';
import bcrypt from 'bcryptjs';
import mongoose from 'mongoose';
import { User } from './models/User.js';
import { Listing } from './models/Listing.js';
import { Order } from './models/Order.js';

// Local demo accounts only. Do not reuse these anywhere real.
export const DEMO_PASSWORD = 'demo12345';
export const DEMO_USERS = [
  { key: 'buyer', name: 'Demo Buyer', email: 'demo@rewear.local' },
  { key: 'seller', name: 'Demo Seller', email: 'seller@rewear.local' },
];


export const SAMPLE_LISTINGS = [
  { seedKey: 'floral-dress', owner: 'seller', title: 'Floral Summer Dress', category: 'dresses', condition: 'like_new', size: 'M', price: 349, description: 'Light cotton midi dress with a small floral print. Worn twice, no marks or pulls.' },
  { seedKey: 'denim-jacket', owner: 'seller', title: 'Classic Denim Jacket', category: 'jackets', condition: 'good', size: 'L', price: 599, description: 'Mid-wash denim jacket with button front. Slight fading at the cuffs, otherwise great.' },
  { seedKey: 'linen-shirt', owner: 'seller', title: 'White Linen Shirt', category: 'tops', condition: 'new', size: 'S', price: 199, description: 'Breathable linen shirt, new with tags. Relaxed fit.' },
  { seedKey: 'high-waist-trousers', owner: 'buyer', title: 'High-waist Trousers', category: 'bottoms', condition: 'like_new', size: '30', price: 450, description: 'Brown tailored trousers with a high waist and straight leg.' },
  { seedKey: 'silk-scarf', owner: 'seller', title: 'Vintage Silk Scarf', category: 'accessories', condition: 'good', size: '', price: 280, description: 'Square printed silk scarf, 70 x 70 cm. Tiny pull on one corner.' },
  { seedKey: 'ankle-boots', owner: 'buyer', title: 'Brown Ankle Boots', category: 'shoes', condition: 'good', size: 'EU 38', price: 720, description: 'Leather ankle boots with a low block heel. Soles in good shape.' },
  { seedKey: 'oversized-hoodie', owner: 'seller', title: 'Oversized Sage Hoodie', category: 'tops', condition: 'like_new', size: 'XL', price: 320, description: 'Soft fleece-lined hoodie in sage green. Oversized fit.' },
  { seedKey: 'pleated-skirt', owner: 'buyer', title: 'Pleated Midi Skirt', category: 'bottoms', condition: 'new', size: 'S', price: 375, description: 'Mustard pleated skirt with elastic waist. Never worn.' },
  { seedKey: 'canvas-tote', owner: 'seller', title: 'Canvas Tote Bag', category: 'other', condition: 'good', size: '', price: 150, description: 'Sturdy everyday canvas tote with inner pocket.' },
  { seedKey: 'wool-cap', owner: 'buyer', title: 'Knitted Wool Cap', category: 'accessories', condition: 'fair', size: 'One size', price: 120, description: 'Warm plum wool cap. Some pilling from regular wear.' },
];

/** Idempotent: upserts demo users and sample listings by stable keys. */
export async function seed() {
  const passwordHash = await bcrypt.hash(DEMO_PASSWORD, 10);
  const users = {};
  for (const u of DEMO_USERS) {
    users[u.key] = await User.findOneAndUpdate(
      { email: u.email },
      { $set: { name: u.name, passwordHash } },
      { upsert: true, new: true, setDefaultsOnInsert: true }
    );
  }

  for (const { owner, seedKey, ...fields } of SAMPLE_LISTINGS) {
    await Listing.updateOne(
      { seedKey },
      {
        $set: {
          ...fields,
          imageUrl: `/seed-images/${seedKey}.svg`,
          seller: users[owner]._id,
        },
        // Don't reset an item that was already sold through a demo order.
        $setOnInsert: { status: 'available', buyer: null },
      },
      { upsert: true }
    );
  }

  return {
    users: await User.countDocuments({ email: { $in: DEMO_USERS.map((u) => u.email) } }),
    sampleListings: await Listing.countDocuments({ seedKey: { $exists: true } }),
  };
}

const isCli = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isCli) {
  const { assertConfig, config } = await import('./config.js');
  const { connectDb, redactUri } = await import('./db.js');
  assertConfig();
  await connectDb(config.mongoUri);
  await Promise.all([User.init(), Listing.init(), Order.init()]);
  const result = await seed();
  console.log(`[seed] ${redactUri(config.mongoUri)}`);
  console.log(`[seed] Demo users: ${result.users}, sample listings: ${result.sampleListings} (safe to re-run).`);
  console.log(`[seed] Log in with ${DEMO_USERS.map((u) => u.email).join(' or ')} / ${DEMO_PASSWORD}`);
  await mongoose.disconnect();
}
