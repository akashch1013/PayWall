export class ApiError extends Error {
  constructor(status, message, fields = {}) {
    super(message);
    this.status = status;
    this.fields = fields;
  }
}

const OFFLINE_MESSAGE = "Can't reach the ReWear server. Make sure the API is running, then try again.";

/**
 * Calls the ReWear API. Pass `body` for JSON or `form` for multipart FormData.
 * Throws ApiError with the server's message and per-field errors.
 */
export async function api(path, { method = 'GET', body, form, signal } = {}) {
  const init = { method, credentials: 'same-origin', headers: { Accept: 'application/json' }, signal };
  if (form) init.body = form;
  else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(path, init);
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new ApiError(0, OFFLINE_MESSAGE);
  }
  if (res.status === 204) return null;

  let data = null;
  try {
    data = await res.json();
  } catch {
    // Non-JSON body (for example the dev proxy failing to reach the API).
  }
  if (!res.ok) {
    const message = data?.error || (res.status >= 500 ? OFFLINE_MESSAGE : `Request failed (${res.status}).`);
    throw new ApiError(res.status, message, data?.fields || {});
  }
  return data;
}
