import {
  DEFAULT_NODE_APPEARANCE,
  type BuilderNode,
  type NodeAppearance,
} from './websiteBuilderOperations';

interface Props {
  node: BuilderNode;
  onChange: (appearance: NodeAppearance | null) => void;
}

/** Shared block/section inspector; does not permit raw HTML, scripts or CSS. */
export function WebsiteNodeStyleEditor({ node, onChange }: Props) {
  const appearance = node.appearance ?? DEFAULT_NODE_APPEARANCE;
  const update = (changes: Partial<NodeAppearance>) =>
    onChange({ ...appearance, ...changes });

  return <fieldset className="site-cms-style-editor" data-style-node={node.id}>
    <legend>Appearance · {node.kind}</legend>
    <div className="site-cms-style-fields">
      <label>Alignment
        <select value={appearance.alignment}
          aria-label={'Alignment for ' + node.kind + ' ' + node.id}
          onChange={(event) => update({
            alignment: event.target.value as NodeAppearance['alignment'],
          })}>
          <option value="start">Left / start</option>
          <option value="center">Center</option>
          <option value="end">Right / end</option>
        </select>
      </label>
      <label>Spacing
        <select value={appearance.spacing}
          aria-label={'Spacing for ' + node.kind + ' ' + node.id}
          onChange={(event) => update({
            spacing: event.target.value as NodeAppearance['spacing'],
          })}>
          <option value="compact">Compact</option>
          <option value="normal">Normal</option>
          <option value="spacious">Spacious</option>
        </select>
      </label>
      <label>Color preset
        <select value={appearance.tone}
          aria-label={'Color preset for ' + node.kind + ' ' + node.id}
          onChange={(event) => update({
            tone: event.target.value as NodeAppearance['tone'],
          })}>
          <option value="default">Default</option>
          <option value="muted">Muted</option>
          <option value="accent">Accent</option>
        </select>
      </label>
    </div>
    {node.appearance ? <button type="button" className="site-cms-style-reset"
      onClick={() => onChange(null)}>Reset appearance</button> : null}
    <small>Safe presets only. Styling stays part of the saved page revision.</small>
  </fieldset>;
}
