import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterAll, afterEach, beforeAll } from 'vitest';
import mongoose from 'mongoose';

// Isolated settings: tests never touch server/.env's database or upload folder.
process.env.JWT_SECRET = 'test-secret';
process.env.UPLOAD_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'rewear-uploads-'));

let mongod;

beforeAll(async () => {
  let uri = process.env.TEST_MONGODB_URI;
  if (!uri) {
    const { MongoMemoryServer } = await import('mongodb-memory-server');
    mongod = await MongoMemoryServer.create();
    uri = mongod.getUri('rewear_test');
  }
  await mongoose.connect(uri);
  await mongoose.connection.dropDatabase();
  await Promise.all(Object.values(mongoose.models).map((m) => m.init()));
});

afterEach(async () => {
  await Promise.all(Object.values(mongoose.connection.collections).map((c) => c.deleteMany({})));
  for (const f of fs.readdirSync(process.env.UPLOAD_DIR)) fs.rmSync(path.join(process.env.UPLOAD_DIR, f));
});

afterAll(async () => {
  await mongoose.disconnect();
  await mongod?.stop();
});
