/* @vitest-environment jsdom */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { WorkspaceGeneralRoute } from '@/features/workspace/general/WorkspaceGeneralRoute';

vi.mock('@/pages/WorkspacePage', () => ({
  WorkspacePage: () => <h1>General settings form</h1>,
}));

afterEach(cleanup);

describe('WorkspaceGeneralRoute', () => {
  it('renders the existing general form under its new canonical protected route', () => {
    render(<MemoryRouter initialEntries={['/workspace/settings/general']}><Routes>
      <Route path="/workspace/settings/general" element={<WorkspaceGeneralRoute />} />
      <Route path="/workspace" element={<h1>Legacy workspace tabs</h1>} />
    </Routes></MemoryRouter>);
    expect(screen.getByText('General settings form')).toBeTruthy();
    expect(screen.queryByText('Legacy workspace tabs')).toBeNull();
  });

  it('keeps other existing tabs on their legacy route instead of showing them as General', async () => {
    render(<MemoryRouter initialEntries={['/workspace/settings/general?section=team']}><Routes>
      <Route path="/workspace/settings/general" element={<WorkspaceGeneralRoute />} />
      <Route path="/workspace" element={<h1>Legacy workspace tabs</h1>} />
    </Routes></MemoryRouter>);
    expect(await screen.findByText('Legacy workspace tabs')).toBeTruthy();
    expect(screen.queryByText('General settings form')).toBeNull();
  });
});
