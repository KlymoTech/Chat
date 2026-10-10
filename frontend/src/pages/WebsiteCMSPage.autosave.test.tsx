import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api';
import { WebsiteCMSPage } from './WebsiteCMSPage';

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('@/lib/api', () => ({
  request: mocks.request,
  apiConfig: { baseUrl: '/api/v1' },
  ApiError: class ApiError extends Error {
    constructor(message: string, readonly status: number) { super(message); }
  },
}));
vi.mock('@/components/providers', () => ({
  useWorkspace: () => ({ activeWorkspace: { id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' } }),
}));

const firstDocument = {
  schema_version: 1,
  slug: 'about-page',
  title: 'About page',
  content_type: 'page',
  blog: null,
  seo: { description: '', canonical_url: null, indexable: false },
  nodes: [
    { id: 'hero', kind: 'section', children: [
      { id: 'heading', kind: 'heading', text: 'About us' },
      { id: 'body', kind: 'paragraph', text: 'Our story.' },
    ] },
  ],
};

const firstPage = () => ({
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  slug: 'about-page',
  title: 'About page',
  status: 'draft',
  draftVersion: 1,
  publishedVersion: null,
  document: structuredClone(firstDocument),
});

describe('CMS acknowledged autosave and conflict recovery', () => {
  let storedPage = firstPage();
  let rejectWrite = false;

  beforeEach(() => {
    storedPage = firstPage();
    rejectWrite = false;
    mocks.request.mockImplementation(async (path: string, options?: { method?: string; body?: string }) => {
      if (path === '/site-cms/pages' && !options) return [structuredClone(storedPage)];
      if (path === '/site-forms' && !options) return [];
      if (path === '/agents' && !options) return [];
      if (path === '/site-cms/redirects' && !options) return [];
      if (path === '/site-cms/menu') return {
        draftVersion: 0, publishedVersion: null, document: { items: [] },
      };
      if (path.startsWith('/site-analytics/summary')) {
        return { days: 30, pageViews: 0, ctaClicks: 0, pages: [] };
      }
      if (path === '/site-cms/pages/import' && options?.method === 'POST') {
        const manifest = JSON.parse(options.body ?? '{}') as {
          new_slug: string; new_title: string; page: typeof firstDocument;
        };
        return {
          id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
          slug: manifest.new_slug,
          title: manifest.new_title,
          status: 'draft',
          draftVersion: 1,
          publishedVersion: null,
          document: {
            ...manifest.page,
            slug: manifest.new_slug,
            title: manifest.new_title,
            seo: { indexable: false, canonical_url: null, description: '' },
          },
        };
      }
      if (path.endsWith('/revisions')) return [
        { version: storedPage.draftVersion, title: storedPage.title, isPublished: false },
      ];
      if (path === '/site-cms/pages/' + storedPage.id && options?.method === 'PUT') {
        if (rejectWrite) throw new ApiError('Page has changed; reload before saving', 409);
        const parsed = JSON.parse(options.body ?? '{}') as {
          expected_version: number; document: typeof firstDocument;
        };
        if (parsed.expected_version !== storedPage.draftVersion) throw new ApiError('Stale revision', 409);
        storedPage = {
          ...storedPage,
          draftVersion: storedPage.draftVersion + 1,
          title: parsed.document.title,
          document: structuredClone(parsed.document),
        };
        return structuredClone(storedPage);
      }
      throw new Error('Unexpected API request ' + path);
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  const openPage = async () => {
    render(<WebsiteCMSPage />);
    const page = await screen.findByRole('button', { name: /About page.*about-page/i });
    fireEvent.click(page);
    return screen.getByLabelText('Page title') as HTMLInputElement;
  };

  it('supports undo and redo without publishing unacknowledged edits', async () => {
    const input = await openPage();
    fireEvent.change(input, { target: { value: 'Changed heading' } });
    expect(input.value).toBe('Changed heading');
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(input.value).toBe('About page');
    fireEvent.click(screen.getByRole('button', { name: 'Redo' }));
    expect(input.value).toBe('Changed heading');
    expect(mocks.request.mock.calls.some(([path, opts]) =>
      path === '/site-cms/pages/' + storedPage.id && opts?.method === 'PUT',
    )).toBe(false);
  });

  it('autosaves after a pause and reports the acknowledged database revision', async () => {
    const input = await openPage();
    vi.useFakeTimers();
    fireEvent.change(input, { target: { value: 'Updated homepage' } });
    expect(screen.getByText(/Autosave will run after a short pause/)).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3200);
    });
    const savedCalls = mocks.request.mock.calls.filter(([path, opts]) =>
      path === '/site-cms/pages/' + storedPage.id && opts?.method === 'PUT',
    );
    expect(savedCalls).toHaveLength(1);
    expect(JSON.parse(savedCalls[0]![1].body).expected_version).toBe(1);
    expect(storedPage.draftVersion).toBe(2);
    expect(screen.getByText(/Saved as server revision 2/)).toBeInTheDocument();
    expect(screen.queryByText(/Autosave will run after a short pause/)).not.toBeInTheDocument();
  });

  it('does not send unsaved edits while offline and retries after reconnect', async () => {
    const input = await openPage();
    vi.useFakeTimers();
    act(() => {
      window.dispatchEvent(new Event('offline'));
      fireEvent.change(input, { target: { value: 'Edited offline' } });
    });
    expect(screen.getByText(/Offline — nothing is being sent/)).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(3500); });
    expect(mocks.request.mock.calls.some(([path, opts]) =>
      path === '/site-cms/pages/' + storedPage.id && opts?.method === 'PUT',
    )).toBe(false);

    act(() => { window.dispatchEvent(new Event('online')); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3500); });
    expect(storedPage.document.title).toBe('Edited offline');
    expect(storedPage.draftVersion).toBe(2);
  });

  it('stops saving after a version conflict and offers safe export before reload', async () => {
    const input = await openPage();
    rejectWrite = true;
    fireEvent.change(input, { target: { value: 'Important local edit' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save now' }));
    });
    expect(screen.getByText(/Version conflict — no changes have been overwritten/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export unsaved draft' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Reload server version' })).toBeEnabled();
    expect(input.value).toBe('Important local edit');
    expect(screen.getByRole('button', { name: 'Save now' })).toBeDisabled();
    expect(screen.getByText(/Local draft vs. latest server revision 1/)).toBeInTheDocument();
    expect(screen.getByRole('table', { name: /Unresolved content differences/ })).toBeInTheDocument();
    expect(screen.getByText('Important local edit')).toBeInTheDocument();

    const confirmed = vi.spyOn(window, 'confirm').mockReturnValue(true);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save as new draft' }));
    });
    const fork = mocks.request.mock.calls.find(([path, options]) =>
      path === '/site-cms/pages/import' && options?.method === 'POST',
    );
    expect(fork).toBeDefined();
    const body = JSON.parse(fork![1].body);
    expect(body.page.title).toBe('Important local edit');
    expect(body.new_slug).toBe('about-page-recovered');
    expect(screen.queryByText(/Version conflict — no changes have been overwritten/)).not.toBeInTheDocument();
    confirmed.mockRestore();
  });
});
