import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { buyer, makeListing, mockApi, renderApp } from './helpers.jsx';

const posts = (fetchMock) => fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST');

describe('Sell form', () => {
  it('redirects logged-out visitors to log in', async () => {
    mockApi({ 'GET /api/auth/me': () => [200, { user: null }] });
    renderApp('/sell');
    expect(await screen.findByText('Please log in to continue.')).toBeInTheDocument();
    expect(screen.getByLabelText(/Email address/)).toBeInTheDocument();
  });

  it('shows required-field errors without calling the API', async () => {
    const fetchMock = mockApi({ 'GET /api/auth/me': () => [200, { user: buyer }] });
    renderApp('/sell');
    await userEvent.click(await screen.findByRole('button', { name: 'Publish listing' }));

    expect(screen.getByText('Title is required.')).toBeInTheDocument();
    expect(screen.getByText('Choose a category.')).toBeInTheDocument();
    expect(screen.getByText('Choose a condition.')).toBeInTheDocument();
    expect(screen.getByText('Price is required.')).toBeInTheDocument();
    expect(screen.getByLabelText(/Item title/)).toHaveAttribute('aria-invalid', 'true');
    expect(posts(fetchMock)).toHaveLength(0);
  });

  it('rejects oversized and non-image photos before upload', async () => {
    mockApi({ 'GET /api/auth/me': () => [200, { user: buyer }] });
    renderApp('/sell');
    const input = await screen.findByLabelText(/Photo/);

    const big = new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'big.png', { type: 'image/png' });
    await userEvent.upload(input, big);
    expect(screen.getByText('Image must be 5 MB or smaller.')).toBeInTheDocument();

    const pdf = new File(['%PDF'], 'doc.pdf', { type: 'application/pdf' });
    await userEvent.upload(input, pdf, { applyAccept: false });
    expect(screen.getByText('Photo must be a JPG, PNG, WEBP or GIF image.')).toBeInTheDocument();
  });

  it('submits a valid listing and shows server field errors', async () => {
    let attempt = 0;
    const fetchMock = mockApi({
      'GET /api/auth/me': () => [200, { user: buyer }],
      'POST /api/listings': () => {
        attempt += 1;
        return attempt === 1
          ? [400, { error: 'Please fix the highlighted fields.', fields: { title: 'Title must be 120 characters or fewer.' } }]
          : [201, { listing: makeListing({ id: 'new1', title: 'Wool Coat', seller: buyer }) }];
      },
      'GET /api/listings/new1': () => [200, { listing: makeListing({ id: 'new1', title: 'Wool Coat', seller: buyer }) }],
    });
    renderApp('/sell');

    await userEvent.type(await screen.findByLabelText(/Item title/), 'Wool Coat');
    await userEvent.selectOptions(screen.getByLabelText(/Category/), 'jackets');
    await userEvent.selectOptions(screen.getByLabelText(/Condition/), 'good');
    await userEvent.type(screen.getByLabelText(/Price/), '1200');
    await userEvent.click(screen.getByRole('button', { name: 'Publish listing' }));

    expect(await screen.findByText('Title must be 120 characters or fewer.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Publish listing' }));
    expect(await screen.findByRole('heading', { name: 'Wool Coat' })).toBeInTheDocument();

    const body = posts(fetchMock).at(-1)[1].body;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get('price')).toBe('1200');
    expect(body.get('category')).toBe('jackets');
  });
});
