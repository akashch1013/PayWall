import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import App from '../App.jsx';
import { AuthProvider } from '../AuthContext.jsx';
import { ToastProvider } from '../components/Toast.jsx';

const json = (status, body) =>
  Promise.resolve(new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }));

/**
 * Replaces fetch with a small router: `routes` maps "METHOD /path" (path without query)
 * to a handler (url, init) => [status, body].
 */
export function mockApi(routes) {
  const fetchMock = vi.fn((input, init = {}) => {
    const url = new URL(input, 'http://localhost');
    const key = `${init.method ?? 'GET'} ${url.pathname}`;
    const handler = routes[key];
    if (!handler) return json(404, { error: `No mock for ${key}` });
    const [status, body] = handler(url, init);
    return json(status, body);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

export function renderApp(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>
  );
}

export const buyer = { id: 'u-buyer', name: 'Asha Buyer', email: 'asha@example.com' };
export const seller = { id: 'u-seller', name: 'Ravi Seller' };

export function makeListing(overrides = {}) {
  return {
    id: 'l1',
    title: 'Floral Summer Dress',
    description: 'Light cotton dress.',
    category: 'dresses',
    condition: 'like_new',
    size: 'M',
    price: 349,
    imageUrl: null,
    status: 'available',
    isSample: false,
    seller,
    createdAt: '2026-10-01T10:00:00.000Z',
    ...overrides,
  };
}
