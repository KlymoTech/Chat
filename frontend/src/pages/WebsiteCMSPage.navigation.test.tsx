import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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

const publishPage = (slug: string, title: string, published = true) => ({
  id: 'page-' + slug, slug, title,
  status: published ? 'published' : 'draft',
  draftVersion: 1,
  publishedVersion: published ? 1 : null,
  document: {
    schema_version: 1, slug, title, nodes: [],
    seo: { indexable: false, canonical_url: null, description: '' },
  },
});

describe('CMS primary navigation editor', () => {
  let menu: {
    draftVersion: number;
    publishedVersion: number | null;
    document: { items: Array<{ id: string; label: string; slug: string }> };
  };

  beforeEach(() => {
    menu = { draftVersion: 0, publishedVersion: null, document: { items: [] } };
    mocks.request.mockImplementation(async (path: string, options?: { method?: string; body?: string }) => {
      if (path === '/site-cms/pages' && !options) return [
        publishPage('home', 'Home'), publishPage('about', 'About us'),
        publishPage('hidden', 'Unpublished page', false),
      ];
      if (path.startsWith('/site-analytics/summary')) {
        return { days: 30, pageViews: 0, ctaClicks: 0, pages: [] };
      }
      if (path === '/site-forms' && !options) return [];
      if (path === '/agents' && !options) return [];
      if (path === '/site-cms/redirects' && !options) return [];
      if (path === '/site-cms/menu' && !options) {
        return structuredClone(menu);
      }
      if (path === '/site-cms/menu/revisions') {
        return menu.draftVersion
          ? [{ version: menu.draftVersion, createdAt: new Date().toISOString(),
            isPublished: menu.publishedVersion === menu.draftVersion }]
          : [];
      }
      if (path === '/site-cms/menu' && options?.method === 'PUT') {
        const body = JSON.parse(options.body ?? '{}');
        if (body.expected_version !== menu.draftVersion) {
          throw new Error('Version conflict');
        }
        menu = { ...menu, draftVersion: menu.draftVersion + 1,
          document: structuredClone(body.document) };
        return structuredClone(menu);
      }
      if (path === '/site-cms/menu/publish' && options?.method === 'POST') {
        const body = JSON.parse(options.body ?? '{}');
        if (body.expected_version !== menu.draftVersion) throw new Error('Stale menu');
        menu = { ...menu, publishedVersion: menu.draftVersion };
        return structuredClone(menu);
      }
      throw new Error('Unexpected API request: ' + path);
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('only offers published pages, saves with an expected revision and publishes separately', async () => {
    render(<WebsiteCMSPage />);
    const selector = await screen.findByLabelText('Published page to add');
    await waitFor(() => expect(selector).toBeEnabled());
    expect(screen.getByRole('option', { name: /About us/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Unpublished page/ })).toBeNull();
    const publish = screen.getByRole('button', { name: 'Publish navigation' });
    expect(publish).toBeDisabled();

    fireEvent.change(selector, { target: { value: 'about' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add link' }));
    const label = screen.getByLabelText('Link 1 label');
    expect(label).toHaveValue('About us');

    fireEvent.change(label, { target: { value: 'Who we are' } });
    expect(publish).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save menu draft' }));
    await waitFor(() => expect(menu.draftVersion).toBe(1));
    const save = mocks.request.mock.calls.find(([path, options]) =>
      path === '/site-cms/menu' && options?.method === 'PUT',
    );
    expect(save).toBeDefined();
    expect(JSON.parse(save![1].body)).toMatchObject({
      expected_version: 0,
      document: { items: [{ label: 'Who we are', slug: 'about' }] },
    });
    await waitFor(() => expect(publish).toBeEnabled());
    fireEvent.click(publish);
    await waitFor(() => expect(menu.publishedVersion).toBe(1));
    expect(screen.getByText(/Navigation revision 1 is live/)).toBeInTheDocument();
  });

  it('supports keyboard-accessible reorder and removal without a parallel editor', async () => {
    render(<WebsiteCMSPage />);
    const selector = await screen.findByLabelText('Published page to add');
    await waitFor(() => expect(selector).toBeEnabled());
    fireEvent.change(selector, { target: { value: 'home' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add link' }));
    fireEvent.change(selector, { target: { value: 'about' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add link' }));

    expect(screen.getByLabelText('Link 1 label')).toHaveValue('Home');
    fireEvent.click(screen.getByRole('button', { name: 'Move menu link 2 up' }));
    expect(screen.getByLabelText('Link 1 label')).toHaveValue('About us');
    fireEvent.click(screen.getByRole('button', { name: 'Remove menu link 2' }));
    expect(screen.getAllByLabelText(/Link \d+ label/)).toHaveLength(1);
    expect(screen.getByLabelText('Link 1 label')).toHaveValue('About us');
    expect(screen.getByRole('button', { name: 'Publish navigation' })).toBeDisabled();
  });
});
