/** Pure, immutable edit operations for versioned owner-controlled page documents.
 * IDs survive moves; only duplication creates new IDs.
 * Public visitors never receive or execute this editor module.
 */
export type BuilderKind = 'section' | 'container' | 'heading' | 'paragraph' | 'image' | 'button' | 'form';

export interface NodeAppearance {
  alignment: 'start' | 'center' | 'end';
  spacing: 'compact' | 'normal' | 'spacious';
  tone: 'default' | 'muted' | 'accent';
}

export const DEFAULT_NODE_APPEARANCE: Readonly<NodeAppearance> = {
  alignment: 'start', spacing: 'normal', tone: 'default',
};

/** Corresponds 1:1 to the backend's allowlisted design-token classes. */
export function appearanceClass(node: BuilderNode): string {
  if (!node.appearance) return '';
  const { alignment, spacing, tone } = node.appearance;
  return ['site-node', 'site-align-' + alignment, 'site-space-' + spacing, 'site-tone-' + tone].join(' ');
}

export interface BuilderNode {
  id: string;
  kind: BuilderKind;
  text?: string | null;
  url?: string | null;
  appearance?: NodeAppearance | null;
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
  if (sameDraftContent(next, history.present)) return history;
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

/** Compare JSON page documents by content, not JavaScript object-key insertion order.
 * Server Pydantic serialization can reorder keys between autosave rounds.
 */
export function sameDraftContent(left: unknown, right: unknown): boolean {
  const canonical = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(canonical);
    if (value !== null && typeof value === 'object') {
      const record = value as Record<string, unknown>;
      return Object.fromEntries(
        Object.keys(record)
          .filter((key) => record[key] !== undefined)
          .sort()
          .map((key) => [key, canonical(record[key])]),
      );
    }
    return value;
  };
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

export interface DraftDifference {
  field: string;
  local: string;
  server: string;
}

/** Summarize safe, human-readable document differences without guessing a merge. */
export function compareDraftDocuments(
  local: { title: string; nodes: BuilderNode[]; seo?: unknown; blog?: unknown },
  server: { title: string; nodes: BuilderNode[]; seo?: unknown; blog?: unknown },
): DraftDifference[] {
  const changes: DraftDifference[] = [];
  const describe = (value: unknown): string => {
    if (value === undefined || value === null) return '(empty)';
    if (typeof value === 'string') return value.slice(0, 160);
    return (JSON.stringify(value) ?? '').slice(0, 160);
  };
  const push = (field: string, a: unknown, b: unknown) => {
    if (!sameDraftContent(a, b) && changes.length < 40) {
      changes.push({ field, local: describe(a), server: describe(b) });
    }
  };
  push('Page title', local.title, server.title);
  push('SEO settings', local.seo, server.seo);
  push('Article metadata', local.blog, server.blog);

  const flatten = (nodes: BuilderNode[]): Map<string, BuilderNode> => {
    const values = new Map<string, BuilderNode>();
    const walk = (node: BuilderNode): void => {
      values.set(node.id, node);
      (node.children ?? []).forEach(walk);
    };
    nodes.forEach(walk);
    return values;
  };
  const localNodes = flatten(local.nodes);
  const serverNodes = flatten(server.nodes);
  const identifiers = [...new Set([...localNodes.keys(), ...serverNodes.keys()])];
  for (const id of identifiers) {
    const a = localNodes.get(id);
    const b = serverNodes.get(id);
    if (!a || !b) push('Block ' + id, a ? 'Present' : 'Removed', b ? 'Present' : 'Removed');
    else {
      push('Block ' + id + ' text', a.text, b.text);
      push('Block ' + id + ' URL', a.url, b.url);
      push('Block ' + id + ' type', a.kind, b.kind);
      push(
        'Block ' + id + ' child order',
        (a.children ?? []).map((child) => child.id),
        (b.children ?? []).map((child) => child.id),
      );
    }
    if (changes.length >= 40) break;
  }
  push('Section order', local.nodes.map((node) => node.id), server.nodes.map((node) => node.id));
  return changes;
}
