import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import {
  fixtureCapabilities,
  loadCapabilitySnapshot,
  type CapabilitySource,
} from '@/features/capabilities/capabilities';
import { RequestGeneration } from '@/lib/requestGeneration';
import { api } from '@/lib/api';
import type { ProviderCapabilities } from '@/types/api';

interface CapabilitiesContextValue {
  capabilities: ProviderCapabilities;
  source: CapabilitySource;
  loading: boolean;
  error?: Error;
  refresh(): Promise<void>;
}

const CapabilitiesContext = createContext<CapabilitiesContextValue | null>(null);

export function CapabilitiesProvider({ children }: { children: ReactNode }) {
  const generation = useRef(new RequestGeneration());
  const [capabilities, setCapabilities] = useState(fixtureCapabilities);
  const [source, setSource] = useState<CapabilitySource>('fixture-fallback');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error>();

  const refresh = useCallback(async () => {
    const sequence = generation.current.begin();
    setLoading(true);
    setError(undefined);
    setCapabilities(fixtureCapabilities);
    setSource('fixture-fallback');
    try {
      const snapshot = await loadCapabilitySnapshot(api.capabilities);
      if (!generation.current.isCurrent(sequence)) return;
      setCapabilities(snapshot.capabilities);
      setSource(snapshot.source);
    } catch (caught) {
      if (!generation.current.isCurrent(sequence)) return;
      setCapabilities(fixtureCapabilities);
      setSource('fixture-fallback');
      setError(caught instanceof Error ? caught : new Error('Provider capabilities are unavailable'));
    } finally {
      if (generation.current.isCurrent(sequence)) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const gate = generation.current;
    const sequence = gate.begin();
    let active = true;
    loadCapabilitySnapshot(api.capabilities)
      .then((snapshot) => {
        if (!active || !gate.isCurrent(sequence)) return;
        setCapabilities(snapshot.capabilities);
        setSource(snapshot.source);
      })
      .catch((caught: unknown) => {
        if (!active || !gate.isCurrent(sequence)) return;
        setCapabilities(fixtureCapabilities);
        setSource('fixture-fallback');
        setError(caught instanceof Error ? caught : new Error('Provider capabilities are unavailable'));
      })
      .finally(() => {
        if (active && gate.isCurrent(sequence)) setLoading(false);
      });
    return () => {
      active = false;
      gate.invalidate();
    };
  }, []);

  const value = useMemo(
    () => ({ capabilities, source, loading, error, refresh }),
    [capabilities, source, loading, error, refresh],
  );
  return <CapabilitiesContext.Provider value={value}>{children}</CapabilitiesContext.Provider>;
}

export function useCapabilities() {
  const value = useContext(CapabilitiesContext);
  if (!value) throw new Error('useCapabilities must be used inside CapabilitiesProvider');
  return value;
}
