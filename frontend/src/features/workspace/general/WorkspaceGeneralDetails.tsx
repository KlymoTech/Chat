import type { Dispatch, SetStateAction } from 'react';
import { Field } from '@/components/ui';
import type { BusinessDay, BusinessHours, WorkspacePreferences, WorkspaceSettings } from '@/lib/workspace-api';

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const;
const defaultDay = (enabled: boolean): BusinessDay => ({ enabled, opens: '09:00', closes: '17:00' });
const DEFAULT_HOURS: BusinessHours = {
  monday: defaultDay(true), tuesday: defaultDay(true), wednesday: defaultDay(true),
  thursday: defaultDay(true), friday: defaultDay(true),
  saturday: defaultDay(false), sunday: defaultDay(false),
};

interface Props {
  workspace: WorkspaceSettings;
  setWorkspace: Dispatch<SetStateAction<WorkspaceSettings | null>>;
  disabled: boolean;
}

/** Keeps the optional legacy preference shape editable without changing existing routes. */
export function WorkspaceGeneralDetails({ workspace, setWorkspace, disabled }: Props) {
  const preferences = workspace.preferences;
  const hours = { ...DEFAULT_HOURS, ...preferences.businessHours };
  function change<K extends keyof WorkspacePreferences>(key: K, value: WorkspacePreferences[K]) {
    setWorkspace((current) => current?.id === workspace.id
      ? { ...current, preferences: { ...current.preferences, [key]: value } }
      : current);
  }
  function changeHours(day: keyof BusinessHours, patch: Partial<BusinessDay>) {
    const updated = { ...hours, [day]: { ...hours[day], ...patch } };
    change('businessHours', updated);
  }

  return <section aria-labelledby="workspace-additional-details">
    <h4 id="workspace-additional-details">Workspace details</h4>
    <p>Profile, regional display preferences, and reference business hours for this workspace.</p>
    <div className="two-fields">
      <Field label="Workspace ID"><input readOnly value={workspace.id} /></Field>
      <Field label="Organization"><input readOnly value={workspace.tenantName ?? 'Not available'} /></Field>
    </div>
    <div className="two-fields">
      <Field label="Workspace status"><input readOnly value={workspace.status ?? 'active'} /></Field>
      <Field label="Industry"><input value={preferences.industry ?? ''} maxLength={120} disabled={disabled} onChange={(event) => change('industry', event.target.value)} /></Field>
    </div>
    <div className="two-fields">
      <Field label="Country"><input value={preferences.country ?? ''} maxLength={80} disabled={disabled} onChange={(event) => change('country', event.target.value)} /></Field>
      <Field label="Workspace icon"><select value={preferences.workspaceIcon ?? ''} disabled={disabled} onChange={(event) => change('workspaceIcon', event.target.value)}><option value="">Default</option><option value="🏢">🏢 Organization</option><option value="🎓">🎓 Education</option><option value="💬">💬 Support</option><option value="🛍️">🛍️ Retail</option></select></Field>
    </div>
    <Field label="Workspace description"><textarea value={preferences.description ?? ''} rows={3} maxLength={2000} disabled={disabled} onChange={(event) => change('description', event.target.value)} /></Field>
    <div className="two-fields">
      <Field label="Time format"><select value={preferences.timeFormat ?? '24h'} disabled={disabled} onChange={(event) => change('timeFormat', event.target.value as NonNullable<WorkspacePreferences['timeFormat']>)}><option value="24h">24-hour</option><option value="12h">12-hour</option></select></Field>
      <Field label="Currency code"><input value={preferences.currency ?? 'USD'} maxLength={3} pattern="[A-Z]{3}" title="Three-letter currency code, such as USD or INR" disabled={disabled} onChange={(event) => change('currency', event.target.value.toUpperCase().replace(/[^A-Z]/g, ''))} /></Field>
    </div>
    <Field label="First day of week"><select value={preferences.weekStart ?? 'monday'} disabled={disabled} onChange={(event) => change('weekStart', event.target.value as NonNullable<WorkspacePreferences['weekStart']>)}><option value="monday">Monday</option><option value="saturday">Saturday</option><option value="sunday">Sunday</option></select></Field>
    <details>
      <summary>Business hours</summary>
      <p>Times use the workspace timezone and are stored in 24-hour format. These reference hours do not yet change channel routing or automatic replies.</p>
      {DAYS.map((day) => <div className="two-fields" key={day}>
        <label><input type="checkbox" checked={hours[day].enabled} disabled={disabled} aria-label={`${day} open`} onChange={(event) => changeHours(day, { enabled: event.target.checked })} /> {day[0]!.toUpperCase() + day.slice(1)}</label>
        <div className="two-fields">
          <Field label={`${day} opens`}><input type="time" value={hours[day].opens} disabled={disabled || !hours[day].enabled} onChange={(event) => changeHours(day, { opens: event.target.value })} /></Field>
          <Field label={`${day} closes`}><input type="time" value={hours[day].closes} disabled={disabled || !hours[day].enabled} onChange={(event) => changeHours(day, { closes: event.target.value })} /></Field>
        </div>
      </div>)}
    </details>
  </section>;
}
