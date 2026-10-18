import { describe, expect, it } from 'vitest';
import request from 'supertest';
import { Listing } from '../src/models/Listing.js';
import { Order } from '../src/models/Order.js';
import { app, postListing, signUp, validListing } from './helpers.js';

async function sellerWithListing() {
  const seller = await signUp('Seller');
  const { listing } = (await postListing(seller.agent)).body;
  return { seller, listing };
}

describe('orders', () => {
  it('requires login to order or view orders', async () => {
    const { listing } = await sellerWithListing();
    await request(app).post('/api/orders').send({ listingId: listing.id }).expect(401);
    await request(app).get('/api/orders').expect(401);
    expect((await Listing.findById(listing.id)).status).toBe('available');
  });

  it('places a demo order, marks the listing sold, and shows it in history', async () => {
    const { listing } = await sellerWithListing();
    const buyer = await signUp('Buyer');

    const res = await buyer.agent.post('/api/orders').send({ listingId: listing.id });
    expect(res.status).toBe(201);
    expect(res.body.order).toMatchObject({
      listing: listing.id,
      status: 'placed',
      item: { title: validListing.title, price: 799 },
      seller: { name: 'Seller' },
    });

    const after = await request(app).get(`/api/listings/${listing.id}`);
    expect(after.body.listing.status).toBe('sold');

    const history = await buyer.agent.get('/api/orders');
    expect(history.body.orders).toHaveLength(1);
    expect(history.body.orders[0].item.title).toBe(validListing.title);
  });

  it('rejects a second purchase of a sold item, by the same or another buyer', async () => {
    const { listing } = await sellerWithListing();
    const buyer = await signUp('Buyer');
    const other = await signUp('Other');
    await buyer.agent.post('/api/orders').send({ listingId: listing.id }).expect(201);

    const again = await buyer.agent.post('/api/orders').send({ listingId: listing.id });
    expect(again.status).toBe(409);
    expect(again.body.error).toMatch(/already ordered/);

    const second = await other.agent.post('/api/orders').send({ listingId: listing.id });
    expect(second.status).toBe(409);
    expect(second.body.error).toMatch(/already been sold/);
    expect(await Order.countDocuments()).toBe(1);
  });

  it('lets only one of several simultaneous orders succeed', async () => {
    const { listing } = await sellerWithListing();
    const buyers = await Promise.all([signUp(), signUp(), signUp(), signUp()]);
    const results = await Promise.all(buyers.map((b) => b.agent.post('/api/orders').send({ listingId: listing.id })));
    expect(results.filter((r) => r.status === 201)).toHaveLength(1);
    expect(results.filter((r) => r.status === 409)).toHaveLength(3);
    expect(await Order.countDocuments()).toBe(1);
  });

  it('rejects buying your own listing', async () => {
    const { seller, listing } = await sellerWithListing();
    const res = await seller.agent.post('/api/orders').send({ listingId: listing.id });
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/your own listing/);
    expect((await Listing.findById(listing.id)).status).toBe('available');
    expect(await Order.countDocuments()).toBe(0);
  });

  it('returns 404 for a missing listing', async () => {
    const buyer = await signUp();
    await buyer.agent.post('/api/orders').send({ listingId: '507f1f77bcf86cd799439011' }).expect(404);
    await buyer.agent.post('/api/orders').send({ listingId: 'bad' }).expect(404);
  });

  it('blocks editing or deleting a sold listing so orders stay consistent', async () => {
    const { seller, listing } = await sellerWithListing();
    const buyer = await signUp();
    await buyer.agent.post('/api/orders').send({ listingId: listing.id }).expect(201);

    const edit = await seller.agent.patch(`/api/listings/${listing.id}`).field({ ...validListing, price: '1' });
    expect(edit.status).toBe(409);
    const del = await seller.agent.delete(`/api/listings/${listing.id}`);
    expect(del.status).toBe(409);
    expect((await Listing.findById(listing.id)).price).toBe(799);
  });

  it("only shows the buyer's own orders", async () => {
    const { listing } = await sellerWithListing();
    const buyer = await signUp();
    const other = await signUp();
    await buyer.agent.post('/api/orders').send({ listingId: listing.id }).expect(201);
    expect((await other.agent.get('/api/orders')).body.orders).toEqual([]);
  });
});
