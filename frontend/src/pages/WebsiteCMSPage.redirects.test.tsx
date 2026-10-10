import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WebsiteCMSPage } from './WebsiteCMSPage';

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('@/lib/api', () => ({
  request: mocks.request, apiConfig: { baseUrl: '/api/v1' },
  ApiError: class ApiError extends Error {
    constructor(message: string, readonly status: number) { super(message); }
  },
}));
vi.mock('@/components/providers', () => ({
  useWorkspace: () => ({ activeWorkspace: { id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' } }),
}));

const page = (slug: string, published: boolean) => ({
  id: 'page-' + slug, slug, title: slug, status: published ? 'published' : 'draft',
  draftVersion: 1, publishedVersion: published ? 1 : null,
  document: { schema_version: 1, slug, title: slug, nodes: [] },
});

describe('owner CMS page redirects', () => {
  let rules: Array<{
    id: string; sourceSlug: string; targetSlug: string;
    statusCode: 307 | 308; enabled: boolean; version: number;
  }>;
  beforeEach(() => {
    rules = [{
      id: 'redirect-1', sourceSlug: 'outdated-page',
      targetSlug: 'home', statusCode: 308, enabled: true, version: 1,
    }];
    mocks.request.mockImplementation(async (path: string, options?: { method?: string; body?: string }) => {
      if (path === '/site-cms/pages' && !options) return [
        page('home', true), page('about', true), page('draft-only', false),
      ];
      if (path === '/site-forms' && !options) return [];
      if (path === '/agents' && !options) return [];
      if (path === '/site-cms/redirects' && !options) return structuredClone(rules);
      if (path === '/site-cms/menu') return {
        draftVersion: 0, publishedVersion: null, document: { items: [] },
      };
      if (path.startsWith('/site-analytics/summary')) {
        return { days: 30, pageViews: 0, ctaClicks: 0, pages: [] };
      }
      if (path === '/site-cms/redirects' && options?.method === 'POST') {
        const data = JSON.parse(options.body ?? '{}');
        const rule = {
          id: 'redirect-2', sourceSlug: data.source_slug, targetSlug: data.target_slug,
          statusCode: data.status_code, enabled: true, version: 1,
        };
        rules.push(rule);
        return rule;
      }
      if (path === '/site-cms/redirects/redirect-1' && options?.method === 'PUT') {
        const data = JSON.parse(options.body ?? '{}');
        const updated = {
          ...rules[0]!, targetSlug: data.target_slug,
          statusCode: data.status_code, enabled: data.enabled,
          version: data.expected_version + 1,
        };
        rules[0] = updated;
        return updated;
      }
      throw new Error('Unexpected request ' + path);
    });
  });

  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('creates redirects using a verified published page selection', async () => {
    render(<WebsiteCMSPage />);
    const sourceInput = await screen.findByLabelText('Previous URL slug');
    await waitFor(() => expect(sourceInput).toBeEnabled());
    const targetInput = screen.getByLabelText('Published destination');
    expect(within(targetInput).queryByText('draft-only')).toBeNull();
    fireEvent.change(sourceInput, { target: { value: 'old-about' } });
    fireEvent.change(targetInput, { target: { value: 'about' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create redirect' }));
    await waitFor(() => expect(rules).toHaveLength(2));
    const request = mocks.request.mock.calls.find(([path, options]) =>
      path === '/site-cms/redirects' && options?.method === 'POST',
    );
    expect(JSON.parse(request![1].body)).toEqual({
      source_slug: 'old-about', target_slug: 'about', status_code: 308,
    });
    expect(screen.getByText('/old-about')).toBeInTheDocument();
  });

  it('supports disabling rules without deleting their source or history', async () => {
    render(<WebsiteCMSPage />);
    const source = await screen.findByText('/outdated-page');
    expect(source).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Enabled' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save rule' }));
    await waitFor(() => expect(rules[0]!.version).toBe(2));
    expect(rules[0]!.enabled).toBe(false);
    const update = mocks.request.mock.calls.find(([path, options]) =>
      path === '/site-cms/redirects/redirect-1' && options?.method === 'PUT',
    );
    expect(JSON.parse(update![1].body)).toMatchObject({
      expected_version: 1, target_slug: 'home', status_code: 308, enabled: false,
    });
    expect(screen.getByText(/Revision 2 · Disabled/)).toBeInTheDocument();
  });
});
