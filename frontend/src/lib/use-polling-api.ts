import { useCallback, useEffect, useRef, useState } from 'react';
import type { AsyncState } from '@/lib/use-api';

interface Snapshot<T> {
  scope: readonly unknown[];
  data: T | null;
  loading: boolean;
  error: string | null;
}

function sameScope(left: readonly unknown[], right: readonly unknown[]): boolean {
  return left.length === right.length && left.every((value, index) => Object.is(value, right[index]));
}

/** Retain successful data during background refreshes, never across request scopes. */
export function usePollingApi<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  dependencies: readonly unknown[],
  interval = 3000,
): AsyncState<T> {
  const [scope, setScope] = useState<readonly unknown[]>(() => [...dependencies]);
  // Reset the request identity during render so no child commits the previous
  // workspace/filter's records. A new equal-valued dependency array is not a change.
  if (!sameScope(scope, dependencies)) setScope([...dependencies]);
  const [snapshot, setSnapshot] = useState<Snapshot<T>>(() => ({
    scope, data: null, loading: true, error: null,
  }));
  const refreshRef = useRef<() => void>(() => {});
  const reload = useCallback(() => refreshRef.current(), []);

  useEffect(() => {
    let active = true;
    let pending = false;
    let refreshAgain = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    const refresh = async () => {
      clearTimeout(timer);
      if (!active) return;
      if (pending) { refreshAgain = true; return; }
      pending = true;
      controller = new AbortController();
      try {
        const next = await loader(controller.signal);
        if (active) setSnapshot({ scope, data: next, loading: false, error: null });
      } catch (reason) {
        if (active && !controller.signal.aborted) {
          setSnapshot((previous) => ({
            scope,
            data: previous.scope === scope ? previous.data : null,
            loading: false,
            error: reason instanceof Error ? reason.message : 'Could not update conversations',
          }));
        }
      } finally {
        pending = false;
        if (active) {
          if (refreshAgain) {
            refreshAgain = false;
            void refresh();
          } else if (!document.hidden) {
            timer = setTimeout(() => void refresh(), interval);
          }
        }
      }
    };
    const resume = () => { if (!document.hidden) void refresh(); };
    const visibilityChanged = () => {
      if (document.hidden) clearTimeout(timer);
      else resume();
    };
    refreshRef.current = () => { void refresh(); };
    document.addEventListener('visibilitychange', visibilityChanged);
    window.addEventListener('focus', resume);
    window.addEventListener('online', resume);
    void refresh();
    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', visibilityChanged);
      window.removeEventListener('focus', resume);
      window.removeEventListener('online', resume);
    };
    // The caller supplies all request-scope values in dependencies. The stable
    // scope array above changes only when those values change (Object.is).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, interval]);

  return snapshot.scope === scope && sameScope(scope, dependencies)
    ? { data: snapshot.data, loading: snapshot.loading, error: snapshot.error, reload }
    : { data: null, loading: true, error: null, reload };
}
