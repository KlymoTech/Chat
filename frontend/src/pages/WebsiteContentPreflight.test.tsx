import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WebsiteContentPreflight } from './WebsiteContentPreflight';

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('@/lib/api', () => ({ request: mocks.request }));

const brokenReport = {
  scope: 'cms-content-only', contentReady: false, releaseCertified: false,
  checkedAt: '2026-10-10T12:00:00Z',
  summary: {
    publishedPages: 2, publishedForms: 1, enabledRedirects: 1,
    blockers: 2, warnings: 1,
  },
  verificationLimits: 'Deployment, database recovery and real end-to-end delivery require separate verification.',
  issues: [
    {
      code: 'BROKEN_FORM_EMBED', severity: 'blocker', resourceType: 'page',
      slug: 'contact', message: 'An embedded form is no longer published.',
    },
    {
      code: 'BROKEN_MENU_LINK', severity: 'blocker', resourceType: 'menu',
      slug: 'outdated', message: 'Navigation destination is no longer published.',
    },
    {
      code: 'EMPTY_PAGE', severity: 'warning', resourceType: 'page',
      slug: 'about', message: 'Page has no published content blocks.',
    },
  ],
};

describe('Website CMS content preflight', () => {
  beforeEach(() => { mocks.request.mockResolvedValue(brokenReport); });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('does not claim readiness before the owner deliberately runs the check', async () => {
    render(<WebsiteContentPreflight />);
    expect(screen.getByText(/No content verification has been run/)).toBeInTheDocument();
    expect(mocks.request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Run content checks' }));
    expect(await screen.findByText(/2 content blockers need attention/)).toBeInTheDocument();
    expect(mocks.request).toHaveBeenCalledWith('/site-cms/preflight');
    expect(screen.getByText('page: /contact')).toBeInTheDocument();
    expect(screen.getByText('menu: /outdated')).toBeInTheDocument();
    expect(screen.getByText(/Production release is not certified/)).toBeInTheDocument();
  });

  it('shows content-only success without pretending production has been tested', async () => {
    mocks.request.mockResolvedValueOnce({
      ...brokenReport, contentReady: true,
      summary: { ...brokenReport.summary, blockers: 0, warnings: 0 },
      issues: [],
    });
    render(<WebsiteContentPreflight />);
    fireEvent.click(screen.getByRole('button', { name: 'Run content checks' }));
    expect(await screen.findByText('Stored content checks passed')).toBeInTheDocument();
    expect(screen.getByText(/Production release is not certified/)).toBeInTheDocument();
    expect(screen.getByText(/No broken internal publication references/)).toBeInTheDocument();
  });

  it('fails closed when the protected API fails', async () => {
    mocks.request.mockRejectedValueOnce(new Error('Workspace unavailable'));
    render(<WebsiteContentPreflight />);
    fireEvent.click(screen.getByRole('button', { name: 'Run content checks' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Workspace unavailable');
    expect(screen.queryByText('Stored content checks passed')).not.toBeInTheDocument();
  });

  it('rejects reports that accidentally advertise false release certification', async () => {
    mocks.request.mockResolvedValueOnce({ ...brokenReport, releaseCertified: true });
    render(<WebsiteContentPreflight />);
    fireEvent.click(screen.getByRole('button', { name: 'Run content checks' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(
      'Unexpected website preflight report type',
    ));
  });
});
