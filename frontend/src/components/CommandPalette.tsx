import { Check, CornerDownLeft, Search, Settings2, ShieldCheck, Sparkles, Building2, CircleHelp } from 'lucide-react';
import {
  useMemo,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from 'react';
import { useNavigate } from 'react-router-dom';
import type { WorkspaceSettings } from '@/lib/workspace-api';
import './command-palette.css';

export interface CommandPaletteNavigationItem {
  to: string;
  label: string;
  keywords?: string[];
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  navigation: CommandPaletteNavigationItem[];
  workspaces: WorkspaceSettings[];
  activeWorkspaceId?: string;
  onSelectWorkspace: (workspaceId: string) => void;
  canViewPlatformAdmin?: boolean;
}

type PaletteResult =
  | { id: string; kind: 'page'; label: string; hint: string; to: string }
  | { id: string; kind: 'workspace'; label: string; hint: string; workspaceId: string; current: boolean };

const extraPages: CommandPaletteNavigationItem[] = [
  { to: '/workspace', label: 'Workspace settings', keywords: ['settings', 'team', 'members', 'api keys'] },
  { to: '/workspace/white-label', label: 'White label', keywords: ['branding', 'domain', 'logo'] },
  { to: '/help', label: 'Help Center', keywords: ['support', 'docs', 'documentation'] },
];

function normalize(value: string): string {
  return value.trim().toLowerCase();
}

export function CommandPalette({
  open,
  onClose,
  navigation,
  workspaces,
  activeWorkspaceId,
  onSelectWorkspace,
  canViewPlatformAdmin = false,
}: CommandPaletteProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);

  const results = useMemo<PaletteResult[]>(() => {
    const term = normalize(query);
    const pageItems = [
      ...navigation,
      ...extraPages,
      ...(canViewPlatformAdmin
        ? [{ to: '/platform-admin', label: 'Platform control plane', keywords: ['admin', 'operations', 'tenants'] }]
        : []),
    ];
    const uniquePages = Array.from(new Map(pageItems.map((item) => [item.to, item])).values());
    const pages: PaletteResult[] = uniquePages
      .filter((item) => {
        if (!term) return true;
        const haystack = [item.label, item.to, ...(item.keywords ?? [])].join(' ').toLowerCase();
        return haystack.includes(term);
      })
      .map((item) => ({
        id: `page:${item.to}`,
        kind: 'page',
        label: item.label,
        hint: item.to === '/' ? 'Open overview' : `Open ${item.label}`,
        to: item.to,
      }));
    const workspaceResults: PaletteResult[] = workspaces
      .filter((workspace) => !term || `${workspace.name} ${workspace.slug} ${workspace.role ?? ''}`.toLowerCase().includes(term))
      .map((workspace) => ({
        id: `workspace:${workspace.id}`,
        kind: 'workspace',
        label: workspace.name,
        hint: workspace.id === activeWorkspaceId
          ? 'Current workspace'
          : `Switch workspace${workspace.role ? ` · ${workspace.role.replace('_', ' ')}` : ''}`,
        workspaceId: workspace.id,
        current: workspace.id === activeWorkspaceId,
      }));
    return [...pages, ...workspaceResults];
  }, [activeWorkspaceId, canViewPlatformAdmin, navigation, query, workspaces]);

  // The highlighted row must always point to a current result, even when
  // a workspace switch or a search term shortens the result list.
  const highlightedIndex = Math.min(activeIndex, Math.max(results.length - 1, 0));

  const closePalette = () => {
    setQuery('');
    setActiveIndex(0);
    onClose();
  };

  const execute = (result: PaletteResult | undefined) => {
    if (!result) return;
    if (result.kind === 'page') {
      navigate(result.to);
    } else if (!result.current) {
      onSelectWorkspace(result.workspaceId);
    }
    closePalette();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closePalette();
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((current) => results.length ? (current + 1) % results.length : 0);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((current) => results.length ? (current - 1 + results.length) % results.length : 0);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      execute(results[highlightedIndex]);
    }
  };

  const closeFromBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) closePalette();
  };

  if (!open) return null;

  return (
    <div className="command-palette-backdrop" onMouseDown={closeFromBackdrop}>
      <div
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Search and commands"
        onKeyDown={handleKeyDown}
      >
        <div className="command-palette__search">
          <Search aria-hidden="true" />
          <input
            autoFocus
            value={query}
            onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }}
            placeholder="Search pages and workspaces…"
            aria-label="Search pages and workspaces"
            autoComplete="off"
          />
          <kbd>Esc</kbd>
        </div>
        <div className="command-palette__results" role="listbox" aria-label="Command results">
          {results.length ? results.map((result, index) => {
            const selected = index === highlightedIndex;
            const Icon = result.kind === 'workspace'
              ? Building2
              : result.to === '/workspace'
                ? Settings2
                : result.to === '/platform-admin'
                  ? ShieldCheck
                  : result.to === '/help'
                    ? CircleHelp
                    : Sparkles;
            return (
              <button
                key={result.id}
                type="button"
                role="option"
                aria-selected={selected}
                className={selected ? 'is-active' : ''}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => execute(result)}
              >
                <span className="command-palette__icon"><Icon aria-hidden="true" /></span>
                <span className="command-palette__copy">
                  <strong>{result.label}</strong>
                  <small>{result.hint}</small>
                </span>
                {result.kind === 'workspace' && result.current
                  ? <Check className="command-palette__current" aria-label="Current workspace" />
                  : selected ? <CornerDownLeft className="command-palette__enter" aria-hidden="true" /> : null}
              </button>
            );
          }) : <div className="command-palette__empty"><Search /><strong>No matching page or workspace</strong><span>Try a different search term.</span></div>}
        </div>
        <div className="command-palette__footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span>
          <span><kbd>Enter</kbd> Open</span>
          <span><kbd>Esc</kbd> Close</span>
        </div>
      </div>
    </div>
  );
}
