import { useCallback, useEffect, useRef, useState } from 'react';

import { RequestGeneration } from '@/lib/requestGeneration';

interface ResourceState<T> {
  data?: T;
  error?: Error;
  loading: boolean;
  refreshing: boolean;
}

export function useResource<T>(loader: () => Promise<T>, dependencies: readonly unknown[] = []) {
  const mounted = useRef(true);
  const requestGeneration = useRef(new RequestGeneration());
  const [state, setState] = useState<ResourceState<T>>({ loading: true, refreshing: false });

  const load = useCallback(
    async (refresh = false) => {
      const sequence = requestGeneration.current.begin();
      setState((current) =>
        refresh
          ? { ...current, loading: false, refreshing: true, error: undefined }
          : { loading: true, refreshing: false },
      );
      try {
        const data = await loader();
        if (mounted.current && requestGeneration.current.isCurrent(sequence)) {
          setState({ data, loading: false, refreshing: false });
        }
        return data;
      } catch (error) {
        if (mounted.current && requestGeneration.current.isCurrent(sequence)) {
          setState((current) => ({
            ...current,
            loading: false,
            refreshing: false,
            error: error instanceof Error ? error : new Error('Something went wrong'),
          }));
        }
        return undefined;
      }
    },
    // The caller controls this dependency tuple, like useEffect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    dependencies,
  );

  useEffect(() => {
    const generation = requestGeneration.current;
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
      generation.invalidate();
    };
  }, [load]);

  const reload = useCallback(() => load(true), [load]);
  const setData = useCallback((data: T) => {
    requestGeneration.current.invalidate();
    setState({ data, loading: false, refreshing: false });
  }, []);

  return { ...state, reload, setData };
}
