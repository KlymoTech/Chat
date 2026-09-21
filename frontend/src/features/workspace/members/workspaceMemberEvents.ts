export const WORKSPACE_MEMBER_CHANGED_EVENT = 'northstar:workspace-member-changed';

export type WorkspaceMemberChangeKind =
  | 'invited'
  | 'invitation-resent'
  | 'invitation-revoked'
  | 'member-updated'
  | 'member-removed'
  | 'member-suspended'
  | 'member-reactivated';

export function emitWorkspaceMemberChanged(kind: WorkspaceMemberChangeKind): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(WORKSPACE_MEMBER_CHANGED_EVENT, { detail: { kind } }));
}

export function onWorkspaceMemberChanged(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  window.addEventListener(WORKSPACE_MEMBER_CHANGED_EVENT, listener);
  return () => window.removeEventListener(WORKSPACE_MEMBER_CHANGED_EVENT, listener);
}
