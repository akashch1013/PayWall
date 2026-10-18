import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import request from 'supertest';
import { Listing } from '../src/models/Listing.js';
import { app, PNG_BYTES, postListing, signUp, validListing } from './helpers.js';

const uploadedFiles = () => fs.readdirSync(process.env.UPLOAD_DIR);
const png = { buffer: PNG_BYTES, filename: 'item.png', contentType: 'image/png' };

describe('listings: create and validate', () => {
  it('requires login to create a listing and stores nothing', async () => {
    const res = await postListing(request(app), validListing, png);
    expect(res.status).toBe(401);
    expect(await Listing.countDocuments()).toBe(0);
    expect(uploadedFiles()).toEqual([]);
  });

  it('creates a listing with a photo that is then served', async () => {
    const { agent, user } = await signUp('Seller');
    const res = await postListing(agent, validListing, png);
    expect(res.status).toBe(201);
    const { listing } = res.body;
    expect(listing).toMatchObject({ title: 'Blue Denim Jacket', price: 799, status: 'available', isSample: false });
    expect(listing.seller).toEqual({ id: user.id, name: 'Seller' });
    expect(listing.imageUrl).toMatch(/^\/uploads\/[\w-]+\.png$/);
    expect(uploadedFiles()).toHaveLength(1);

    const img = await request(app).get(listing.imageUrl);
    expect(img.status).toBe(200);
    expect(img.headers['content-type']).toBe('image/png');

    const fetched = await request(app).get(`/api/listings/${listing.id}`);
    expect(fetched.body.listing.title).toBe('Blue Denim Jacket');
  });

  it('creates a listing without a photo', async () => {
    const { agent } = await signUp();
    const res = await postListing(agent);
    expect(res.status).toBe(201);
    expect(res.body.listing.imageUrl).toBeNull();
  });

  it.each([
    [{ title: '' }, 'title'],
    [{ category: 'hats' }, 'category'],
    [{ condition: 'mint' }, 'condition'],
    [{ price: '' }, 'price'],
    [{ price: '0' }, 'price'],
    [{ price: '-5' }, 'price'],
    [{ price: 'abc' }, 'price'],
    [{ price: '12.5' }, 'price'],
    [{ price: '2000000' }, 'price'],
  ])('rejects invalid field %o and removes the uploaded photo', async (override, field) => {
    const { agent } = await signUp();
    const res = await postListing(agent, { ...validListing, ...override }, png);
    expect(res.status).toBe(400);
    expect(res.body.fields[field]).toBeTruthy();
    expect(await Listing.countDocuments()).toBe(0);
    expect(uploadedFiles()).toEqual([]);
  });

  it('rejects non-image uploads, including disguised ones', async () => {
    const { agent } = await signUp();
    const text = await postListing(agent, validListing, {
      buffer: Buffer.from('hello'),
      filename: 'notes.txt',
      contentType: 'text/plain',
    });
    expect(text.status).toBe(400);
    expect(text.body.fields.photo).toMatch(/JPG, PNG, WEBP or GIF/);

    const disguised = await postListing(agent, validListing, {
      buffer: Buffer.from('this is not really a png file'),
      filename: 'fake.png',
      contentType: 'image/png',
    });
    expect(disguised.status).toBe(400);
    expect(disguised.body.fields.photo).toMatch(/JPG, PNG, WEBP or GIF/);
    expect(await Listing.countDocuments()).toBe(0);
    expect(uploadedFiles()).toEqual([]);
  });

  it('rejects images over 5 MB', async () => {
    const { agent } = await signUp();
    const big = Buffer.concat([PNG_BYTES, Buffer.alloc(5 * 1024 * 1024 + 10)]);
    const res = await postListing(agent, validListing, { buffer: big, filename: 'big.png', contentType: 'image/png' });
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/5 MB/);
    expect(await Listing.countDocuments()).toBe(0);
    expect(uploadedFiles()).toEqual([]);
  });
});

describe('listings: ownership', () => {
  it('lets the owner edit (including replacing the photo) and delete', async () => {
    const { agent } = await signUp();
    const { listing } = (await postListing(agent, validListing, png)).body;
    const oldFile = path.basename(listing.imageUrl);

    const edit = await agent
      .patch(`/api/listings/${listing.id}`)
      .field({ ...validListing, title: 'Updated title', price: '650' })
      .attach('photo', PNG_BYTES, { filename: 'new.png', contentType: 'image/png' });
    expect(edit.status).toBe(200);
    expect(edit.body.listing).toMatchObject({ title: 'Updated title', price: 650 });
    expect(uploadedFiles()).not.toContain(oldFile);
    expect(uploadedFiles()).toHaveLength(1);

    const removePhoto = await agent
      .patch(`/api/listings/${listing.id}`)
      .field({ ...validListing, removePhoto: 'true' });
    expect(removePhoto.body.listing.imageUrl).toBeNull();
    expect(uploadedFiles()).toEqual([]);

    await agent.delete(`/api/listings/${listing.id}`).expect(204);
    await request(app).get(`/api/listings/${listing.id}`).expect(404);
  });

  it("forbids editing or deleting another seller's listing", async () => {
    const owner = await signUp('Owner');
    const other = await signUp('Other');
    const { listing } = (await postListing(owner.agent)).body;

    const edit = await other.agent.patch(`/api/listings/${listing.id}`).field({ ...validListing, title: 'Hacked' });
    expect(edit.status).toBe(403);
    const del = await other.agent.delete(`/api/listings/${listing.id}`);
    expect(del.status).toBe(403);
    expect((await Listing.findById(listing.id)).title).toBe('Blue Denim Jacket');
  });

  it('requires login to edit or delete', async () => {
    const { agent } = await signUp();
    const { listing } = (await postListing(agent)).body;
    await request(app).patch(`/api/listings/${listing.id}`).field(validListing).expect(401);
    await request(app).delete(`/api/listings/${listing.id}`).expect(401);
    await request(app).get('/api/listings/mine').expect(401);
  });

  it('returns only the current user’s listings from /mine', async () => {
    const a = await signUp();
    const b = await signUp();
    await postListing(a.agent, { ...validListing, title: 'Mine' });
    await postListing(b.agent, { ...validListing, title: 'Theirs' });
    const res = await a.agent.get('/api/listings/mine');
    expect(res.body.listings.map((l) => l.title)).toEqual(['Mine']);
  });

  it('returns 404 for unknown or malformed ids', async () => {
    await request(app).get('/api/listings/507f1f77bcf86cd799439011').expect(404);
    await request(app).get('/api/listings/not-an-id').expect(404);
  });
});

describe('listings: browse', () => {
  it('filters by category, searches text, and sorts', async () => {
    const { agent } = await signUp();
    await postListing(agent, { ...validListing, title: 'Red Dress', category: 'dresses', price: '500' });
    await postListing(agent, { ...validListing, title: 'Green Shirt', category: 'tops', price: '200', description: 'cotton' });
    await postListing(agent, { ...validListing, title: 'Blue Dress', category: 'dresses', price: '300' });

    const newest = await request(app).get('/api/listings');
    expect(newest.body.listings.map((l) => l.title)).toEqual(['Blue Dress', 'Green Shirt', 'Red Dress']);

    const dresses = await request(app).get('/api/listings?category=dresses&sort=price_asc');
    expect(dresses.body.listings.map((l) => l.title)).toEqual(['Blue Dress', 'Red Dress']);

    const desc = await request(app).get('/api/listings?sort=price_desc');
    expect(desc.body.listings.map((l) => l.price)).toEqual([500, 300, 200]);

    const search = await request(app).get('/api/listings?q=COTTON');
    expect(search.body.listings.map((l) => l.title)).toEqual(['Green Shirt']);

    const regexy = await request(app).get('/api/listings?q=' + encodeURIComponent('.*('));
    expect(regexy.status).toBe(200);
    expect(regexy.body.listings).toEqual([]);

    await request(app).get('/api/listings?category=hats').expect(400);
    await request(app).get('/api/listings?sort=random').expect(400);
  });

  it('does not expose seller emails or buyer ids', async () => {
    const { agent } = await signUp();
    await postListing(agent);
    const { listings } = (await request(app).get('/api/listings')).body;
    expect(JSON.stringify(listings)).not.toMatch(/@example\.com/);
    expect(listings[0].buyer).toBeUndefined();
  });
});
