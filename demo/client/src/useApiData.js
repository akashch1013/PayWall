import { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';

/** Loads a GET endpoint and exposes loading/error state, a reload function and a local setter. */
export function useApiData(path) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null });
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading', data: null, error: null });
    api(path, { signal: controller.signal })
      .then((data) => setState({ status: 'ready', data, error: null }))
      .catch((err) => {
        if (err.name !== 'AbortError') setState({ status: 'error', data: null, error: err });
      });
    return () => controller.abort();
  }, [path, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
  const setData = useCallback((update) => setState((s) => ({ ...s, data: update(s.data) })), []);
  return { ...state, reload, setData };
}
