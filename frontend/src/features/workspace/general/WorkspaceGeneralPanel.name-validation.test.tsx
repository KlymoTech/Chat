/* @vitest-environment jsdom */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceGeneralPanel } from '@/features/workspace/general/WorkspaceGeneralPanel';
import { workspaceDefaults } from '@/lib/workspace-api';

afterEach(cleanup);

describe('Workspace general name validation', () => {
  it('provides a browser constraint for at least two non-space characters', () => {
    render(<WorkspaceGeneralPanel
      workspace={{ ...workspaceDefaults, permissions: ['workspace.view', 'workspace.update'] }}
      setWorkspace={vi.fn()}
      onSave={vi.fn()}
      saving={false}
      ownerInitial="N"
    />);
    const name = screen.getByLabelText('Workspace name') as HTMLInputElement;
    expect(name.required).toBe(true);
    expect(name.minLength).toBe(2);
    expect(name.maxLength).toBe(160);
    expect(name.pattern).toBe('.*\\S.*\\S.*');
    expect(name.title).toMatch(/two non-space characters/);
  });
});
