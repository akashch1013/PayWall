import jwt from 'jsonwebtoken';
import { config } from '../config.js';
import { User } from '../models/User.js';
import { HttpError } from './errors.js';

export const COOKIE_NAME = 'rewear_session';
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

export function setSessionCookie(res, user) {
  const token = jwt.sign({ sub: String(user._id) }, config.jwtSecret, { expiresIn: '7d' });
  res.cookie(COOKIE_NAME, token, {
    httpOnly: true,
    sameSite: 'lax',
    secure: config.isProduction,
    maxAge: MAX_AGE_MS,
    path: '/',
  });
}

export function clearSessionCookie(res) {
  res.clearCookie(COOKIE_NAME, { httpOnly: true, sameSite: 'lax', secure: config.isProduction, path: '/' });
}

async function userFromRequest(req) {
  const token = req.cookies?.[COOKIE_NAME];
  if (!token) return null;
  try {
    const { sub } = jwt.verify(token, config.jwtSecret);
    return await User.findById(sub);
  } catch {
    return null;
  }
}

/** Attaches req.user when a valid session exists; never rejects. */
export async function optionalAuth(req, res, next) {
  try {
    req.user = await userFromRequest(req);
    next();
  } catch (err) {
    next(err);
  }
}

export async function requireAuth(req, res, next) {
  try {
    req.user = await userFromRequest(req);
    if (!req.user) throw new HttpError(401, 'Please log in to continue.');
    next();
  } catch (err) {
    next(err);
  }
}
