import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import multer from 'multer';
import { config } from '../config.js';
import { HttpError } from './errors.js';

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
const TYPES = {
  'image/jpeg': '.jpg',
  'image/png': '.png',
  'image/webp': '.webp',
  'image/gif': '.gif',
};
export const INVALID_TYPE_MESSAGE = 'Photo must be a JPG, PNG, WEBP or GIF image.';

const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    fs.mkdir(config.uploadDir, { recursive: true }).then(() => cb(null, config.uploadDir), cb);
  },
  filename: (req, file, cb) => cb(null, `${crypto.randomUUID()}${TYPES[file.mimetype]}`),
});

const multerUpload = multer({
  storage,
  limits: { fileSize: MAX_UPLOAD_BYTES, files: 1 },
  fileFilter: (req, file, cb) => {
    if (TYPES[file.mimetype]) cb(null, true);
    else cb(new HttpError(400, INVALID_TYPE_MESSAGE, { photo: INVALID_TYPE_MESSAGE }));
  },
}).single('photo');

/** Checks the file's leading bytes so a renamed non-image can't pass as one. */
async function looksLikeImage(filePath, mimetype) {
  const handle = await fs.open(filePath, 'r');
  try {
    const { buffer, bytesRead } = await handle.read(Buffer.alloc(12), 0, 12, 0);
    const b = buffer.subarray(0, bytesRead);
    switch (mimetype) {
      case 'image/jpeg':
        return b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff;
      case 'image/png':
        return b.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
      case 'image/gif':
        return b.subarray(0, 4).toString('ascii') === 'GIF8';
      case 'image/webp':
        return b.subarray(0, 4).toString('ascii') === 'RIFF' && b.subarray(8, 12).toString('ascii') === 'WEBP';
      default:
        return false;
    }
  } finally {
    await handle.close();
  }
}

/** Parses an optional single "photo" upload and validates its contents. */
export function photoUpload(req, res, next) {
  multerUpload(req, res, async (err) => {
    if (err) return next(err);
    if (!req.file) return next();
    try {
      if (!(await looksLikeImage(req.file.path, req.file.mimetype))) {
        await removeFile(req.file.path);
        req.file = undefined;
        return next(new HttpError(400, INVALID_TYPE_MESSAGE, { photo: INVALID_TYPE_MESSAGE }));
      }
      next();
    } catch (e) {
      next(e);
    }
  });
}

export async function removeFile(filePath) {
  if (!filePath) return;
  await fs.rm(filePath, { force: true }).catch(() => {});
}

/** Deletes a stored upload given its public URL; ignores seed images and other paths. */
export async function removeUploadByUrl(url) {
  if (!url || !url.startsWith('/uploads/')) return;
  const name = path.basename(url);
  await removeFile(path.join(config.uploadDir, name));
}

export const uploadUrlFor = (file) => `/uploads/${file.filename}`;
