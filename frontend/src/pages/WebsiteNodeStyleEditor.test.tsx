import { useState } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { WebsiteNodeStyleEditor } from './WebsiteNodeStyleEditor';
import { appearanceClass, type BuilderNode } from './websiteBuilderOperations';

function Harness() {
  const [node, setNode] = useState<BuilderNode>({
    id: 'heading-one', kind: 'heading', text: 'Hello',
  });
  return <>
    <WebsiteNodeStyleEditor node={node}
      onChange={(appearance) => setNode((current) => ({ ...current, appearance }))}/>
    <output data-testid="appearance">{JSON.stringify(node.appearance)}</output>
    <output data-testid="classes">{appearanceClass(node)}</output>
  </>;
}

describe('versioned CMS node-style inspector', () => {
  afterEach(cleanup);

  it('only offers bounded style choices, then resets the optional properties', () => {
    render(<Harness />);
    const alignment = screen.getByLabelText('Alignment for heading heading-one');
    const spacing = screen.getByLabelText('Spacing for heading heading-one');
    const color = screen.getByLabelText('Color preset for heading heading-one');

    expect(alignment).toHaveValue('start');
    expect(spacing).toHaveValue('normal');
    expect(color).toHaveValue('default');
    expect(screen.queryByRole('textbox', { name: /custom css/i })).not.toBeInTheDocument();

    fireEvent.change(alignment, { target: { value: 'center' } });
    fireEvent.change(spacing, { target: { value: 'spacious' } });
    fireEvent.change(color, { target: { value: 'accent' } });
    expect(screen.getByTestId('appearance')).toHaveTextContent(
      '{"alignment":"center","spacing":"spacious","tone":"accent"}',
    );
    expect(screen.getByTestId('classes')).toHaveTextContent(
      'site-node site-align-center site-space-spacious site-tone-accent',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Reset appearance' }));
    expect(screen.getByTestId('appearance').textContent).toBe('null');
    expect(screen.getByTestId('classes').textContent).toBe('');
  });
});
