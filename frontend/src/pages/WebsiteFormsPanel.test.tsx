import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WebsiteFormsPanel } from './WebsiteFormsPanel';

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('@/lib/api', () => ({
  request: mocks.request,
  apiConfig: { baseUrl: '/api/v1' },
}));

const workspaceId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const agentId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

const formDocument = {
  title: 'Contact us', description: 'Contact our team',
  privacy_notice: 'We process your enquiry to reply to you.',
  submit_label: 'Send enquiry',
  fields: [
    { key: 'email', label: 'Email', kind: 'email', purpose: 'Reply to an enquiry',
      required: true, sensitivity: 'personal', retention_days: 365, max_length: 300, choices: [] },
    { key: 'processing_consent', label: 'I consent', kind: 'consent',
      purpose: 'Process enquiry', required: true,
      sensitivity: 'personal', retention_days: 365, max_length: 300, choices: [] },
  ],
};

describe('Website CMS site forms editor', () => {
  let forms: Array<{
    id: string; slug: string; agentId: string; draftVersion: number;
    publishedVersion: number | null; document: typeof formDocument;
  }>;

  beforeEach(() => {
    forms = [];
    mocks.request.mockImplementation(async (path: string, options?: { method?: string; body?: string }) => {
      if (path === '/site-forms' && !options) return structuredClone(forms);
      if (path === '/agents') return [
        { id: agentId, name: 'Lead Generation', purpose: 'lead_generation', status: 'active' },
        { id: 'other', name: 'Support', purpose: 'support', status: 'active' },
      ];
      if (path === '/site-forms' && options?.method === 'POST') {
        const posted = JSON.parse(options.body ?? '{}');
        const result = {
          id: 'form-1', slug: posted.slug, agentId: posted.agent_id,
          draftVersion: 1, publishedVersion: null,
          document: structuredClone(posted.document),
        };
        forms.push(result);
        return result;
      }
      if (path === '/site-forms/form-1' && options?.method === 'PUT') {
        const posted = JSON.parse(options.body ?? '{}');
        if (posted.expected_version !== forms[0]!.draftVersion) throw new Error('Stale revision');
        forms[0] = {
          ...forms[0]!, draftVersion: forms[0]!.draftVersion + 1,
          document: structuredClone(posted.document),
        };
        return structuredClone(forms[0]);
      }
      if (path === '/site-forms/form-1/publish' && options?.method === 'POST') {
        forms[0]!.publishedVersion = forms[0]!.draftVersion;
        return structuredClone(forms[0]);
      }
      if (path === '/site-forms/form-1/unpublish' && options?.method === 'POST') {
        forms[0]!.publishedVersion = null;
        return structuredClone(forms[0]);
      }
      if (path === '/site-forms/form-1/submissions') {
        return [{ receiptId: 'receipt1', leadId: 'lead1', version: '1',
          createdAt: '2026-10-10T08:00:00Z' }];
      }
      throw new Error('Unexpected request ' + path);
    });
  });

  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('uses the existing lead-generation agent, saves private draft and then publishes separately', async () => {
    render(<WebsiteFormsPanel workspaceId={workspaceId}/>);
    const slug = await screen.findByLabelText('Form URL slug');
    await waitFor(() => expect(slug).toBeEnabled());
    expect(screen.getByRole('option', { name: /Lead Generation/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Support' })).not.toBeInTheDocument();
    fireEvent.change(slug, { target: { value: 'enquiry' } });
    fireEvent.change(screen.getByLabelText('Lead Generation Agent'), { target: { value: agentId } });
    fireEvent.click(screen.getByRole('button', { name: 'Create private form' }));
    await waitFor(() => expect(forms).toHaveLength(1));
    expect(forms[0]!.publishedVersion).toBeNull();
    const create = mocks.request.mock.calls.find(([path, opts]) =>
      path === '/site-forms' && opts?.method === 'POST',
    );
    expect(JSON.parse(create![1].body).agent_id).toBe(agentId);
    expect(screen.getByRole('button', { name: 'Publish form' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Publish form' }));
    await waitFor(() => expect(forms[0]!.publishedVersion).toBe(1));
    expect(screen.getByRole('link', { name: /site-forms\/public/ })).toHaveAttribute(
      'href', '/api/v1/site-forms/public/' + workspaceId + '/enquiry',
    );
    expect(screen.getByText(/published revision 1/i)).toBeInTheDocument();
  });

  it('does not publish unsaved edits and retains prior live revision while saving draft', async () => {
    forms = [{
      id: 'form-1', slug: 'contact', agentId, draftVersion: 1, publishedVersion: 1,
      document: structuredClone(formDocument),
    }];
    render(<WebsiteFormsPanel workspaceId={workspaceId}/>);
    const select = await screen.findByLabelText('Choose a form');
    fireEvent.change(select, { target: { value: 'form-1' } });
    const title = screen.getByLabelText('Form title');
    fireEvent.change(title, { target: { value: 'New draft title' } });
    expect(screen.getByRole('button', { name: 'Publish form' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save revision' }));
    await waitFor(() => expect(forms[0]!.draftVersion).toBe(2));
    expect(forms[0]!.publishedVersion).toBe(1);
    const update = mocks.request.mock.calls.find(([path, opts]) =>
      path === '/site-forms/form-1' && opts?.method === 'PUT',
    );
    expect(JSON.parse(update![1].body).expected_version).toBe(1);
  });

  it('reads receipt references without requesting or exposing full submission answers', async () => {
    forms = [{
      id: 'form-1', slug: 'contact', agentId, draftVersion: 1, publishedVersion: 1,
      document: structuredClone(formDocument),
    }];
    render(<WebsiteFormsPanel workspaceId={workspaceId}/>);
    fireEvent.change(await screen.findByLabelText('Choose a form'),
      { target: { value: 'form-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Load submission receipts' }));
    expect(await screen.findByText(/Receipt receipt1/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Review lead' })).toHaveAttribute('href', '/leads');
    expect(mocks.request.mock.calls.some(([path]) =>
      path === '/site-forms/form-1/submissions')).toBe(true);
  });

  it('saves step labels and an authorized conditional choice through the existing form API', async () => {
    render(<WebsiteFormsPanel workspaceId={workspaceId}/>);
    const slug = await screen.findByLabelText('Form URL slug');
    await waitFor(() => expect(slug).toBeEnabled());
    fireEvent.change(slug, { target: { value: 'conditional-contact' } });
    fireEvent.change(screen.getByLabelText('Lead Generation Agent'), { target: { value: agentId } });
    fireEvent.click(screen.getByRole('button', { name: 'Add a step' }));
    fireEvent.change(screen.getByLabelText('Step 2 heading'),
      { target: { value: 'More details' } });

    // Keep required email and processing consent; turn the earlier name field into a controller.
    const controlTypes = screen.getAllByLabelText('Control type');
    fireEvent.change(controlTypes[0]!, { target: { value: 'select' } });
    fireEvent.change(screen.getByLabelText('Choices (one per line)'),
      { target: { value: 'Sales\nSupport' } });
    const keys = screen.getAllByLabelText('Stable key');
    const lastKey = keys[keys.length - 1]!;
    const newFieldKey = (lastKey as HTMLInputElement).value;
    const conditions = screen.getAllByLabelText('Display condition');
    fireEvent.change(conditions[conditions.length - 1]!, { target: { value: 'name' } });
    expect(screen.getByLabelText('Show when choice equals')).toHaveValue('Sales');
    expect(screen.getByRole('button', { name: 'Create private form' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Create private form' }));
    await waitFor(() => expect(forms).toHaveLength(1));
    const sent = mocks.request.mock.calls.find(([path, options]) =>
      path === '/site-forms' && options?.method === 'POST',
    );
    const document = JSON.parse(sent![1].body).document;
    expect(document.steps).toEqual(['Your details', 'More details']);
    expect(document.fields.find((item: { key: string }) => item.key === newFieldKey))
      .toMatchObject({ step: 2, condition: { field_key: 'name', equals: 'Sales' } });
    expect(forms[0]!.publishedVersion).toBeNull();
  });


  it('adds a separate optional marketing checkbox without changing processing consent', async () => {
    render(<WebsiteFormsPanel workspaceId={workspaceId}/>);
    const slugInput = await screen.findByLabelText('Form URL slug');
    await waitFor(() => expect(slugInput).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Add marketing opt-in' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Add marketing opt-in' }));
    expect(screen.getByRole('button', { name: 'Add marketing opt-in' })).toBeDisabled();

    const stableKeys = screen.getAllByLabelText('Stable key');
    expect(stableKeys[stableKeys.length - 1]).toHaveValue('marketing_opt_in');
    expect(stableKeys[stableKeys.length - 1]).toHaveAttribute('readonly');
    const required = screen.getAllByLabelText('Required');
    expect(required[required.length - 1]).toBeDisabled();
    expect(required[required.length - 1]).not.toBeChecked();

    fireEvent.change(slugInput, { target: { value: 'marketing-contact' } });
    fireEvent.change(screen.getByLabelText('Lead Generation Agent'), {
      target: { value: agentId },
    });
    const create = screen.getByRole('button', { name: 'Create private form' });
    expect(create).toBeEnabled();
    fireEvent.click(create);
    await waitFor(() => expect(forms).toHaveLength(1));

    const request = mocks.request.mock.calls.find(([path, options]) =>
      path === '/site-forms' && options?.method === 'POST',
    );
    const posted = JSON.parse(request![1].body);
    const marketing = posted.document.fields.find(
      (field: { key: string }) => field.key === 'marketing_opt_in',
    );
    expect(marketing).toMatchObject({
      kind: 'checkbox', required: false, condition: null,
    });
    expect(marketing.label).toMatch(/marketing/i);
    expect(marketing.purpose).toMatch(/marketing/i);
    expect(posted.document.fields.find(
      (field: { key: string }) => field.key === 'processing_consent',
    )).toMatchObject({ kind: 'consent', required: true });
    expect(forms[0]!.publishedVersion).toBeNull();
  });

});
