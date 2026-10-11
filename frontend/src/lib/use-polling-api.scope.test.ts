import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePollingApi } from './use-polling-api';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe('polling data belongs to its request scope', () => {
  it('hides a loaded previous workspace immediately while the next workspace loads', async () => {
    const next = deferred<string[]>();
    const loader = vi.fn().mockResolvedValueOnce(['Workspace A private message']).mockReturnValueOnce(next.promise);
    const { result, rerender } = renderHook(({ workspace }) => usePollingApi(loader, [workspace]), {
      initialProps: { workspace: 'workspace-a' },
    });
    await act(async () => {});
    expect(result.current.data).toEqual(['Workspace A private message']);
    rerender({ workspace: 'workspace-b' });
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBeNull();
    await act(async () => { next.resolve(['Workspace B message']); });
    expect(result.current.data).toEqual(['Workspace B message']);
  });

  it('does not show cached workspace A data when workspace B is forbidden', async () => {
    const next = deferred<string[]>();
    const loader = vi.fn().mockResolvedValueOnce(['Private A']).mockReturnValueOnce(next.promise);
    const { result, rerender } = renderHook(({ workspace }) => usePollingApi(loader, [workspace]), {
      initialProps: { workspace: 'a' },
    });
    await act(async () => {});
    rerender({ workspace: 'b' });
    await act(async () => { next.reject(new Error('Access denied')); });
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe('Access denied');
    expect(result.current.loading).toBe(false);
  });

  it('clears old errors and results when a conversation filter changes', async () => {
    const next = deferred<string[]>();
    const loader = vi.fn().mockResolvedValueOnce(['Open conversation'])
      .mockRejectedValueOnce(new Error('Temporary open-list failure')).mockReturnValueOnce(next.promise);
    const { result, rerender } = renderHook(({ filter }) => usePollingApi(loader, ['workspace-a', filter]), {
      initialProps: { filter: 'open' },
    });
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(result.current.error).toBe('Temporary open-list failure');
    expect(result.current.data).toEqual(['Open conversation']);
    rerender({ filter: 'resolved' });
    expect(result.current.error).toBeNull();
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
    await act(async () => { next.resolve([]); });
    expect(result.current.data).toEqual([]);
  });

  it('does not reuse a previous result on a rapid A to B to A switch', async () => {
    const middle = deferred<string>();
    const last = deferred<string>();
    const loader = vi.fn().mockResolvedValueOnce('Old A')
      .mockReturnValueOnce(middle.promise).mockReturnValueOnce(last.promise);
    const { result, rerender } = renderHook(({ scope }) => usePollingApi(loader, [scope]), {
      initialProps: { scope: 'a' },
    });
    await act(async () => {});
    rerender({ scope: 'b' });
    rerender({ scope: 'a' });
    expect(result.current.data).toBeNull();
    await act(async () => { middle.resolve('Stale B'); });
    expect(result.current.data).toBeNull();
    await act(async () => { last.resolve('Fresh A'); });
    expect(result.current.data).toBe('Fresh A');
  });

  it('keeps same-scope data during refresh and avoids refetching equal dependency values', async () => {
    const pending = deferred<string>();
    const loader = vi.fn().mockResolvedValueOnce('Saved').mockReturnValueOnce(pending.promise);
    const { result, rerender } = renderHook(({ scope }) => usePollingApi(loader, [scope]), {
      initialProps: { scope: 'a' },
    });
    await act(async () => {});
    rerender({ scope: 'a' });
    expect(loader).toHaveBeenCalledTimes(1);
    act(() => result.current.reload());
    expect(result.current.data).toBe('Saved');
    await act(async () => pending.resolve('Updated'));
    expect(result.current.data).toBe('Updated');
  });
});
