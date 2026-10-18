import request from 'supertest';
import { createApp } from '../src/app.js';

export const app = createApp();

// Smallest valid PNG (1x1 pixel).
export const PNG_BYTES = Buffer.from(
  '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000100' +
    '05fe02fea7d6a40000000049454e44ae426082',
  'hex'
);

let counter = 0;

/** Registers a fresh user and returns a cookie-carrying agent plus the user. */
export async function signUp(name = 'Test User') {
  const agent = request.agent(app);
  counter += 1;
  const res = await agent
    .post('/api/auth/register')
    .send({ name, email: `user${counter}-${Date.now()}@example.com`, password: 'password123' });
  if (res.status !== 201) throw new Error(`signUp failed: ${res.status} ${JSON.stringify(res.body)}`);
  return { agent, user: res.body.user };
}

export const validListing = {
  title: 'Blue Denim Jacket',
  description: 'Barely worn.',
  category: 'jackets',
  condition: 'good',
  size: 'M',
  price: '799',
};

/** Creates a listing via multipart, optionally with a photo buffer. */
export function postListing(agent, fields = validListing, photo) {
  let req = agent.post('/api/listings');
  for (const [k, v] of Object.entries(fields)) req = req.field(k, v);
  if (photo) req = req.attach('photo', photo.buffer, { filename: photo.filename, contentType: photo.contentType });
  return req;
}
