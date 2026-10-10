import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WebsiteCMSPage } from './WebsiteCMSPage';

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
}));

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

describe('CMS blog article creation', () => {
  beforeEach(() => {
    mocks.request.mockImplementation(async (path: string, options?: { method?: string; body?: string }) => {
      if (path === '/site-cms/pages' && !options) return [];
      if (path === '/site-forms' && !options) return [];
      if (path === '/agents' && !options) return [];
      if (path === '/site-cms/redirects' && !options) return [];
      if (path === '/site-cms/menu') return {
        draftVersion: 0, publishedVersion: null, document: { items: [] },
      };
      if (path.startsWith('/site-analytics/summary')) {
        return { days: 30, pageViews: 0, ctaClicks: 0, pages: [] };
      }
      if (path === '/site-cms/pages' && options?.method === 'POST') {
        const document = JSON.parse(options.body || '{}');
        return {
          id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          slug: document.slug, title: document.title,
          status: 'draft', draftVersion: 1, publishedVersion: null,
          document,
        };
      }
      if (path.includes('/revisions')) return [{ version: 1, title: 'Example article', isPublished: false }];
      throw new Error('Unexpected request ' + path);
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('requires a real author, category and summary before creating an article', async () => {
    const user = userEvent.setup();
    render(<WebsiteCMSPage />);

    await screen.findByText('No pages yet. Create one below.');
    const createForm = screen.getByRole('button', { name: 'Create draft' }).closest('form');
    if (!createForm) throw new Error('Missing CMS create form');

    await user.selectOptions(within(createForm).getByLabelText('Content type'), 'article');
    expect(within(createForm).getByLabelText('Verified author')).toBeRequired();
    expect(within(createForm).getByLabelText('Category')).toBeRequired();
    expect(within(createForm).getByLabelText('Article summary')).toBeRequired();

    await user.clear(within(createForm).getByLabelText('URL slug'));
    await user.type(within(createForm).getByLabelText('URL slug'), 'product-news');
    await user.type(within(createForm).getByLabelText('Verified author'), 'Editorial Board');
    await user.type(within(createForm).getByLabelText('Category'), 'Product updates');
    await user.type(within(createForm).getByLabelText('Article summary'), 'Reliable product news.');
    await user.click(within(createForm).getByRole('button', { name: 'Create draft' }));

    await waitFor(() => {
      expect(mocks.request).toHaveBeenCalledWith(
        '/site-cms/pages', expect.objectContaining({ method: 'POST' }),
      );
    });
    const post = mocks.request.mock.calls.find(
      ([path, opts]) => path === '/site-cms/pages' && opts?.method === 'POST',
    );
    const document = JSON.parse(post?.[1]?.body || '{}');
    expect(document.content_type).toBe('article');
    expect(document.blog).toMatchObject({
      author: 'Editorial Board', category: 'Product updates',
      summary: 'Reliable product news.',
    });
    expect(screen.getByText('Blog article editor')).toBeInTheDocument();
  });

  it('keeps ordinary CMS pages separate from the article metadata form', async () => {
    render(<WebsiteCMSPage />);
    await screen.findByText('No pages yet. Create one below.');
    const createForm = screen.getByRole('button', { name: 'Create draft' }).closest('form');
    if (!createForm) throw new Error('Missing CMS create form');
    expect(within(createForm).queryByLabelText('Verified author')).toBeNull();
    expect(within(createForm).getByLabelText('Content type')).toHaveValue('page');
  });
});
