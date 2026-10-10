/** Pure, immutable edit operations for versioned owner-controlled page documents.
 * IDs survive moves; only duplication creates new IDs.
 * Public visitors never receive or execute this editor module.
 */
export type BuilderKind = 'section' | 'container' | 'heading' | 'paragraph' | 'image' | 'button';

export interface BuilderNode {
  id: string;
  kind: BuilderKind;
  text?: string | null;
  url?: string | null;
  children?: BuilderNode[];
}

export function duplicateNode(node: BuilderNode, makeId: () => string): BuilderNode {
  return {
    ...node,
    id: makeId(),
    ...(node.children ? { children: node.children.map((child) => duplicateNode(child, makeId)) } : {}),
  };
}

export function reorderNodes(nodes: BuilderNode[], id: string, offset: number): BuilderNode[] {
  const from = nodes.findIndex((node) => node.id === id);
  const to = from + offset;
  if (from < 0 || !Number.isInteger(offset) || to < 0 || to >= nodes.length) return nodes;
  const reordered = [...nodes];
  [reordered[from], reordered[to]] = [reordered[to]!, reordered[from]!];
  return reordered;
}

export function removeChild(nodes: BuilderNode[], id: string): BuilderNode[] {
  if (!nodes.some((node) => node.id === id)) return nodes;
  return nodes.filter((node) => node.id !== id);
}

export function duplicateSibling(nodes: BuilderNode[], id: string, makeId: () => string): BuilderNode[] {
  const index = nodes.findIndex((node) => node.id === id);
  if (index < 0) return nodes;
  const result = [...nodes];
  result.splice(index + 1, 0, duplicateNode(nodes[index]!, makeId));
  return result;
}

/** Move a content block between top-level sections without dropping it on invalid targets. */
export function moveBlockBetweenSections(
  sections: BuilderNode[],
  blockId: string,
  destinationId: string,
  destinationIndex?: number,
): BuilderNode[] {
  const from = sections.findIndex((section) => section.kind === 'section'
    && (section.children ?? []).some((item) => item.id === blockId));
  const destination = sections.findIndex((section) => section.kind === 'section' && section.id === destinationId);
  if (from < 0 || destination < 0) return sections;
  const sourceChildren = sections[from]!.children ?? [];
  const sourceIndex = sourceChildren.findIndex((item) => item.id === blockId);
  const block = sourceChildren[sourceIndex]!;
  if (block.kind === 'section') return sections;
  const targetChildren = sections[destination]!.children ?? [];
  const targetIndex = destinationIndex === undefined ? targetChildren.length : destinationIndex;
  if (!Number.isInteger(targetIndex) || targetIndex < 0 || targetIndex > targetChildren.length) return sections;
  if (from === destination) {
    const without = sourceChildren.filter((item) => item.id !== blockId);
    const insertionIndex = targetIndex > sourceIndex ? targetIndex - 1 : targetIndex;
    if (insertionIndex === sourceIndex) return sections;
    without.splice(insertionIndex, 0, block);
    return sections.map((section, index) => index === from ? { ...section, children: without } : section);
  }
  return sections.map((section, index) => {
    if (index === from) return { ...section, children: sourceChildren.filter((item) => item.id !== blockId) };
    if (index === destination) {
      const next = [...targetChildren];
      next.splice(targetIndex, 0, block);
      return { ...section, children: next };
    }
    return section;
  });
}

export function collectNodeIds(sections: BuilderNode[]): string[] {
  const ids: string[] = [];
  const stack = [...sections];
  while (stack.length) {
    const next = stack.pop()!;
    ids.push(next.id);
    stack.push(...(next.children ?? []));
  }
  return ids;
}

/** One bounded undo stack shared by text, block, section and metadata edits. */
export interface DraftHistory<T> {
  past: T[];
  present: T | null;
  future: T[];
}

export function startDraftHistory<T>(document: T | null): DraftHistory<T> {
  return { past: [], present: document, future: [] };
}

export function reviseDraftHistory<T>(
  history: DraftHistory<T>,
  change: T | null | ((current: T | null) => T | null),
  maxSteps = 50,
): DraftHistory<T> {
  const next = typeof change === 'function'
    ? (change as (current: T | null) => T | null)(history.present)
    : change;
  if (JSON.stringify(next) === JSON.stringify(history.present)) return history;
  if (next === null) return startDraftHistory<T>(null);
  const past = history.present === null ? [] : [...history.past, history.present].slice(-maxSteps);
  return { past, present: next, future: [] };
}

export function undoDraftHistory<T>(history: DraftHistory<T>): DraftHistory<T> {
  if (!history.past.length) return history;
  const previous = history.past[history.past.length - 1]!;
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: history.present === null ? history.future : [history.present, ...history.future],
  };
}

export function redoDraftHistory<T>(history: DraftHistory<T>): DraftHistory<T> {
  if (!history.future.length) return history;
  const next = history.future[0]!;
  return {
    past: history.present === null ? history.past : [...history.past, history.present].slice(-50),
    present: next,
    future: history.future.slice(1),
  };
}
