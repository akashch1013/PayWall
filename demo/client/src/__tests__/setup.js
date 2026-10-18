import * as matchers from '@testing-library/jest-dom/matchers';
import { afterEach, expect, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

expect.extend(matchers);

// jsdom doesn't implement scrolling.
window.scrollTo = () => {};
Element.prototype.scrollIntoView = () => {};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
