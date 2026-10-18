import { describe, expect, it } from 'vitest';
import request from 'supertest';
import { User } from '../src/models/User.js';
import { app, signUp } from './helpers.js';

describe('auth', () => {
  it('registers, keeps the session, and never returns the password hash', async () => {
    const agent = request.agent(app);
    const res = await agent
      .post('/api/auth/register')
      .send({ name: 'Priya', email: 'Priya@Example.com', password: 'password123' });
    expect(res.status).toBe(201);
    expect(res.body.user).toMatchObject({ name: 'Priya', email: 'priya@example.com' });
    expect(res.body.user.passwordHash).toBeUndefined();
    expect(res.headers['set-cookie'][0]).toMatch(/HttpOnly/);

    const stored = await User.findOne({ email: 'priya@example.com' });
    expect(stored.passwordHash).not.toBe('password123');
    expect(stored.passwordHash).toMatch(/^\$2[aby]\$/);

    const me = await agent.get('/api/auth/me');
    expect(me.body.user.email).toBe('priya@example.com');
    expect(me.body.user.passwordHash).toBeUndefined();
  });

  it('rejects invalid registration fields with per-field errors', async () => {
    const res = await request(app).post('/api/auth/register').send({ name: '', email: 'nope', password: 'short' });
    expect(res.status).toBe(400);
    expect(Object.keys(res.body.fields).sort()).toEqual(['email', 'name', 'password']);
  });

  it('rejects a duplicate email with 409', async () => {
    const body = { name: 'A', email: 'dup@example.com', password: 'password123' };
    await request(app).post('/api/auth/register').send(body).expect(201);
    const res = await request(app).post('/api/auth/register').send({ ...body, email: 'DUP@example.com' });
    expect(res.status).toBe(409);
    expect(res.body.fields.email).toMatch(/already registered/);
  });

  it('logs in with correct credentials and rejects wrong ones generically', async () => {
    await request(app).post('/api/auth/register').send({ name: 'B', email: 'b@example.com', password: 'password123' });
    const bad = await request(app).post('/api/auth/login').send({ email: 'b@example.com', password: 'wrongpass1' });
    expect(bad.status).toBe(401);
    expect(bad.body.error).toBe('Invalid email or password.');
    const unknown = await request(app).post('/api/auth/login').send({ email: 'x@example.com', password: 'wrongpass1' });
    expect(unknown.body.error).toBe('Invalid email or password.');

    const agent = request.agent(app);
    const ok = await agent.post('/api/auth/login').send({ email: 'B@example.com', password: 'password123' });
    expect(ok.status).toBe(200);
    expect((await agent.get('/api/auth/me')).body.user.name).toBe('B');
  });

  it('logs out by clearing the session', async () => {
    const { agent } = await signUp();
    await agent.post('/api/auth/logout').expect(204);
    expect((await agent.get('/api/auth/me')).body.user).toBeNull();
  });

  it('ignores a forged session cookie', async () => {
    const res = await request(app).get('/api/auth/me').set('Cookie', 'rewear_session=not-a-real-token');
    expect(res.body.user).toBeNull();
  });
});
