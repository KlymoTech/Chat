import { useState } from 'react';
import { Button, Card, Field, Switch } from '@/components/ui';
import type { DashboardSettings, DashboardWidget } from '@/features/workspace/settings/workspaceSettings.api';

const WIDGET_TYPES = [
  'welcome', 'kpi-cards', 'conversation-summary', 'conversation-chart', 'lead-summary', 'leads-chart',
  'channel-health', 'agent-activity', 'crm-status', 'education-summary', 'quick-actions', 'announcements', 'usage',
];

export function BrandDashboardSettings({ value, onChange }: { value: DashboardSettings; onChange: (value: DashboardSettings) => void }) {
  const [dragging, setDragging] = useState<string | null>(null);
  function changeWidget(id: string, next: Partial<DashboardWidget>) {
    onChange({ ...value, layoutVersion: value.layoutVersion + 1, widgets: value.widgets.map((widget) => widget.id === id ? { ...widget, ...next } : widget) });
  }
  function addWidget() {
    const maxY = value.widgets.reduce((max, widget) => Math.max(max, widget.y + widget.height), 0);
    onChange({ ...value, layoutVersion: value.layoutVersion + 1, widgets: [...value.widgets, { id: crypto.randomUUID(), type: 'conversation-summary', x: 0, y: maxY, width: 4, height: 2, visible: true, audience: [], config: {} }] });
  }
  function moveBefore(targetId: string) {
    if (!dragging || dragging === targetId) return;
    const source = value.widgets.find((widget) => widget.id === dragging);
    if (!source) return;
    const without = value.widgets.filter((widget) => widget.id !== dragging);
    const targetIndex = without.findIndex((widget) => widget.id === targetId);
    without.splice(Math.max(targetIndex, 0), 0, source);
    const widgets = without.map((widget, index) => ({ ...widget, y: index * 2 }));
    onChange({ ...value, layoutVersion: value.layoutVersion + 1, widgets });
  }
  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <div className="page-heading page-heading--split"><div><h3>Dashboard builder</h3><p>Configure the published workspace dashboard as data, not hardcoded customer-specific React.</p></div><Button type="button" onClick={addWidget}>Add widget</Button></div>
    <Field label="Dashboard landing screen"><input value={value.landingScreen} onChange={(event) => onChange({ ...value, landingScreen: event.target.value, layoutVersion: value.layoutVersion + 1 })} /></Field>
    <p>Drag cards to reorder them, then use grid coordinates and size for precise placement. Layout version {value.layoutVersion}.</p>
    {value.widgets.length === 0 ? <p>No dashboard widgets. Add one to start the workspace layout.</p> : null}
    {value.widgets.map((widget) => <div className="setup-resource" key={widget.id} draggable onDragStart={() => setDragging(widget.id)} onDragEnd={() => setDragging(null)} onDragOver={(event) => event.preventDefault()} onDrop={() => moveBefore(widget.id)}>
      <div className="two-fields"><Field label="Widget type"><select value={widget.type} onChange={(event) => changeWidget(widget.id, { type: event.target.value })}>{WIDGET_TYPES.map((type) => <option key={type} value={type}>{type.replaceAll('-', ' ')}</option>)}</select></Field><Field label="Audience roles / IDs"><input value={widget.audience.join(', ')} placeholder="Leave empty for everyone" onChange={(event) => changeWidget(widget.id, { audience: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} /></Field></div>
      <div className="two-fields"><Field label="Grid X"><input type="number" min={0} max={24} value={widget.x} onChange={(event) => changeWidget(widget.id, { x: Number(event.target.value) })} /></Field><Field label="Grid Y"><input type="number" min={0} max={1000} value={widget.y} onChange={(event) => changeWidget(widget.id, { y: Number(event.target.value) })} /></Field></div>
      <div className="two-fields"><Field label="Width"><input type="number" min={1} max={24} value={widget.width} onChange={(event) => changeWidget(widget.id, { width: Number(event.target.value) })} /></Field><Field label="Height"><input type="number" min={1} max={24} value={widget.height} onChange={(event) => changeWidget(widget.id, { height: Number(event.target.value) })} /></Field></div>
      <Switch checked={widget.visible} onChange={(visible) => changeWidget(widget.id, { visible })} label="Visible" />
      <Field label="Widget config (JSON)"><textarea value={JSON.stringify(widget.config, null, 2)} onChange={(event) => { try { changeWidget(widget.id, { config: JSON.parse(event.target.value) as Record<string, unknown> }); } catch { /* keep last valid config while editing */ } }} /></Field>
      <Button type="button" variant="danger" onClick={() => onChange({ ...value, layoutVersion: value.layoutVersion + 1, widgets: value.widgets.filter((item) => item.id !== widget.id) })}>Remove widget</Button>
    </div>)}
  </div></Card>;
}
