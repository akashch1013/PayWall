import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    setupFiles: ['./test/setup.js'],
    // One in-memory mongod per file; run files sequentially to keep resource use low.
    fileParallelism: false,
    testTimeout: 30000,
    hookTimeout: 120000,
  },
});
