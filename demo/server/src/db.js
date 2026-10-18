import mongoose from 'mongoose';

/** Hide credentials so connection errors are safe to print. */
export function redactUri(uri) {
  return String(uri).replace(/\/\/[^@/]*@/, '//<credentials>@');
}

export async function connectDb(uri) {
  try {
    await mongoose.connect(uri, { serverSelectionTimeoutMS: 8000 });
    await Promise.all(Object.values(mongoose.models).map((m) => m.init()));
  } catch (err) {
    console.error(
      `\n[db] Cannot reach MongoDB at ${redactUri(uri)}\n` +
        `     ${err.message}\n\n` +
        `     - Local MongoDB: make sure mongod is running on the host/port in MONGODB_URI.\n` +
        `     - MongoDB Atlas: check the user/password and that this machine's IP is on the\n` +
        `       cluster's Network Access list.\n` +
        `     ReWear does not fall back to mock data; it needs a real database.\n`
    );
    process.exit(1);
  }
}
