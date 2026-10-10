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
  useWorkspace: () => ({
    activeWorkspace: { id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' },
  }),
}));

const workspace = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const form = {
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  slug: 'contact',
  agentId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  draftVersion: 1,
  publishedVersion: 1,
  document: {
    title: 'Get in touch', description: '',
    privacy_notice: 'Your message is only used to respond to this enquiry.',
    submit_label: 'Send enquiry', fields: [],
  },
};
let page = {
  id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
  title: 'Home', slug: 'home', status: 'draft',
  draftVersion: 1, publishedVersion: null as number | null,
  document: {
    schema_version: 1, slug: 'home', title: 'Home',
    seo: { description: '', canonical_url: null, indexable: false },
    nodes: [{ id: 'top', kind: 'section', children: [
      { id: 'intro', kind: 'heading', text: 'Hello' },
    ] }],
  },
};

describe('CMS published form embed builder', () => {
  beforeEach(() => {
    page = {
      ...page, draftVersion: 1, publishedVersion: null,
      document: {
        ...page.document,
        nodes: [{ id: 'top', kind: 'section', children: [
          { id: 'intro', kind: 'heading', text: 'Hello' },
        ] }],
      },
    };
    mocks.request.mockImplementation(async (path: string, options?: { method?: string; body?: string }) => {
      if (path === '/site-cms/pages' && !options) return [structuredClone(page)];
      if (path === '/site-forms' && !options) return [structuredClone(form)];
      if (path === '/agents' && !options) return [];
      if (path === '/site-cms/redirects' && !options) return [];
      if (path === '/site-cms/menu' && !options) return {
        draftVersion: 0, publishedVersion: null, document: { items: [] },
      };
      if (path === '/site-analytics/summary?days=30') return {
        days: 30, pageViews: 0, ctaClicks: 0, pages: [],
      };
      if (path === '/site-cms/pages/' + page.id + '/revisions') return [];
      if (path === '/site-cms/pages/' + page.id && options?.method === 'PUT') {
        const body = JSON.parse(options.body ?? '{}');
        if (body.expected_version !== page.draftVersion) throw new Error('Version conflict');
        page = {
          ...page, draftVersion: page.draftVersion + 1,
          document: structuredClone(body.document),
        };
        return structuredClone(page);
      }
      throw new Error('Unexpected request ' + path);
    });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('only embeds already published first-party forms and previews without accepting leads', async () => {
    render(<WebsiteCMSPage />);
    const pageItem = await screen.findByRole('button', { name: /Home.*home/i });
    fireEvent.click(pageItem);
    const chooser = await screen.findByLabelText('Published form to embed');
    await waitFor(() => expect(screen.getByRole('option', { name: /Get in touch/ })).toBeInTheDocument());
    fireEvent.change(chooser, { target: { value: 'contact' } });
    fireEvent.click(screen.getByRole('button', { name: 'Embed published form' }));

    expect(screen.getByText(/First-party form: Get in touch/)).toBeInTheDocument();
    expect(screen.queryByRole('iframe')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save now' }));
    await waitFor(() => expect(page.draftVersion).toBe(2));
    const saved = mocks.request.mock.calls.find(([path, opts]) =>
      path === '/site-cms/pages/' + page.id && opts?.method === 'PUT',
    );
    const sent = JSON.parse(saved![1].body);
    expect(sent.expected_version).toBe(1);
    expect(sent.document.nodes[0].children).toEqual(expect.arrayContaining([
      expect.objectContaining({
        kind: 'form',
        text: 'Get in touch',
        url: '/api/v1/site-forms/public/' + workspace + '/contact',
      }),
    ]));
  });
});
