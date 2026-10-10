import { describe, expect, it } from 'vitest';
import {
  collectNodeIds, compareDraftDocuments, duplicateNode, duplicateSibling, moveBlockBetweenSections,
  removeChild, reorderNodes, redoDraftHistory, reviseDraftHistory, sameDraftContent, startDraftHistory, undoDraftHistory, type BuilderNode,
} from './websiteBuilderOperations';

const sample = (): BuilderNode[] => [
  { id: 'section-one', kind: 'section', children: [
    { id: 'heading-one', kind: 'heading', text: 'First' },
    { id: 'paragraph-one', kind: 'paragraph', text: 'Second' },
  ] },
  { id: 'section-two', kind: 'section', children: [
    { id: 'heading-two', kind: 'heading', text: 'Third' },
  ] },
];

describe('versioned visual website builder operations', () => {
  it('reorders sections without mutating original arrays or changing identifiers', () => {
    const original = sample();
    const moved = reorderNodes(original, 'section-one', 1);
    expect(moved.map((node) => node.id)).toEqual(['section-two', 'section-one']);
    expect(original.map((node) => node.id)).toEqual(['section-one', 'section-two']);
    expect(reorderNodes(original, 'section-one', -1)).toBe(original);
  });

  it('duplicates a nested section with entirely new identifiers', () => {
    const original = sample();
    let next = 0;
    const cloned = duplicateNode(original[0]!, () => 'copy-' + ++next);
    expect(cloned.children?.map((node) => node.text)).toEqual(['First', 'Second']);
    const existing = collectNodeIds(original);
    const newIds = collectNodeIds([cloned]);
    expect(new Set(newIds).size).toBe(newIds.length);
    expect(newIds.some((id) => existing.includes(id))).toBe(false);
    expect(original[0]?.id).toBe('section-one');
  });

  it('duplicates a block immediately after the source', () => {
    const original = sample()[0]!.children!;
    const duplicated = duplicateSibling(original, 'heading-one', () => 'new-heading');
    expect(duplicated.map((node) => node.id)).toEqual(['heading-one', 'new-heading', 'paragraph-one']);
    expect(duplicated[1]?.text).toBe('First');
    expect(original).toHaveLength(2);
  });

  it('removes only the selected block and preserves original content', () => {
    const original = sample()[0]!.children!;
    const reduced = removeChild(original, 'paragraph-one');
    expect(reduced.map((node) => node.id)).toEqual(['heading-one']);
    expect(original).toHaveLength(2);
    expect(removeChild(original, 'nonexistent')).toBe(original);
  });

  it('moves content between sections and keeps the same block ID', () => {
    const original = sample();
    const moved = moveBlockBetweenSections(original, 'heading-one', 'section-two');
    expect(moved[0]!.children?.map((node) => node.id)).toEqual(['paragraph-one']);
    expect(moved[1]!.children?.map((node) => node.id)).toEqual(['heading-two', 'heading-one']);
    expect(new Set(collectNodeIds(moved)).size).toBe(collectNodeIds(original).length);
    expect(original[0]!.children).toHaveLength(2);
  });

  it('does not drop a block on an unknown section', () => {
    const original = sample();
    expect(moveBlockBetweenSections(original, 'heading-one', 'no-section')).toBe(original);
    expect(moveBlockBetweenSections(original, 'no-block', 'section-two')).toBe(original);
  });

  it('moves blocks within a section deterministically and ignores invalid indices', () => {
    const original = sample();
    const moved = moveBlockBetweenSections(original, 'heading-one', 'section-one', 2);
    expect(moved[0]!.children?.map((node) => node.id)).toEqual(['paragraph-one', 'heading-one']);
    expect(moveBlockBetweenSections(original, 'heading-one', 'section-one', -1)).toBe(original);
    expect(moveBlockBetweenSections(original, 'heading-one', 'section-one', 999)).toBe(original);
  });
});

describe('editor draft history', () => {
  it('records a reversible edit and redo without changing the saved baseline', () => {
    const initial = { title: 'Original', nodes: sample() };
    const edited = { ...initial, title: 'Updated' };
    const start = startDraftHistory(initial);
    const changed = reviseDraftHistory(start, edited);
    expect(changed.past).toHaveLength(1);
    expect(start.present?.title).toBe('Original');
    const undone = undoDraftHistory(changed);
    expect(undone.present?.title).toBe('Original');
    expect(undone.future).toHaveLength(1);
    expect(redoDraftHistory(undone).present?.title).toBe('Updated');
  });

  it('discards the redo branch after a new edit', () => {
    const start = startDraftHistory({ title: 'One' });
    const changed = reviseDraftHistory(start, { title: 'Two' });
    const undone = undoDraftHistory(changed);
    const fork = reviseDraftHistory(undone, { title: 'Three' });
    expect(fork.future).toHaveLength(0);
    expect(redoDraftHistory(fork)).toBe(fork);
    expect(fork.present?.title).toBe('Three');
  });

  it('caps history length and ignores duplicate updates', () => {
    let history = startDraftHistory({ number: 0 });
    for (let i = 1; i < 101; i += 1) {
      history = reviseDraftHistory(history, { number: i });
    }
    expect(history.past).toHaveLength(50);
    expect(history.present?.number).toBe(100);
    expect(reviseDraftHistory(history, { number: 100 })).toBe(history);
  });

  it('resets draft history when changing pages', () => {
    const changed = reviseDraftHistory(startDraftHistory({ title: 'First' }), { title: 'Second' });
    const reset = startDraftHistory({ title: 'Other page' });
    expect(changed.past).toHaveLength(1);
    expect(reset.past).toHaveLength(0);
    expect(undoDraftHistory(reset).present?.title).toBe('Other page');
  });
});

describe('canonical document content comparison', () => {
  it('serializes owner drafts across stable field order without a false autosave', () => {
    const local = { title: 'About', seo: { indexable: false, description: 'About us' }, nodes: [{ id: 'one', kind: 'paragraph', text: 'Hello' }] };
    const server = { nodes: [{ text: 'Hello', kind: 'paragraph', id: 'one' }], seo: { description: 'About us', indexable: false }, title: 'About' };
    expect(sameDraftContent(local, server)).toBe(true);
    expect(reviseDraftHistory(startDraftHistory(local), server).past).toHaveLength(0);
  });

  it('detects changed content and block order', () => {
    const left = { nodes: [{ id: 'a' }, { id: 'b' }] };
    expect(sameDraftContent(left, { nodes: [{ id: 'b' }, { id: 'a' }] })).toBe(false);
    expect(sameDraftContent(left, { nodes: [{ id: 'a' }, { id: 'c' }] })).toBe(false);
  });
});

describe('readable editor conflict comparison', () => {
  const original = { title: 'First', seo: { indexable: false }, nodes: sample() };

  it('shows title, SEO, and individual changed block contents', () => {
    const local = { ...original, title: 'Local title',
      nodes: original.nodes.map((node) => node.id === 'section-one'
        ? { ...node, children: (node.children ?? []).map((child) => child.id === 'heading-one'
          ? { ...child, text: 'Local heading' } : child) } : node),
    };
    const server = { ...original, title: 'Server title', seo: { indexable: true } };
    const changes = compareDraftDocuments(local, server);
    expect(changes.some((entry) => entry.field === 'Page title'
      && entry.local === 'Local title' && entry.server === 'Server title')).toBe(true);
    expect(changes.some((entry) => entry.field === 'SEO settings')).toBe(true);
    expect(changes.some((entry) => entry.field === 'Block heading-one text'
      && entry.local === 'Local heading' && entry.server === 'First')).toBe(true);
  });

  it('never fabricates a difference for equivalent property ordering', () => {
    const document = {
      title: 'Same', nodes: [{ id: 'hero', kind: 'section' as const, text: 'Hello' }],
    };
    const reordered = {
      nodes: [{ text: 'Hello', kind: 'section' as const, id: 'hero' }], title: 'Same',
    };
    expect(compareDraftDocuments(document, reordered)).toEqual([]);
  });

  it('describes deletions without discarding either document', () => {
    const local = { title: 'Draft', nodes: [
      { id: 'a', kind: 'section' as const },
      { id: 'b', kind: 'section' as const },
    ] };
    const server = { title: 'Draft', nodes: [
      { id: 'a', kind: 'section' as const },
    ] };
    expect(compareDraftDocuments(local, server).some((entry) =>
      entry.field === 'Block b' && entry.server === 'Removed')).toBe(true);
    expect(local.nodes).toHaveLength(2);
    expect(server.nodes).toHaveLength(1);
  });
});


describe('appearance tokens and existing editor history', () => {
  it('preserves bounded styling across duplication and undo/redo without mutating the source', () => {
    const initial = sample();
    const styled = initial.map((section) => section.id === 'section-one' ? {
      ...section,
      appearance: { alignment: 'center' as const, spacing: 'spacious' as const, tone: 'accent' as const },
    } : section);
    const history = reviseDraftHistory(startDraftHistory(initial), styled);
    const back = undoDraftHistory(history);
    expect(back.present?.[0]?.appearance).toBeUndefined();
    expect(redoDraftHistory(back).present?.[0]?.appearance?.tone).toBe('accent');
    const copied = duplicateNode(styled[0]!, () => 'new-section');
    expect(copied.appearance).toEqual(styled[0]!.appearance);
    expect(copied.id).not.toBe(styled[0]!.id);
    expect(initial[0]!.appearance).toBeUndefined();
  });
});
