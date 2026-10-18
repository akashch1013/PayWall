import { describe, expect, it } from 'vitest';
import request from 'supertest';
import { Listing } from '../src/models/Listing.js';
import { User } from '../src/models/User.js';
import { DEMO_PASSWORD, DEMO_USERS, SAMPLE_LISTINGS, seed } from '../src/seed.js';
import { app } from './helpers.js';

describe('seed', () => {
  it('is idempotent and its demo credentials work', async () => {
    const first = await seed();
    const second = await seed();
    expect(first).toEqual({ users: DEMO_USERS.length, sampleListings: SAMPLE_LISTINGS.length });
    expect(second).toEqual(first);
    expect(await User.countDocuments()).toBe(DEMO_USERS.length);
    expect(await Listing.countDocuments()).toBe(SAMPLE_LISTINGS.length);

    const login = await request(app).post('/api/auth/login').send({ email: DEMO_USERS[0].email, password: DEMO_PASSWORD });
    expect(login.status).toBe(200);
  });

  it('marks sample listings and serves their local images', async () => {
    await seed();
    const { listings } = (await request(app).get('/api/listings')).body;
    expect(listings.every((l) => l.isSample)).toBe(true);
    for (const l of listings) {
      const img = await request(app).get(l.imageUrl);
      expect(img.status, l.imageUrl).toBe(200);
    }
  });

  it('does not reset a sample item that was sold', async () => {
    await seed();
    const listing = await Listing.findOne({ seedKey: 'floral-dress' });
    await Listing.updateOne({ _id: listing._id }, { status: 'sold' });
    await seed();
    expect((await Listing.findById(listing._id)).status).toBe('sold');
  });
});
