import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { makeListing, mockApi, renderApp } from './helpers.jsx';

describe('Browse', () => {
  it('shows listings from the API and filters by category through the API', async () => {
    const fetchMock = mockApi({
      'GET /api/auth/me': () => [200, { user: null }],
      'GET /api/listings': (url) =>
        url.searchParams.get('category') === 'jackets'
          ? [200, { listings: [makeListing({ id: 'l2', title: 'Denim Jacket', category: 'jackets', price: 599 })] }]
          : [200, { listings: [makeListing(), makeListing({ id: 'l3', title: 'Linen Shirt', category: 'tops', status: 'sold' })] }],
    });
    renderApp('/');

    expect(await screen.findByText('Floral Summer Dress')).toBeInTheDocument();
    const shirtCard = screen.getByRole('link', { name: /Linen Shirt/ });
    expect(within(shirtCard).getByText('Sold')).toBeInTheDocument();
    const dressCard = screen.getByRole('link', { name: /Floral Summer Dress/ });
    expect(within(dressCard).getByText('₹349')).toBeInTheDocument();
    expect(within(dressCard).getByText('Available')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Jackets' }));
    expect(await screen.findByText('Denim Jacket')).toBeInTheDocument();
    expect(screen.queryByText('Floral Summer Dress')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Jackets' })).toHaveAttribute('aria-pressed', 'true');

    const listingCalls = fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.startsWith('/api/listings'));
    expect(listingCalls.at(-1)).toContain('category=jackets');
  });

  it('shows an empty state with a working clear-filters action', async () => {
    mockApi({
      'GET /api/auth/me': () => [200, { user: null }],
      'GET /api/listings': (url) => [200, { listings: url.searchParams.get('q') ? [] : [makeListing()] }],
    });
    renderApp('/?q=zzz');
    expect(await screen.findByText('No listings match')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(await screen.findByText('Floral Summer Dress')).toBeInTheDocument();
  });

  it('shows a recoverable error when the API fails', async () => {
    let fail = true;
    mockApi({
      'GET /api/auth/me': () => [200, { user: null }],
      'GET /api/listings': () => (fail ? [503, { error: 'The database is unavailable. Please try again shortly.' }] : [200, { listings: [makeListing()] }]),
    });
    renderApp('/');
    expect(await screen.findByText(/database is unavailable/)).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(screen.getByText('Floral Summer Dress')).toBeInTheDocument());
  });
});
