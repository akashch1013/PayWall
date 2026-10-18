import { assertConfig, config } from './config.js';
import { connectDb, redactUri } from './db.js';
import { createApp } from './app.js';
import './models/User.js';
import './models/Listing.js';
import './models/Order.js';

assertConfig();
await connectDb(config.mongoUri);
console.log(`[db] Connected to ${redactUri(config.mongoUri)}`);

createApp().listen(config.port, () => {
  console.log(`[api] ReWear API listening on http://localhost:${config.port}`);
});
