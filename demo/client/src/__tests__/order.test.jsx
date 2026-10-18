import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { buyer, makeListing, mockApi, renderApp, seller } from './helpers.jsx';

describe('Demo order', () => {
  it('confirms with no-payment wording and shows the demo confirmation', async () => {
    const fetchMock = mockApi({
      'GET /api/auth/me': () => [200, { user: buyer }],
      'GET /api/listings/l1': () => [200, { listing: makeListing() }],
      'POST /api/orders': () => [201, { order: { id: 'o1', listing: 'l1', item: { title: 'Floral Summer Dress', price: 349 } } }],
    });
    renderApp('/listings/l1');

    await userEvent.click(await screen.findByRole('button', { name: 'Place demo order' }));
    const dialog = screen.getByRole('dialog', { name: 'Place a demo order?' });
    expect(within(dialog).getByText(/No payment will be taken/)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/card/i)).not.toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole('button', { name: 'Place demo order' }));
    expect(await screen.findByText(/Demo order placed\./)).toBeInTheDocument();
    expect(screen.getByText(/No real payment was processed/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View my orders' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    const [, init] = fetchMock.mock.calls.find(([, i]) => i?.method === 'POST');
    expect(JSON.parse(init.body)).toEqual({ listingId: 'l1' });
  });

  it('shows the server message when the item was already sold', async () => {
    mockApi({
      'GET /api/auth/me': () => [200, { user: buyer }],
      'GET /api/listings/l1': () => [200, { listing: makeListing() }],
      'POST /api/orders': () => [409, { error: 'Sorry, this item has already been sold.' }],
    });
    renderApp('/listings/l1');
    await userEvent.click(await screen.findByRole('button', { name: 'Place demo order' }));
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Place demo order' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('already been sold');
  });

  it('offers edit/delete instead of ordering on your own listing', async () => {
    mockApi({
      'GET /api/auth/me': () => [200, { user: { ...seller, email: 'r@example.com' } }],
      'GET /api/listings/l1': () => [200, { listing: makeListing() }],
    });
    renderApp('/listings/l1');
    expect(await screen.findByRole('link', { name: 'Edit listing' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Place demo order' })).not.toBeInTheDocument();
  });

  it('asks logged-out visitors to log in before ordering', async () => {
    mockApi({
      'GET /api/auth/me': () => [200, { user: null }],
      'GET /api/listings/l1': () => [200, { listing: makeListing() }],
    });
    renderApp('/listings/l1');
    expect(await screen.findByRole('link', { name: 'Log in to order' })).toBeInTheDocument();
  });
});
