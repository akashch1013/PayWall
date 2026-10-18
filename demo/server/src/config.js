import path from 'node:path';
import { fileURLToPath } from 'node:url';
import dotenv from 'dotenv';

const here = path.dirname(fileURLToPath(import.meta.url));
export const SERVER_ROOT = path.resolve(here, '..');

dotenv.config({ path: path.join(SERVER_ROOT, '.env'), quiet: true });

export const config = {
  mongoUri: process.env.MONGODB_URI,
  jwtSecret: process.env.JWT_SECRET,
  port: Number(process.env.PORT) || 4000,
  isProduction: process.env.NODE_ENV === 'production',
  uploadDir: process.env.UPLOAD_DIR || path.join(SERVER_ROOT, 'uploads'),
  seedImageDir: path.join(SERVER_ROOT, 'assets', 'seed-images'),
  clientDist: path.resolve(SERVER_ROOT, '..', 'client', 'dist'),
};

/** Exit with a readable message when a required setting is missing. */
export function assertConfig() {
  const missing = [];
  if (!config.mongoUri) missing.push('MONGODB_URI');
  if (!config.jwtSecret) missing.push('JWT_SECRET');
  if (missing.length) {
    console.error(
      `\n[config] Missing ${missing.join(', ')}.\n` +
        `Copy server/.env.example to server/.env and fill in the values (see README).\n`
    );
    process.exit(1);
  }
}
