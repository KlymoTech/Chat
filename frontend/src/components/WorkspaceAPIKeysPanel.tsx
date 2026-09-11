import { Check, Copy, KeyRound, LockKeyhole, Plus, Trash2 } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useToast } from '@/components/providers';
import { Button, Card } from '@/components/ui';
import {
  workspaceAPIKeyApi,
  type WorkspaceAPIKey,
} from '@/lib/workspace-api-keys';
import type { WorkspaceSettings } from '@/lib/workspace-api';

export function WorkspaceAPIKeysPanel({ workspace }: { workspace: WorkspaceSettings }) {
  const { pushToast } = useToast();
  const [keys, setKeys] = useState<WorkspaceAPIKey[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [newSecret, setNewSecret] = useState('');
  const permissions = workspace.permissions ?? [];
  const canView = permissions.includes('*') || permissions.includes('api_keys.view');
  const canManage = permissions.includes('*') || permissions.includes('api_keys.manage');

  useEffect(() => {
    if (!canView) return;
    let active = true;
    setLoading(true);
    void workspaceAPIKeyApi.list()
      .then((values) => { if (active) setKeys(values); })
      .catch((error) => {
        if (active) pushToast(error instanceof Error ? error.message : 'API keys could not be loaded', 'error');
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [canView, pushToast, workspace.id]);

  async function createKey() {
    setCreating(true);
    try {
      const created = await workspaceAPIKeyApi.create(`Production ${keys.length + 1}`);
      const { secret, ...record } = created;
      setKeys((current) => [record, ...current.filter((item) => item.id !== record.id)]);
      setNewSecret(secret);
      pushToast('API key created');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'API key could not be created', 'error');
    } finally {
      setCreating(false);
    }
  }

  async function revokeKey(id: string) {
    setRevokingId(id);
    try {
      await workspaceAPIKeyApi.revoke(id);
      setKeys((current) => current.filter((item) => item.id !== id));
      pushToast('API key revoked');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'API key could not be revoked', 'error');
    } finally {
      setRevokingId(null);
    }
  }

  return <Card className="workspace-panel">
    <PanelHeading
      title="API keys"
      description="Create and revoke workspace-scoped credentials used by your server-side integrations."
      action={canManage ? <Button icon={Plus} onClick={() => void createKey()} disabled={creating}>{creating ? 'Creating…' : 'Create secret key'}</Button> : undefined}
    />
    {!canView ? <div className="workspace-empty-row"><KeyRound /><span><strong>API key access is restricted</strong><small>Ask a workspace administrator to manage server credentials.</small></span></div> : null}
    {newSecret ? <div className="workspace-secret"><LockKeyhole /><div><strong>Copy this key now</strong><small>For security, the full secret is shown only once and is not stored in plaintext.</small><code>{newSecret}</code></div><button type="button" className="icon-button" aria-label="Copy new API key" onClick={() => void navigator.clipboard.writeText(newSecret).then(() => pushToast('Secret key copied'))}><Copy /></button><button type="button" className="icon-button" aria-label="Hide new API key" onClick={() => setNewSecret('')}><Check /></button></div> : null}
    {canView ? <div className="workspace-key-list">
      {loading ? <div className="workspace-empty-row"><KeyRound /><span><strong>Loading API keys…</strong><small>Reading active credentials for this workspace.</small></span></div> : null}
      {!loading && keys.length ? keys.map((key) => <div key={key.id}><span><strong>{key.name}</strong><small>Created {new Date(key.createdAt).toLocaleDateString()}{key.lastUsedAt ? ` · Last used ${new Date(key.lastUsedAt).toLocaleDateString()}` : ''}</small></span><code>{key.prefix}••••</code>{canManage ? <button type="button" className="icon-button danger-hover" onClick={() => void revokeKey(key.id)} disabled={revokingId === key.id} aria-label={`Revoke ${key.name}`}><Trash2 /></button> : null}</div>) : null}
      {!loading && keys.length === 0 ? <div className="workspace-empty-row"><KeyRound /><span><strong>No API keys yet</strong><small>Create a key when you are ready to connect your backend.</small></span></div> : null}
    </div> : null}
  </Card>;
}

function PanelHeading({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="workspace-panel__heading"><span><KeyRound /></span><div><h3>{title}</h3><p>{description}</p></div>{action}</div>;
}
