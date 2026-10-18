import fs from 'node:fs';
import path from 'node:path';
import express from 'express';
import cookieParser from 'cookie-parser';
import mongoose from 'mongoose';
import { config } from './config.js';
import { errorHandler, notFound } from './middleware/errors.js';
import { router as authRouter } from './routes/auth.js';
import { router as listingsRouter } from './routes/listings.js';
import { router as ordersRouter } from './routes/orders.js';

export function createApp() {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '100kb' }));
  app.use(cookieParser());

  app.get('/api/health', (req, res) => {
    const connected = mongoose.connection.readyState === 1;
    res.status(connected ? 200 : 503).json({ ok: connected, db: connected ? 'connected' : 'disconnected' });
  });
  app.use('/api/auth', authRouter);
  app.use('/api/listings', listingsRouter);
  app.use('/api/orders', ordersRouter);
  app.use('/api', notFound);

  const staticOpts = { maxAge: '1d', fallthrough: false };
  app.use('/uploads', express.static(config.uploadDir, { ...staticOpts, dotfiles: 'deny' }));
  app.use('/seed-images', express.static(config.seedImageDir, staticOpts));

  // In production, the API also serves the built React app.
  const indexHtml = path.join(config.clientDist, 'index.html');
  if (config.isProduction && fs.existsSync(indexHtml)) {
    app.use(express.static(config.clientDist));
    app.get('*', (req, res) => res.sendFile(indexHtml));
  }

  app.use((err, req, res, next) => {
    // express.static with fallthrough:false reports missing files as 404 errors.
    if (err.status === 404 || err.statusCode === 404) return res.status(404).json({ error: 'Not found' });
    next(err);
  });
  app.use(notFound);
  app.use(errorHandler);
  return app;
}
