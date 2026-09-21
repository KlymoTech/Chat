import { Building2, GraduationCap } from 'lucide-react';
import type { Dispatch, FormEvent, ReactNode, SetStateAction } from 'react';
import { Button, Card, Field } from '@/components/ui';
import { WorkspaceGeneralDetails } from '@/features/workspace/general/WorkspaceGeneralDetails';
import type { WorkspaceSettings } from '@/lib/workspace-api';

interface WorkspaceGeneralPanelProps {
  workspace: WorkspaceSettings;
  setWorkspace: Dispatch<SetStateAction<WorkspaceSettings | null>>;
  onSave: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  saving: boolean;
  ownerInitial: string;
}

/** Keep the legacy form and API; UI grants mirror (but never replace) backend authorization. */
export function WorkspaceGeneralPanel({
  workspace, setWorkspace, onSave, saving, ownerInitial,
}: WorkspaceGeneralPanelProps) {
  const canEdit = workspace.permissions?.includes('workspace.update')
    ?? (workspace.id === 'workspace-demo');
  const disabled = !canEdit || saving;
  return <>
    <form onSubmit={onSave}>
      <Card className="workspace-panel"><PanelHeading icon={Building2} title="Workspace profile" description="Organization details and regional preferences shared across the workspace." />
        <div className="workspace-panel__body">
          {!canEdit ? <p role="status">You can view these settings, but only a workspace administrator can change them.</p> : null}
          <div className="workspace-profile-mark">{workspace.whiteLabel.logoDataUrl ? <img src={workspace.whiteLabel.logoDataUrl} alt="Workspace logo" /> : ownerInitial}</div>
          <div className="two-fields"><Field label="Workspace name" htmlFor="workspace-name"><input id="workspace-name" value={workspace.name} disabled={disabled} minLength={2} maxLength={160} required onChange={(event) => setWorkspace({ ...workspace, name: event.target.value })} /></Field><Field label="Workspace slug" htmlFor="workspace-slug"><div className="prefix-input"><span>app.northstar.ai/</span><input id="workspace-slug" value={workspace.slug} disabled={disabled} minLength={2} maxLength={80} required pattern="[a-z0-9]+(-[a-z0-9]+)*" onChange={(event) => setWorkspace({ ...workspace, slug: event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') })} /></div></Field></div>
          <div className="two-fields"><Field label="Timezone"><select value={workspace.preferences.timezone} disabled={disabled} onChange={(event) => setWorkspace({ ...workspace, preferences: { ...workspace.preferences, timezone: event.target.value } })}><option>Asia/Calcutta</option><option>UTC</option><option>America/New_York</option><option>Europe/London</option></select></Field><Field label="Date format"><select value={workspace.preferences.dateFormat} disabled={disabled} onChange={(event) => setWorkspace({ ...workspace, preferences: { ...workspace.preferences, dateFormat: event.target.value as WorkspaceSettings['preferences']['dateFormat'] } })}><option>DD/MM/YYYY</option><option>MM/DD/YYYY</option><option>YYYY-MM-DD</option></select></Field></div>
          <Field label="Default workspace language"><select value={workspace.preferences.defaultLanguage} disabled={disabled} onChange={(event) => setWorkspace({ ...workspace, preferences: { ...workspace.preferences, defaultLanguage: event.target.value } })}><option>English</option><option>Hindi</option><option>Spanish</option><option>French</option><option>German</option><option>Arabic</option></select></Field>
          <WorkspaceGeneralDetails workspace={workspace} setWorkspace={setWorkspace} disabled={disabled} />
          <div className="workspace-panel__actions"><Button type="submit" disabled={disabled}>{saving ? 'Saving…' : 'Save workspace'}</Button></div>
        </div>
      </Card>
    </form>

    <Card className="workspace-panel"><PanelHeading icon={GraduationCap} title="Education conversations" description="Student chats stay in Conversations and are kept separate from Leads and CRM sales sync." />
      <div className="workspace-panel__body"><p>Education agents support enrolled students. Their chats have no Resolve or lead-status actions. Use a Lead Generation agent for sales enquiries.</p></div>
    </Card>
  </>;
}

function PanelHeading({ icon: Icon, title, description, action }: { icon: typeof Building2; title: string; description: string; action?: ReactNode }) {
  return <div className="workspace-panel__heading"><span><Icon /></span><div><h3>{title}</h3><p>{description}</p></div>{action}</div>;
}
