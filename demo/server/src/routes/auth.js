import { Router } from 'express';
import bcrypt from 'bcryptjs';
import { User } from '../models/User.js';
import { asyncHandler, HttpError } from '../middleware/errors.js';
import { clearSessionCookie, optionalAuth, setSessionCookie } from '../middleware/auth.js';

export const router = Router();

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const MIN_PASSWORD = 8;

const str = (v) => (typeof v === 'string' ? v.trim() : '');

router.post(
  '/register',
  asyncHandler(async (req, res) => {
    const name = str(req.body?.name);
    const email = str(req.body?.email).toLowerCase();
    const password = typeof req.body?.password === 'string' ? req.body.password : '';

    const fields = {};
    if (!name) fields.name = 'Name is required.';
    else if (name.length > 80) fields.name = 'Name must be 80 characters or fewer.';
    if (!EMAIL_RE.test(email)) fields.email = 'Enter a valid email address.';
    if (password.length < MIN_PASSWORD) fields.password = `Password must be at least ${MIN_PASSWORD} characters.`;
    else if (password.length > 128) fields.password = 'Password must be 128 characters or fewer.';
    if (Object.keys(fields).length) throw new HttpError(400, 'Please fix the highlighted fields.', fields);

    if (await User.exists({ email })) {
      throw new HttpError(409, 'An account with this email already exists.', { email: 'This email is already registered.' });
    }
    let user;
    try {
      user = await User.create({ name, email, passwordHash: await bcrypt.hash(password, 10) });
    } catch (err) {
      if (err.code === 11000) {
        throw new HttpError(409, 'An account with this email already exists.', { email: 'This email is already registered.' });
      }
      throw err;
    }
    setSessionCookie(res, user);
    res.status(201).json({ user });
  })
);

router.post(
  '/login',
  asyncHandler(async (req, res) => {
    const email = str(req.body?.email).toLowerCase();
    const password = typeof req.body?.password === 'string' ? req.body.password : '';
    if (!email || !password) {
      const fields = {};
      if (!email) fields.email = 'Email is required.';
      if (!password) fields.password = 'Password is required.';
      throw new HttpError(400, 'Please enter your email and password.', fields);
    }
    const user = await User.findOne({ email });
    if (!user || !(await bcrypt.compare(password, user.passwordHash))) {
      throw new HttpError(401, 'Invalid email or password.');
    }
    setSessionCookie(res, user);
    res.json({ user });
  })
);

router.post('/logout', (req, res) => {
  clearSessionCookie(res);
  res.status(204).end();
});

router.get('/me', optionalAuth, (req, res) => {
  res.json({ user: req.user ?? null });
});
