import { useCallback, useEffect, useRef, useState, type ReactNode, type SetStateAction } from 'react';
import { ArrowDown, ArrowUp, Check, Copy, ExternalLink, FilePlus2, GripVertical, Plus, Redo2, RefreshCw, Save, Send, ShieldCheck, Trash2, Undo2 } from 'lucide-react';
import { useWorkspace } from '@/components/providers';
import { Button, Card, Badge } from '@/components/ui';
import { ApiError, apiConfig, request } from '@/lib/api';
import { appearanceClass, compareDraftDocuments, duplicateSibling, moveBlockBetweenSections, redoDraftHistory, removeChild, reorderNodes, reviseDraftHistory, sameDraftContent, startDraftHistory, undoDraftHistory, type BuilderNode } from './websiteBuilderOperations';
import { WebsiteAnalyticsReport } from './WebsiteAnalyticsReport';
import { WebsiteContentPreflight } from './WebsiteContentPreflight';
import { WebsiteNodeStyleEditor } from './WebsiteNodeStyleEditor';
import { WebsiteFormsPanel } from './WebsiteFormsPanel';
import './WebsiteCMSPage.css';

type Kind = 'section' | 'heading' | 'paragraph' | 'image' | 'button';
type Action = 'submit' | 'approve' | 'publish' | 'archive' | 'restore_draft' | 'request_changes';
type Node = BuilderNode;
interface PageSEO { description: string; canonical_url: string | null; indexable: boolean }
interface BlogMetadata { author: string; category: string; summary: string; reviewer: string | null; locale: string }
interface PageDocument {
  schema_version: 1; title: string; slug: string; nodes: Node[]; seo?: PageSEO;
  content_type?: 'page' | 'article'; blog?: BlogMetadata | null;
}
interface WebsiteMetrics {
  days: number; pageViews: number; ctaClicks: number;
  pages: Array<{ slug: string; pageViews: number }>;
  formSubmissions?: { total: number; byForm: Array<{ slug: string; submissions: number }> };
  conversionDispatch?: {
    publishedToEventBus: number; queued: number; retrying: number;
    missingOutboxEvents: number; deliveryConfirmed: boolean; note: string;
  };
}
interface Revision { version: number; title: string; createdAt: string; isPublished: boolean }
interface CMSPage { id: string; slug: string; title: string; status: string; draftVersion: number; publishedVersion: number | null; document: PageDocument }
interface EmbeddableForm { id: string; slug: string; publishedVersion: number | null; document: { title: string } }
interface SiteMenuLink { id: string; label: string; slug: string }
interface SiteMenu { draftVersion: number; publishedVersion: number | null; document: { items: SiteMenuLink[] } }
interface SiteMenuRevision { version: number; createdAt: string; isPublished: boolean }
interface SiteRedirect {
  id: string; sourceSlug: string; targetSlug: string;
  statusCode: 307 | 308; enabled: boolean; version: number;
}
type RedirectEdit = Pick<SiteRedirect, 'targetSlug' | 'statusCode' | 'enabled'>;
const id = () => crypto.randomUUID();
const defaultSEO: PageSEO = { description: '', canonical_url: null, indexable: false };
const newDocument = (
  title: string, slug: string, asArticle = false,
  author = '', category = '', summary = '',
): PageDocument => ({
  schema_version: 1, title, slug, seo: { ...defaultSEO },
  content_type: asArticle ? 'article' : 'page',
  blog: asArticle ? { author: author.trim(), category: category.trim(), summary: summary.trim(), reviewer: null, locale: 'en' } : null,
  nodes: [
  { id: id(), kind: 'section', children: [{ id: id(), kind: 'heading', text: title }, { id: id(), kind: 'paragraph', text: 'Edit this introduction.' }] },
] });
const newBlock = (kind: Exclude<Kind, 'section'>): Node => kind === 'heading' ? { id: id(), kind, text: 'Heading' }
  : kind === 'paragraph' ? { id: id(), kind, text: 'Describe this section.' }
    : kind === 'image' ? { id: id(), kind, text: 'Image description', url: '/favicon.svg' }
      : { id: id(), kind, text: 'Learn more', url: '/contact' };
function mapNodes(nodes: Node[], target: string, change: (node: Node) => Node): Node[] {
  return nodes.map((node) => node.id === target ? change(node)
    : node.children ? { ...node, children: mapNodes(node.children, target, change) } : node);
}
function move(items: Node[], identifier: string, delta: number): Node[] {
  return reorderNodes(items, identifier, delta);
}
function render(node: Node): ReactNode {
  if (node.kind === 'heading') return <h2 key={node.id} className={appearanceClass(node)}>{node.text}</h2>;
  if (node.kind === 'paragraph') return <p key={node.id} className={appearanceClass(node)}>{node.text}</p>;
  if (node.kind === 'image') return <img key={node.id} className={appearanceClass(node)} src={node.url ?? ''} alt={node.text ?? ''} loading="lazy"/>;
  if (node.kind === 'button') return <span className={'button button--primary ' + appearanceClass(node)} key={node.id}>{node.text}</span>;
  if (node.kind === 'form') return <div key={node.id} className={'site-cms-form-placeholder ' + appearanceClass(node)}
    role="note">First-party form: {node.text}. Live submissions are disabled in this private preview.</div>;
  return <section key={node.id} className={'site-cms-preview-section ' + appearanceClass(node)}>{(node.children ?? []).map(render)}</section>;
}
function message(reason: unknown): string {
  if (reason && typeof reason === 'object' && 'detail' in reason) {
    const detail = (reason as { detail?: unknown }).detail;
    if (detail && typeof detail === 'object' && 'detail' in detail) return String((detail as { detail: unknown }).detail);
  }
  return reason instanceof Error ? reason.message : 'The request could not be completed.';
}

function downloadJson(manifest: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function WebsiteCMSPage() {
  const { activeWorkspace } = useWorkspace();
  const workspaceId = activeWorkspace?.id;
  const [pages, setPages] = useState<CMSPage[]>([]);
  const [embeddableForms, setEmbeddableForms] = useState<EmbeddableForm[]>([]);
  const [formEmbedSlug, setFormEmbedSlug] = useState('');
  useEffect(() => {
    if (!workspaceId) {
      setEmbeddableForms([]);
      return;
    }
    let active = true;
    void request<EmbeddableForm[]>('/site-forms')
      .then((forms) => { if (active) setEmbeddableForms(forms.filter((form) => form.publishedVersion !== null)); })
      .catch(() => { if (active) setEmbeddableForms([]); });
    return () => { active = false; };
  }, [workspaceId]);

  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [metrics, setMetrics] = useState<WebsiteMetrics | null>(null);
  const [siteMenu, setSiteMenu] = useState<SiteMenu | null>(null);
  const [menuDraft, setMenuDraft] = useState<SiteMenuLink[]>([]);
  const [menuHistory, setMenuHistory] = useState<SiteMenuRevision[]>([]);
  const [menuChoice, setMenuChoice] = useState('');
  const [menuBusy, setMenuBusy] = useState(false);
  const [menuError, setMenuError] = useState('');
  const [menuNote, setMenuNote] = useState('');
  const [redirects, setRedirects] = useState<SiteRedirect[]>([]);
  const [redirectEdits, setRedirectEdits] = useState<Record<string, RedirectEdit>>({});
  const [redirectSource, setRedirectSource] = useState('');
  const [redirectTarget, setRedirectTarget] = useState('');
  const [redirectStatus, setRedirectStatus] = useState<307 | 308>(308);
  const [redirectBusy, setRedirectBusy] = useState(false);
  const [redirectError, setRedirectError] = useState('');
  const [redirectNote, setRedirectNote] = useState('');
  const [selected, setSelected] = useState<CMSPage | null>(null);
  const [editing, setEditing] = useState(() => startDraftHistory<PageDocument>(null));
  const draft = editing.present;
  const resetDraft = useCallback((document: PageDocument | null) => {
    setEditing(startDraftHistory(document));
  }, []);
  const setDraft = useCallback((change: SetStateAction<PageDocument | null>) => {
    setEditing((history) => reviseDraftHistory(history, change));
  }, []);
  const [online, setOnline] = useState(() => typeof navigator === 'undefined' || navigator.onLine);
  const [saveBlocked, setSaveBlocked] = useState(false);
  const [saveConflict, setSaveConflict] = useState(false);
  const [serverConflict, setServerConflict] = useState<CMSPage | null>(null);
  const [recoverTitle, setRecoverTitle] = useState('Recovered page');
  const [recoverSlug, setRecoverSlug] = useState('recovered-page');
  const [saveNote, setSaveNote] = useState('');
  const saveRef = useRef<() => Promise<void>>(async () => {});
  const [sectionId, setSectionId] = useState<string | null>(null);
  const [draggedItem, setDraggedItem] = useState<{ id: string; type: 'section' | 'block' } | null>(null);
  const [name, setName] = useState('New page');
  const [slug, setSlug] = useState('new-page');
  const [newContentType, setNewContentType] = useState<'page' | 'article'>('page');
  const [newAuthor, setNewAuthor] = useState('');
  const [newCategory, setNewCategory] = useState('');
  const [newSummary, setNewSummary] = useState('');
  const [copyTitle, setCopyTitle] = useState('');
  const [copySlug, setCopySlug] = useState('');
  const [importContent, setImportContent] = useState('');
  const [importTitle, setImportTitle] = useState('Imported page');
  const [importSlug, setImportSlug] = useState('imported-page');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!workspaceId) return;
    setBusy(true); setError('');
    try {
      const saved = await request<CMSPage[]>('/site-cms/pages');
      setPages(saved);
      try {
        const rules = await request<SiteRedirect[]>('/site-cms/redirects');
        setRedirects(rules);
        setRedirectEdits({});
        setRedirectError('');
      } catch (reason) {
        setRedirectError('Redirect rules could not load: ' + message(reason));
      }
      try {
        const menu = await request<SiteMenu>('/site-cms/menu');
        setSiteMenu(menu);
        setMenuDraft(menu.document.items);
        setMenuHistory(menu.draftVersion
          ? await request<SiteMenuRevision[]>('/site-cms/menu/revisions') : []);
        setMenuError('');
      } catch (reason) {
        setSiteMenu(null);
        setMenuError('Navigation could not be loaded: ' + message(reason));
      }
      setMetrics(await request<WebsiteMetrics>('/site-analytics/summary?days=30').catch(() => null));
      setSelected((current) => current && saved.some((page) => page.id === current.id) ? current : null);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }, [workspaceId]);
  useEffect(() => { setPages([]); setSelected(null); resetDraft(null); setSiteMenu(null); setMenuDraft([]); setMenuHistory([]); void load(); }, [load, resetDraft]);
  const refreshRedirects = async () => {
    if (Object.keys(redirectEdits).length > 0
      && !window.confirm('Discard unsaved redirect rule edits and reload server settings?')) return;
    setRedirectBusy(true); setRedirectError('');
    try {
      const rules = await request<SiteRedirect[]>('/site-cms/redirects');
      setRedirects(rules);
      setRedirectEdits({});
      setRedirectNote('Redirect rules reloaded.');
    } catch (reason) { setRedirectError(message(reason)); }
    finally { setRedirectBusy(false); }
  };
  const createRedirect = async () => {
    if (redirectBusy || !redirectSource.trim() || !redirectTarget) return;
    setRedirectBusy(true); setRedirectError(''); setRedirectNote('');
    try {
      const created = await request<SiteRedirect>('/site-cms/redirects', {
        method: 'POST',
        body: JSON.stringify({
          source_slug: redirectSource.trim(),
          target_slug: redirectTarget,
          status_code: redirectStatus,
        }),
      });
      setRedirects((items) => [...items, created].sort((a, b) => a.sourceSlug.localeCompare(b.sourceSlug)));
      setRedirectSource('');
      setRedirectTarget('');
      setRedirectNote('Redirect created. The old URL now forwards to its published destination.');
    } catch (reason) { setRedirectError(message(reason)); }
    finally { setRedirectBusy(false); }
  };
  const changeRedirect = (rule: SiteRedirect, change: Partial<RedirectEdit>) => {
    setRedirectEdits((old) => ({
      ...old,
      [rule.id]: { targetSlug: rule.targetSlug, statusCode: rule.statusCode,
        enabled: rule.enabled, ...old[rule.id], ...change },
    }));
    setRedirectError(''); setRedirectNote('');
  };
  const saveRedirect = async (rule: SiteRedirect) => {
    if (redirectBusy) return;
    const editing = redirectEdits[rule.id];
    if (!editing) return;
    setRedirectBusy(true); setRedirectError(''); setRedirectNote('');
    try {
      const changed = await request<SiteRedirect>('/site-cms/redirects/' + rule.id, {
        method: 'PUT',
        body: JSON.stringify({
          expected_version: rule.version, target_slug: editing.targetSlug,
          status_code: editing.statusCode, enabled: editing.enabled,
        }),
      });
      setRedirects((items) => items.map((item) => item.id === rule.id ? changed : item));
      setRedirectEdits((old) => {
        const next = { ...old };
        delete next[rule.id];
        return next;
      });
      setRedirectNote('Redirect /' + changed.sourceSlug + ' saved as version ' + changed.version + '.');
    } catch (reason) {
      setRedirectError(message(reason) + ' Your proposed changes remain visible. Reload to resolve a version conflict.');
    } finally { setRedirectBusy(false); }
  };
  const menuDirty = !!siteMenu && !sameDraftContent(menuDraft, siteMenu.document.items);
  const updateMenu = (next: SiteMenuLink[]) => {
    setMenuDraft(next);
    setMenuNote('');
    setMenuError('');
  };
  const addMenuLink = () => {
    const page = pages.find((entry) =>
      entry.publishedVersion !== null && entry.slug === menuChoice);
    if (!page || !siteMenu || menuDraft.some((item) => item.slug === page.slug) || menuDraft.length >= 20) return;
    updateMenu([...menuDraft, { id: id(), label: page.title, slug: page.slug }]);
    setMenuChoice('');
  };
  const removeMenuLink = (linkId: string) => {
    updateMenu(menuDraft.filter((entry) => entry.id !== linkId));
  };
  const moveMenuLink = (linkId: string, offset: number) => {
    const index = menuDraft.findIndex((entry) => entry.id === linkId);
    const nextIndex = index + offset;
    if (index < 0 || nextIndex < 0 || nextIndex >= menuDraft.length) return;
    const moved = [...menuDraft];
    [moved[index], moved[nextIndex]] = [moved[nextIndex]!, moved[index]!];
    updateMenu(moved);
  };
  const refreshSiteMenu = async () => {
    if (menuDirty && !window.confirm('Discard unsaved navigation edits and reload the latest server revision?')) return;
    setMenuBusy(true); setMenuError('');
    try {
      const current = await request<SiteMenu>('/site-cms/menu');
      setSiteMenu(current);
      setMenuDraft(current.document.items);
      setMenuHistory(current.draftVersion
        ? await request<SiteMenuRevision[]>('/site-cms/menu/revisions') : []);
      setMenuNote('Navigation reloaded from the server.');
    } catch (reason) { setMenuError(message(reason)); }
    finally { setMenuBusy(false); }
  };
  const refreshMenuHistory = async () => {
    try {
      setMenuHistory(await request<SiteMenuRevision[]>('/site-cms/menu/revisions'));
    } catch {
      // A failed history refresh cannot undo an already acknowledged server write.
      setMenuNote((note) => note + ' Revision history could not refresh; reload to retry.');
    }
  };
  const saveSiteMenu = async () => {
    if (!siteMenu || !menuDirty || menuBusy) return;
    setMenuBusy(true); setMenuError(''); setMenuNote('Saving navigation…');
    try {
      const saved = await request<SiteMenu>('/site-cms/menu', {
        method: 'PUT',
        body: JSON.stringify({ expected_version: siteMenu.draftVersion, document: { items: menuDraft } }),
      });
      setSiteMenu(saved);
      setMenuDraft(saved.document.items);
      setMenuNote('Navigation draft saved as version ' + saved.draftVersion + '.');
      void refreshMenuHistory();
    } catch (reason) {
      setMenuError(message(reason) + ' Your unsaved navigation edits remain in this tab.');
      setMenuNote('Navigation save was not acknowledged.');
    } finally { setMenuBusy(false); }
  };
  const publishSiteMenu = async () => {
    if (!siteMenu || menuDirty || menuBusy || !siteMenu.draftVersion) return;
    setMenuBusy(true); setMenuError(''); setMenuNote('Validating linked pages…');
    try {
      const published = await request<SiteMenu>('/site-cms/menu/publish', {
        method: 'POST',
        body: JSON.stringify({ expected_version: siteMenu.draftVersion }),
      });
      setSiteMenu(published);
      setMenuDraft(published.document.items);
      setMenuNote('Navigation revision ' + published.publishedVersion + ' is live.');
      void refreshMenuHistory();
    } catch (reason) {
      setMenuError(message(reason));
      setMenuNote('Navigation publication was not acknowledged.');
    } finally { setMenuBusy(false); }
  };
  const restoreSiteMenu = async (version: number) => {
    if (!siteMenu || menuDirty || menuBusy || !window.confirm('Restore menu version ' + version + ' as a new private draft?')) return;
    setMenuBusy(true); setMenuError('');
    try {
      const saved = await request<SiteMenu>('/site-cms/menu/restore/' + version, {
        method: 'POST', body: JSON.stringify({ expected_version: siteMenu.draftVersion }),
      });
      setSiteMenu(saved);
      setMenuDraft(saved.document.items);
      setMenuNote('Historical menu copied as draft version ' + saved.draftVersion + '. Review before publishing.');
      void refreshMenuHistory();
    } catch (reason) { setMenuError(message(reason)); }
    finally { setMenuBusy(false); }
  };
  const refreshRevisions = async (pageId: string) => {
    try { setRevisions(await request<Revision[]>('/site-cms/pages/' + pageId + '/revisions')); }
    catch (reason) { setError(message(reason)); }
  };
  const open = (page: CMSPage, force = false) => {
    if (!force && busy) return;
    if (!force && dirty && !window.confirm('Discard unsaved content changes?')) return;
    setSelected(page); resetDraft(page.document); setSectionId(page.document.nodes[0]?.id ?? null); setError('');
    setSaveBlocked(false); setSaveConflict(false); setServerConflict(null);
    setRecoverTitle('Recovered ' + page.title);
    setRecoverSlug((page.slug + '-recovered').slice(0, 160));
    setSaveNote('Loaded the latest acknowledged page revision.');
    setCopyTitle('Copy of ' + page.title);
    setCopySlug((page.slug + '-copy').slice(0, 160));
    void refreshRevisions(page.id);
  };
  const create = async () => {
    setBusy(true); setError('');
    try {
      const page = await request<CMSPage>('/site-cms/pages', { method: 'POST', body: JSON.stringify(newDocument(name.trim(), slug.trim(), newContentType === 'article', newAuthor, newCategory, newSummary)) });
      setPages((items) => [page, ...items]); open(page, true);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const duplicatePage = async () => {
    if (!selected || busy || dirty) return;
    setBusy(true); setError('');
    try {
      const copied = await request<CMSPage>('/site-cms/pages/' + selected.id + '/duplicate', {
        method: 'POST',
        body: JSON.stringify({ slug: copySlug.trim(), title: copyTitle.trim() }),
      });
      setPages((items) => [copied, ...items]);
      open(copied, true);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const exportPage = async () => {
    if (!selected || busy || dirty) return;
    setBusy(true); setError('');
    try {
      const manifest = await request<{
        format: 'northstar.site-page'; version: 1; page: PageDocument;
      }>('/site-cms/pages/' + selected.id + '/export');
      downloadJson(manifest, selected.slug + '.site-page.json');
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const createImportedDraft = async (
    manifest: Record<string, unknown>,
    newSlug: string,
    newTitle: string,
  ): Promise<boolean> => {
    if (busy) return false;
    setBusy(true); setError('');
    try {
      const result = await request<CMSPage>('/site-cms/pages/import', {
        method: 'POST',
        body: JSON.stringify({
          ...manifest, new_slug: newSlug.trim(), new_title: newTitle.trim(),
        }),
      });
      setPages((items) => [result, ...items]);
      open(result, true);
      return true;
    } catch (reason) {
      setError(message(reason));
      return false;
    } finally { setBusy(false); }
  };
  const importPage = async () => {
    if (!importContent || busy || dirty) return;
    try {
      const imported: unknown = JSON.parse(importContent);
      if (!imported || typeof imported !== 'object' || Array.isArray(imported)) {
        throw new Error('Choose a valid site page JSON manifest.');
      }
      const importedOk = await createImportedDraft(
        imported as Record<string, unknown>, importSlug, importTitle,
      );
      if (importedOk) setImportContent('');
    } catch (reason) { setError(message(reason)); }
  };
  const edit = (identifier: string, change: (node: Node) => Node) => {
    setDraft((current) => current ? { ...current, nodes: mapNodes(current.nodes, identifier, change) } : null);
  };
  const addSection = () => {
    const identifier = id();
    setDraft((current) => current ? { ...current, nodes: [...current.nodes, { id: identifier, kind: 'section', children: [] }] } : null);
    setSectionId(identifier);
  };
  const currentSection = draft?.nodes.find((node) => node.id === sectionId) ?? draft?.nodes[0];
  const seo = draft?.seo ?? defaultSEO;
  const refreshEmbeddableForms = async () => {
    try {
      const listed = await request<EmbeddableForm[]>('/site-forms');
      setEmbeddableForms(listed.filter((form) => form.publishedVersion !== null));
    } catch (reason) {
      setError('Published form choices could not load: ' + message(reason));
    }
  };
  const addFormBlock = () => {
    const chosen = embeddableForms.find((form) => form.slug === formEmbedSlug);
    if (!chosen || !workspaceId || !currentSection) return;
    const embedded: Node = {
      id: id(), kind: 'form', text: chosen.document.title,
      url: '/api/v1/site-forms/public/' + workspaceId + '/' + chosen.slug,
    };
    edit(currentSection.id, (section) => ({
      ...section, children: [...(section.children ?? []), embedded],
    }));
    setFormEmbedSlug('');
  };
  const addBlock = (kind: Exclude<Kind, 'section'>) => {
    if (currentSection) edit(currentSection.id, (section) => ({ ...section, children: [...(section.children ?? []), newBlock(kind)] }));
  };
  const moveSection = (targetId: string, direction: number) => {
    setDraft((current) => current ? { ...current, nodes: reorderNodes(current.nodes, targetId, direction) } : null);
  };
  const duplicateSection = (targetId: string) => {
    setDraft((current) => current ? { ...current, nodes: duplicateSibling(current.nodes, targetId, id) } : null);
  };
  const deleteSection = (targetId: string) => {
    if (!draft || draft.nodes.length <= 1 || !window.confirm('Remove this section from the unsaved draft?')) return;
    const next = draft.nodes.filter((node) => node.id !== targetId);
    setDraft({ ...draft, nodes: next });
    if (sectionId === targetId) setSectionId(next[0]?.id ?? null);
  };
  const duplicateBlock = (blockId: string) => {
    if (currentSection) edit(currentSection.id, (section) => ({
      ...section, children: duplicateSibling(section.children ?? [], blockId, id),
    }));
  };
  const deleteBlock = (blockId: string) => {
    if (!currentSection || !window.confirm('Remove this block from the unsaved draft?')) return;
    edit(currentSection.id, (section) => ({
      ...section, children: removeChild(section.children ?? [], blockId),
    }));
  };
  const moveBlock = (blockId: string, destinationId: string) => {
    setDraft((current) => current ? {
      ...current, nodes: moveBlockBetweenSections(current.nodes, blockId, destinationId),
    } : null);
  };
  const dropSection = (targetId: string) => {
    if (draggedItem?.type !== 'section' || draggedItem.id === targetId || !draft) return;
    const from = draft.nodes.findIndex((node) => node.id === draggedItem.id);
    const to = draft.nodes.findIndex((node) => node.id === targetId);
    if (from < 0 || to < 0) return;
    setDraft({ ...draft, nodes: reorderNodes(draft.nodes, draggedItem.id, to - from) });
    setDraggedItem(null);
  };
  const dropBlock = (targetId: string) => {
    if (draggedItem?.type !== 'block' || draggedItem.id === targetId || !draft || !currentSection) return;
    const sourceSection = draft.nodes.find((node) => (node.children ?? []).some((child) => child.id === draggedItem.id));
    if (!sourceSection) return;
    const targetIndex = (currentSection.children ?? []).findIndex((node) => node.id === targetId);
    if (targetIndex < 0) return;
    const fromIndex = sourceSection.id === currentSection.id
      ? (currentSection.children ?? []).findIndex((node) => node.id === draggedItem.id)
      : -1;
    // Dropping onto the following block places it after that block, not back in the old slot.
    const insertionIndex = fromIndex >= 0 && fromIndex < targetIndex ? targetIndex + 1 : targetIndex;
    setDraft({
      ...draft,
      nodes: moveBlockBetweenSections(draft.nodes, draggedItem.id, currentSection.id, insertionIndex),
    });
    setDraggedItem(null);
  };

  const dirty = !!selected && !!draft && !sameDraftContent(draft, selected.document);
  const replace = (page: CMSPage) => {
    setSelected(page);
    resetDraft(page.document);
    setSaveBlocked(false); setSaveConflict(false); setServerConflict(null);
    setSaveNote('Saved as server revision ' + page.draftVersion + '.');
    setPages((items) => items.map((item) => item.id === page.id ? page : item));
    void refreshRevisions(page.id);
  };
  const save = async () => {
    if (!selected || !draft || busy || saveConflict || !online) return;
    const snapshot = draft;
    const pageId = selected.id;
    setBusy(true); setError(''); setSaveNote('Saving to the server…');
    try {
      const saved = await request<CMSPage>('/site-cms/pages/' + pageId, {
        method: 'PUT',
        body: JSON.stringify({ expected_version: selected.draftVersion, document: draft }),
      });
      // Never replace edits made while this request was in flight.
      setSelected((current) => current?.id === pageId ? saved : current);
      setPages((items) => items.map((page) => page.id === pageId ? saved : page));
      setEditing((history) => sameDraftContent(history.present, snapshot)
        ? { ...history, present: saved.document }
        : history);
      setSaveBlocked(false);
      setSaveNote('Saved as server revision ' + saved.draftVersion + '.');
      void refreshRevisions(saved.id);
    } catch (reason) {
      setSaveBlocked(true);
      if (reason instanceof ApiError && reason.status === 409) {
        setSaveConflict(true);
        setSaveNote('Another editor changed this page. Autosave stopped. Compare both drafts before choosing a recovery option.');
        try {
          const currentPages = await request<CMSPage[]>('/site-cms/pages');
          setServerConflict(currentPages.find((page) => page.id === pageId) ?? null);
        } catch {
          setServerConflict(null);
        }
      } else {
        setSaveNote('Autosave paused after a failed request. Changes remain in this tab; use Retry save.');
      }
      setError(message(reason));
    } finally { setBusy(false); }
  };
  useEffect(() => {
    const handleOffline = () => {
      setOnline(false);
      setSaveNote('You are offline. Local edits remain in this tab; they have not reached the server.');
    };
    const handleOnline = () => {
      setOnline(true);
      setSaveNote('Connection restored. Pending edits can be saved to the server.');
      // A known 409 conflict still requires deliberate reconciliation.
      if (!saveConflict) setSaveBlocked(false);
    };
    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);
    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, [saveConflict]);
  useEffect(() => { saveRef.current = save; });
  // Debounced database autosave uses the same optimistic-version API as manual Save.
  useEffect(() => {
    if (!dirty || !draft || !selected || busy || saveBlocked || saveConflict || !online) return;
    const timer = window.setTimeout(() => { void saveRef.current(); }, 3000);
    return () => window.clearTimeout(timer);
  }, [selected?.id, selected?.draftVersion, draft, dirty, busy, saveBlocked, saveConflict, online]);
  useEffect(() => {
    if (!dirty && !busy) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [dirty, busy]);
  useEffect(() => {
    const onHistoryShortcut = (event: KeyboardEvent) => {
      if ((!event.ctrlKey && !event.metaKey) || event.key.toLowerCase() !== 'z') return;
      const target = event.target;
      if (!(target instanceof HTMLElement) || !target.closest('.site-cms-page')) return;
      if (target.closest('input, textarea, select, [contenteditable="true"]')) return;
      event.preventDefault();
      setSaveBlocked(false);
      setEditing((history) => event.shiftKey ? redoDraftHistory(history) : undoDraftHistory(history));
    };
    window.addEventListener('keydown', onHistoryShortcut);
    return () => window.removeEventListener('keydown', onHistoryShortcut);
  }, []);
  const reloadServerPage = async () => {
    if (!selected || busy || !window.confirm('Discard local unsaved changes and load the latest server revision?')) return;
    setBusy(true); setError('');
    try {
      const latest = await request<CMSPage[]>('/site-cms/pages');
      setPages(latest);
      const server = latest.find((page) => page.id === selected.id);
      if (!server) throw new Error('This page is no longer available in your workspace.');
      open(server, true);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const exportLocalDraft = () => {
    if (!selected || !draft) return;
    downloadJson({
      format: 'northstar.site-page', version: 1, page: draft,
    }, selected.slug + '-unsaved.site-page.json');
    setSaveNote('Unsaved draft exported for recovery; nothing was sent to the server.');
  };
  const recoverAsSeparateDraft = async () => {
    if (!selected || !draft || !saveConflict || busy) return;
    if (!window.confirm('Keep the server version unchanged and save local edits as a separate private draft?')) return;
    await createImportedDraft(
      { format: 'northstar.site-page', version: 1, page: draft },
      recoverSlug, recoverTitle,
    );
  };
  const transition = async (action: Action) => {
    if (!selected || dirty) return;
    if (action === 'archive' && !window.confirm('Archive this page and remove its public URL? The source revisions will be preserved.')) return;
    setBusy(true); setError('');
    try { replace(await request<CMSPage>('/site-cms/pages/' + selected.id + '/' + action, { method: 'POST' })); }
    catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const restore = async (version: number) => {
    if (!selected || dirty || busy || version === selected.draftVersion) return;
    if (!window.confirm('Restore revision ' + version + ' as a new draft? The current published page will remain unchanged.')) return;
    setBusy(true); setError('');
    try {
      replace(await request<CMSPage>('/site-cms/pages/' + selected.id + '/restore/' + version, {
        method: 'POST', body: JSON.stringify({ expected_version: selected.draftVersion }),
      }));
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const publicUrl = selected && activeWorkspace
    ? apiConfig.baseUrl + '/site-cms/public/' + activeWorkspace.id + '/' + selected.slug : '';

  return <div className="page site-cms-page">
    <div className="page-heading page-heading--split"><div><h2>Website CMS</h2>
      <p>Create content blocks, review pages, and publish immutable versions.</p></div>
      <Button variant="secondary" icon={RefreshCw} disabled={busy || menuBusy || redirectBusy}
        onClick={() => {
          if ((dirty || menuDirty || Object.keys(redirectEdits).length > 0)
            && !window.confirm('Discard unsaved page, navigation or redirect changes and reload workspace data?')) return;
          void load();
        }}>Refresh</Button></div>
    {error ? <div role="alert" className="form-error">{error}</div> : null}
    {!activeWorkspace ? <Card><p>Select a workspace to manage its site.</p></Card> :
      <div className="site-cms-layout">
        <Card><h3>Pages</h3><div className="site-cms-pages">
          {pages.map((page) => <button key={page.id} type="button" className={selected?.id === page.id ? 'is-selected' : ''}
            onClick={() => open(page)}><strong>{page.title}</strong><small>{page.document.content_type === 'article' ? 'Article' : 'Page'} · /{page.slug} · {page.status}</small></button>)}
          {!busy && pages.length === 0 ? <p>No pages yet. Create one below.</p> : null}
        </div><form className="site-cms-create" onSubmit={(event) => { event.preventDefault(); void create(); }}>
          <label>Page title<input value={name} required maxLength={180} onChange={(event) => setName(event.target.value)}/></label>
          <label>URL slug<input value={slug} required maxLength={160} pattern="[a-z0-9]+(-[a-z0-9]+)*" onChange={(event) => setSlug(event.target.value)}/></label>
          <label>Content type
            <select value={newContentType} onChange={(event) => setNewContentType(event.target.value as 'page' | 'article')}>
              <option value="page">Website page</option>
              <option value="article">Blog article</option>
            </select>
          </label>
          {newContentType === 'article' ? <fieldset className="site-cms-seo">
            <legend>Editorial information</legend>
            <label>Verified author
              <input required maxLength={120} value={newAuthor}
                onChange={(event) => setNewAuthor(event.target.value)} placeholder="Actual author or team" />
            </label>
            <label>Category
              <input required maxLength={80} value={newCategory}
                onChange={(event) => setNewCategory(event.target.value)} />
            </label>
            <label>Article summary
              <textarea required maxLength={240} rows={3} value={newSummary}
                onChange={(event) => setNewSummary(event.target.value)} />
            </label>
          </fieldset> : null}
          <Button type="submit" icon={FilePlus2}
            disabled={busy || !name.trim() || (newContentType === 'article'
              && (!newAuthor.trim() || !newCategory.trim() || !newSummary.trim()))}>Create draft</Button>
        </form>
        <div className="site-cms-import">
          <h4>Import page JSON</h4>
          <p>Import a previously exported page as a new private draft. Existing pages are never overwritten.</p>
          <form className="site-cms-import-form" onSubmit={(event) => { event.preventDefault(); void importPage(); }}>
            <label>Exported JSON manifest (up to 10 MB)
              <input type="file" accept=".json,application/json" onChange={(event) => {
                const file = event.target.files?.[0];
                setImportContent('');
                if (!file) return;
                if (file.size > 10 * 1024 * 1024) {
                  setError('The import file must be 10 MB or smaller.');
                  return;
                }
                void file.text().then((value) => { setImportContent(value); setError(''); })
                  .catch(() => setError('Could not read the selected file.'));
              }} />
            </label>
            <label>New page title
              <input required maxLength={180} value={importTitle}
                onChange={(event) => setImportTitle(event.target.value)} />
            </label>
            <label>New URL slug
              <input required pattern="[a-z0-9]+(-[a-z0-9]+)*" maxLength={160}
                value={importSlug} onChange={(event) => setImportSlug(event.target.value)} />
            </label>
            <Button type="submit" variant="secondary" disabled={busy || dirty || !importContent || !importSlug.trim() || !importTitle.trim()}>Import as draft</Button>
          </form>
        </div></Card>
        <div className="site-cms-workspace">
          <WebsiteContentPreflight />
          <WebsiteFormsPanel key={activeWorkspace.id} workspaceId={activeWorkspace.id}
            onFormsChanged={() => { void refreshEmbeddableForms(); }} />
          <Card>
            <div className="site-cms-navigation-heading">
              <div><h3>Page redirects</h3>
                <p>Forward an old or archived URL to a currently published page. No external or unpublished destinations are permitted.</p>
              </div>
              <Button size="sm" variant="secondary" icon={RefreshCw}
                disabled={redirectBusy} onClick={() => { void refreshRedirects(); }}>Reload redirects</Button>
            </div>
            {redirectError ? <p role="alert" className="form-error">{redirectError}</p> : null}
            {redirectNote ? <p role="status" className="site-cms-save-note">{redirectNote}</p> : null}
            <form className="site-cms-redirect-create" onSubmit={(event) => { event.preventDefault(); void createRedirect(); }}>
              <label>Previous URL slug
                <input value={redirectSource} maxLength={160} required
                  pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="old-page"
                  disabled={redirectBusy}
                  onChange={(event) => setRedirectSource(event.target.value)} />
              </label>
              <label>Published destination
                <select value={redirectTarget} required disabled={redirectBusy}
                  onChange={(event) => setRedirectTarget(event.target.value)}>
                  <option value="">Choose a published page…</option>
                  {pages.filter((page) => page.publishedVersion !== null).map((page) =>
                    <option key={page.id} value={page.slug}>{page.title} (/{page.slug})</option>)}
                </select>
              </label>
              <label>Redirect type
                <select value={redirectStatus} disabled={redirectBusy}
                  onChange={(event) => setRedirectStatus(Number(event.target.value) as 307 | 308)}>
                  <option value={308}>Permanent (308)</option>
                  <option value={307}>Temporary (307)</option>
                </select>
              </label>
              <Button type="submit" icon={Plus} variant="secondary"
                disabled={redirectBusy || !redirectSource.trim() || !redirectTarget}>
                Create redirect
              </Button>
            </form>
            <div className="site-cms-redirect-list">
              {redirects.length === 0 ? <p>No redirect rules have been configured.</p> : null}
              {redirects.map((rule) => {
                const edited = redirectEdits[rule.id] ?? rule;
                const hasChange = !sameDraftContent(
                  { targetSlug: edited.targetSlug, statusCode: edited.statusCode, enabled: edited.enabled },
                  { targetSlug: rule.targetSlug, statusCode: rule.statusCode, enabled: rule.enabled },
                );
                return <div className="site-cms-redirect-row" key={rule.id}>
                  <strong>/{rule.sourceSlug}</strong>
                  <label>Destination
                    <select value={edited.targetSlug} disabled={redirectBusy}
                      onChange={(event) => changeRedirect(rule, { targetSlug: event.target.value })}>
                      {!pages.some((page) => page.slug === edited.targetSlug && page.publishedVersion !== null)
                        ? <option value={edited.targetSlug}>/{edited.targetSlug} (not currently published)</option> : null}
                      {pages.filter((page) => page.publishedVersion !== null).map((page) =>
                        <option key={page.id} value={page.slug}>/{page.slug}</option>)}
                    </select>
                  </label>
                  <label>Type
                    <select value={edited.statusCode} disabled={redirectBusy}
                      onChange={(event) => changeRedirect(rule, { statusCode: Number(event.target.value) as 307 | 308 })}>
                      <option value={308}>308 permanent</option>
                      <option value={307}>307 temporary</option>
                    </select>
                  </label>
                  <label className="site-cms-redirect-enabled">
                    <input type="checkbox" checked={edited.enabled} disabled={redirectBusy}
                      onChange={(event) => changeRedirect(rule, { enabled: event.target.checked })}/>
                    Enabled
                  </label>
                  <Button size="sm" variant="secondary" icon={Save}
                    disabled={redirectBusy || !hasChange}
                    onClick={() => { void saveRedirect(rule); }}>Save rule</Button>
                  <small>Revision {rule.version} · {rule.enabled ? 'Active' : 'Disabled'}</small>
                </div>;
              })}
            </div>
          </Card>
          <Card>
            <div className="site-cms-navigation-heading">
              <div><h3>Public navigation</h3>
                <p>Choose published pages for your site's primary menu. A menu becomes public only after you publish its saved revision.</p>
              </div>
              <Button variant="secondary" size="sm" icon={RefreshCw}
                disabled={menuBusy} onClick={() => { void refreshSiteMenu(); }}>Reload menu</Button>
            </div>
            {menuError ? <p role="alert" className="form-error">{menuError}</p> : null}
            {menuNote ? <p role="status" className="site-cms-save-note">{menuNote}</p> : null}
            {!siteMenu ? <p>Public navigation is not available until its owner settings load.</p> : <>
              <p className="site-cms-menu-meta">Draft revision {siteMenu.draftVersion || 'not created'} · Live revision {siteMenu.publishedVersion ?? 'none'}</p>
              <div className="site-cms-menu-list">
                {menuDraft.map((entry, index) => <div className="site-cms-menu-item" key={entry.id}>
                  <label>Link {index + 1} label
                    <input value={entry.label} maxLength={80} disabled={menuBusy}
                      onChange={(event) => updateMenu(menuDraft.map((item) =>
                        item.id === entry.id ? { ...item, label: event.target.value } : item))} />
                  </label>
                  <span className="site-cms-menu-target">/{entry.slug}{!pages.some((page) =>
                    page.slug === entry.slug && page.publishedVersion !== null)
                    ? ' · Not currently published' : ''}</span>
                  <div className="site-cms-menu-controls">
                    <button type="button" aria-label={'Move menu link ' + (index + 1) + ' up'}
                      disabled={menuBusy || index === 0} onClick={() => moveMenuLink(entry.id, -1)}><ArrowUp size={17}/></button>
                    <button type="button" aria-label={'Move menu link ' + (index + 1) + ' down'}
                      disabled={menuBusy || index === menuDraft.length - 1} onClick={() => moveMenuLink(entry.id, 1)}><ArrowDown size={17}/></button>
                    <button type="button" aria-label={'Remove menu link ' + (index + 1)}
                      disabled={menuBusy} onClick={() => removeMenuLink(entry.id)}><Trash2 size={17}/></button>
                  </div>
                </div>)}
                {menuDraft.length === 0 ? <p>No navigation links configured yet.</p> : null}
              </div>
              <div className="site-cms-menu-add">
                <label>Published page to add
                  <select value={menuChoice} disabled={menuBusy || menuDraft.length >= 20}
                    onChange={(event) => setMenuChoice(event.target.value)}>
                    <option value="">Select a published page…</option>
                    {pages.filter((page) => page.publishedVersion !== null
                      && !menuDraft.some((item) => item.slug === page.slug))
                      .map((page) => <option key={page.id} value={page.slug}>{page.title} (/{page.slug})</option>)}
                  </select>
                </label>
                <Button icon={Plus} variant="secondary" size="sm"
                  disabled={!menuChoice || menuBusy || menuDraft.length >= 20}
                  onClick={addMenuLink}>Add link</Button>
              </div>
              <div className="site-cms-actions">
                <Button icon={Save} disabled={menuBusy || !menuDirty || menuDraft.some((item) => !item.label.trim())}
                  onClick={() => { void saveSiteMenu(); }}>Save menu draft</Button>
                <Button icon={ShieldCheck} variant="secondary"
                  disabled={menuBusy || menuDirty || siteMenu.draftVersion === 0
                    || siteMenu.publishedVersion === siteMenu.draftVersion}
                  onClick={() => { void publishSiteMenu(); }}>Publish navigation</Button>
              </div>
              {menuHistory.length > 0 ? <div className="site-cms-menu-history">
                <strong>Navigation revision history</strong>
                {menuHistory.slice(0, 10).map((revision) => <div key={revision.version}>
                  <span>Version {revision.version} {revision.isPublished ? '· live' : ''}</span>
                  <Button variant="secondary" size="sm"
                    disabled={menuBusy || menuDirty || revision.version === siteMenu.draftVersion}
                    onClick={() => { void restoreSiteMenu(revision.version); }}>Restore as draft</Button>
                </div>)}
              </div> : null}
            </>}
          </Card>
          <WebsiteAnalyticsReport />
          <Card><h3>Website engagement</h3><p>First-party, consent-eligible events from published pages (last 30 days).</p>
            <div className="site-cms-metrics">
              <div><strong>{metrics?.pageViews ?? '—'}</strong><span>Page views</span></div>
              <div><strong>{metrics?.ctaClicks ?? '—'}</strong><span>CTA clicks</span></div>
              <div><strong>{metrics?.pages.length ?? '—'}</strong><span>Viewed pages</span></div>
            </div>
            {metrics && metrics.pages.length > 0 ? <p>Top page: /{metrics.pages[0]?.slug} · {metrics.pages[0]?.pageViews} views</p> : null}
            {metrics?.formSubmissions && metrics.conversionDispatch ? <section className="site-cms-form-health"
              aria-label="Lead-capture receipt and event-bus reconciliation">
              <h4>Committed enquiry receipts</h4>
              <p>Authoritative database submissions, not optional visitor analytics. A submission is not an automatically qualified lead.</p>
              <div className="site-cms-metrics">
                <div><strong>{metrics.formSubmissions.total}</strong><span>Accepted forms</span></div>
                <div><strong>{metrics.conversionDispatch.publishedToEventBus}</strong><span>Events published to broker</span></div>
                <div><strong>{metrics.conversionDispatch.queued}</strong><span>Waiting for broker</span></div>
                <div><strong>{metrics.conversionDispatch.retrying}</strong><span>Broker retries needed</span></div>
                <div><strong>{metrics.conversionDispatch.missingOutboxEvents}</strong><span>Unmatched receipts</span></div>
              </div>
              {(metrics.conversionDispatch.retrying > 0 || metrics.conversionDispatch.missingOutboxEvents > 0)
                ? <p role="alert" className="site-cms-reconciliation-warning">
                  Some accepted enquiries require operational review. Do not create duplicate leads to repair them.
                </p> : null}
              <p>{metrics.conversionDispatch.note}</p>
              {metrics.formSubmissions.byForm.length > 0
                ? <p>Most-used form: /{metrics.formSubmissions.byForm[0]?.slug} ·
                  {' '}{metrics.formSubmissions.byForm[0]?.submissions} submissions</p> : null}
            </section> : null}
            <a className="site-cms-public-link" href={apiConfig.baseUrl + '/site-blog/' + activeWorkspace.id}
              target="_blank" rel="noopener noreferrer">View published blog <ExternalLink size={15} aria-hidden="true" /></a>
            <a className="site-cms-public-link" href={apiConfig.baseUrl + '/site-discovery/sitemap/' + activeWorkspace.id + '.xml'}
              target="_blank" rel="noopener noreferrer">View published XML sitemap <ExternalLink size={15} aria-hidden="true" /></a>
          </Card>
          {!draft || !selected ? <Card><h3>Select a page</h3><p>Choose an existing page or create a draft.</p></Card> : <>
            <Card><div className="site-cms-toolbar"><div><strong>{selected.title}</strong> <Badge tone={selected.status === 'published' ? 'success' : 'warning'}>{selected.status}</Badge>
              <small>{draft.content_type === 'article' ? 'Article' : 'Page'} · Draft revision {selected.draftVersion} · Published {selected.publishedVersion ?? 'never'}</small></div>
              <div className="site-cms-actions">
                <Button icon={Undo2} variant="secondary" disabled={busy || editing.past.length === 0}
                  onClick={() => { setSaveBlocked(false); setEditing((history) => undoDraftHistory(history)); }}>Undo</Button>
                <Button icon={Redo2} variant="secondary" disabled={busy || editing.future.length === 0}
                  onClick={() => { setSaveBlocked(false); setEditing((history) => redoDraftHistory(history)); }}>Redo</Button>
                <Button icon={Save} disabled={busy || !dirty || saveConflict}
                  onClick={() => { setSaveBlocked(false); void save(); }}>Save now</Button>
                <Button variant="secondary" icon={Send} disabled={busy || dirty || selected.status !== 'draft'} onClick={() => void transition('submit')}>Submit review</Button>
                <Button variant="secondary" icon={Check} disabled={busy || dirty || selected.status !== 'in_review'} onClick={() => void transition('approve')}>Approve</Button>
                <Button variant="secondary" icon={ShieldCheck} disabled={busy || dirty || selected.status !== 'approved'} onClick={() => void transition('publish')}>Publish</Button>
                <Button variant="secondary" icon={RefreshCw} disabled={busy || dirty || selected.status !== 'in_review'}
                  onClick={() => void transition('request_changes')}>Request changes</Button>
                <Button variant="secondary" icon={Trash2} disabled={busy || dirty || selected.status !== 'published'}
                  onClick={() => void transition('archive')}>Archive safely</Button>
                <Button variant="secondary" icon={RefreshCw} disabled={busy || dirty || selected.status !== 'archived'}
                  onClick={() => void transition('restore_draft')}>Restore draft</Button>
              </div></div>
              {dirty ? <p className="site-cms-unsaved" role="status">Unsaved edits. {saveBlocked ? 'Autosave is paused.' : 'Autosave will run after a short pause.'}</p> : null}
              {!online ? <p role="status" className="site-cms-save-note">Offline — nothing is being sent. Keep this tab open until the connection returns.</p> : null}
              {saveNote ? <p role="status" className="site-cms-save-note">{saveNote}</p> : null}
              {saveBlocked && !saveConflict && dirty ? <Button variant="secondary" disabled={busy}
                onClick={() => { setSaveBlocked(false); void save(); }}>Retry save</Button> : null}
              {saveConflict ? <div className="site-cms-conflict" role="alert">
                <strong>Version conflict — no changes have been overwritten.</strong>
                <p>Keep this tab open. Export your unsaved draft before replacing it with the current server version.</p>
                {serverConflict && draft ? <div className="site-cms-compare">
                  <p>Local draft vs. latest server revision {serverConflict.draftVersion}</p>
                  <table>
                    <caption>Unresolved content differences; no automatic merge is performed.</caption>
                    <thead><tr><th scope="col">Field</th><th scope="col">Your draft</th><th scope="col">Server</th></tr></thead>
                    <tbody>{compareDraftDocuments(draft, serverConflict.document).slice(0, 25).map((item) =>
                      <tr key={item.field}><th scope="row">{item.field}</th><td>{item.local}</td><td>{item.server}</td></tr>)}</tbody>
                  </table>
                  {compareDraftDocuments(draft, serverConflict.document).length === 0
                    ? <p>The content matches, but the saved revision differs. Reload to acknowledge it.</p>
                    : null}
                </div> : <p>Current server comparison is unavailable. Export your local draft first.</p>}
                <div className="site-cms-actions">
                  <Button icon={Copy} variant="secondary" onClick={exportLocalDraft}>Export unsaved draft</Button>
                  <Button icon={RefreshCw} variant="secondary" disabled={busy}
                    onClick={() => { void reloadServerPage(); }}>Reload server version</Button>
                </div>
                <form className="site-cms-recovery-form" onSubmit={(event) => {
                  event.preventDefault(); void recoverAsSeparateDraft();
                }}>
                  <strong>Save local changes as a separate draft</strong>
                  <label>Recovery page title<input required maxLength={180} value={recoverTitle}
                    onChange={(event) => setRecoverTitle(event.target.value)} /></label>
                  <label>Recovery URL slug<input required pattern="[a-z0-9]+(-[a-z0-9]+)*"
                    maxLength={160} value={recoverSlug}
                    onChange={(event) => setRecoverSlug(event.target.value)} /></label>
                  <Button type="submit" variant="secondary" disabled={busy || !recoverTitle.trim() || !recoverSlug.trim()}>
                    Save as new draft
                  </Button>
                </form>
              </div> : null}
              {selected.publishedVersion ? <a className="site-cms-public-link" target="_blank" rel="noreferrer" href={publicUrl}>Open published page <ExternalLink size={15}/></a> : null}
            </Card>
            <Card>
              <h3>Export content</h3>
              <p>Download this private draft in the validated site-page JSON format.</p>
              <Button icon={Copy} variant="secondary" onClick={() => { void exportPage(); }}
                disabled={busy || dirty}>Export current draft</Button>
            </Card>
            <Card>
              <h3>Duplicate this page</h3>
              <p>Create an independent private draft. Block IDs are regenerated and search indexing must be approved again.</p>
              <form className="site-cms-copy" onSubmit={(event) => { event.preventDefault(); void duplicatePage(); }}>
                <label>New page title
                  <input required value={copyTitle} maxLength={180}
                    onChange={(event) => setCopyTitle(event.target.value)} />
                </label>
                <label>New URL slug
                  <input required value={copySlug} pattern="[a-z0-9]+(-[a-z0-9]+)*" maxLength={160}
                    onChange={(event) => setCopySlug(event.target.value)} />
                </label>
                <Button variant="secondary" icon={Copy} type="submit"
                  disabled={busy || dirty || !copyTitle.trim() || !copySlug.trim()}>
                  Duplicate as draft
                </Button>
              </form>
            </Card>
            <div className="site-cms-editor-grid"><Card>
              <h3>{draft.content_type === 'article' ? 'Blog article editor' : 'Visual page builder'}</h3>
              <label>Page title<input value={draft.title} maxLength={180} onChange={(event) => setDraft({ ...draft, title: event.target.value })}/></label>
              {draft.content_type === 'article' && draft.blog ? <fieldset className="site-cms-seo">
                <legend>Blog article details</legend>
                <label>Author
                  <input required maxLength={120} value={draft.blog.author}
                    onChange={(event) => setDraft({ ...draft, blog: { ...draft.blog!, author: event.target.value } })}/>
                </label>
                <label>Category
                  <input required maxLength={80} value={draft.blog.category}
                    onChange={(event) => setDraft({ ...draft, blog: { ...draft.blog!, category: event.target.value } })}/>
                </label>
                <label>Article summary
                  <textarea required rows={3} maxLength={240} value={draft.blog.summary}
                    onChange={(event) => setDraft({ ...draft, blog: { ...draft.blog!, summary: event.target.value } })}/>
                </label>
                <label>Reviewer (optional)
                  <input maxLength={120} value={draft.blog.reviewer ?? ''}
                    onChange={(event) => setDraft({ ...draft, blog: { ...draft.blog!, reviewer: event.target.value || null } })}/>
                </label>
                <label>Language and region
                  <select value={draft.blog.locale}
                    onChange={(event) => setDraft({ ...draft, blog: { ...draft.blog!, locale: event.target.value } })}>
                    <option value="en">English</option>
                    <option value="hi">Hindi</option>
                    <option value="en-IN">English (India)</option>
                  </select>
                </label>
              </fieldset> : null}
              <fieldset className="site-cms-seo">
                <legend>Search appearance</legend>
                <label>Meta description (up to 160 characters)
                  <textarea rows={3} maxLength={160} value={seo.description}
                    onChange={(event) => setDraft({ ...draft, seo: { ...seo, description: event.target.value } })}/>
                </label>
                <label>Approved canonical HTTPS URL
                  <input type="url" placeholder="https://yourdomain.example/page"
                    value={seo.canonical_url ?? ''} maxLength={2048}
                    onChange={(event) => {
                      const value = event.target.value.trim();
                      setDraft({ ...draft, seo: { ...seo, canonical_url: value || null, indexable: value ? seo.indexable : false } });
                    }}/>
                </label>
                <label className="site-cms-indexable">
                  <input type="checkbox" checked={seo.indexable} disabled={!seo.canonical_url}
                    onChange={(event) => setDraft({ ...draft, seo: { ...seo, indexable: event.target.checked } })}/>
                  Allow search engines to index this page
                </label>
                <small>Unapproved pages remain noindex. Add the verified canonical URL before enabling indexing.</small>
              </fieldset>
              <div className="site-cms-sections" role="group" aria-label="Page sections">
                {draft.nodes.map((section, index) => <div className="site-cms-section-row" key={section.id}
                  draggable onDragStart={() => setDraggedItem({ id: section.id, type: 'section' })}
                  onDragEnd={() => setDraggedItem(null)}
                  onDragOver={(event) => { if (draggedItem?.type === 'section') event.preventDefault(); }}
                  onDrop={(event) => { event.preventDefault(); dropSection(section.id); }}>
                  <button type="button" className={currentSection?.id === section.id ? 'is-selected' : ''}
                    aria-pressed={currentSection?.id === section.id}
                    onClick={() => setSectionId(section.id)}><GripVertical size={15} aria-hidden="true" /> Section {index + 1} · {(section.children ?? []).length} blocks</button>
                  <div className="site-cms-row-actions">
                    <button type="button" aria-label={'Move section ' + (index + 1) + ' up'} disabled={index === 0}
                      onClick={() => moveSection(section.id, -1)}><ArrowUp size={15}/></button>
                    <button type="button" aria-label={'Move section ' + (index + 1) + ' down'} disabled={index === draft.nodes.length - 1}
                      onClick={() => moveSection(section.id, 1)}><ArrowDown size={15}/></button>
                    <button type="button" aria-label={'Duplicate section ' + (index + 1)}
                      onClick={() => duplicateSection(section.id)}><Copy size={15}/></button>
                    <button type="button" aria-label={'Remove section ' + (index + 1)} disabled={draft.nodes.length <= 1}
                      onClick={() => deleteSection(section.id)}><Trash2 size={15}/></button>
                  </div>
                </div>)}
              </div>
              <Button variant="secondary" size="sm" icon={Plus} onClick={addSection}>Add section</Button>
              {currentSection && <WebsiteNodeStyleEditor node={currentSection}
                onChange={(appearance) => edit(currentSection.id, (item) => ({ ...item, appearance }))}/>}
              <h4>Add content block</h4><div className="site-cms-add" role="group" aria-label="Add block">
                {(['heading', 'paragraph', 'image', 'button'] as const).map((kind) =>
                  <Button key={kind} size="sm" variant="secondary" icon={Plus} onClick={() => addBlock(kind)}>{kind}</Button>)}
              </div>
              <div className="site-cms-form-embed">
                <label>Published form to embed
                  <select value={formEmbedSlug} onChange={(event) => setFormEmbedSlug(event.target.value)}>
                    <option value="">Select a published form…</option>
                    {embeddableForms.map((form) => <option key={form.id} value={form.slug}>
                      {form.document.title} (/{form.slug})
                    </option>)}
                  </select>
                </label>
                <Button size="sm" variant="secondary" icon={Plus}
                  disabled={!currentSection || !formEmbedSlug}
                  onClick={addFormBlock}>Embed published form</Button>
                <Button size="sm" variant="secondary" icon={RefreshCw}
                  onClick={() => { void refreshEmbeddableForms(); }}>Refresh forms</Button>
              </div>
              {(currentSection?.children ?? []).map((node, index, list) => <div key={node.id} className="site-cms-block"
                draggable onDragStart={() => setDraggedItem({ id: node.id, type: 'block' })}
                onDragEnd={() => setDraggedItem(null)}
                onDragOver={(event) => { if (draggedItem?.type === 'block') event.preventDefault(); }}
                onDrop={(event) => { event.preventDefault(); dropBlock(node.id); }}>
                <div className="site-cms-block-head"><strong><GripVertical size={15} aria-hidden="true"/> {node.kind} {index + 1}</strong><div>
                  <button aria-label={'Move ' + node.kind + ' up'} type="button" disabled={index === 0}
                    onClick={() => edit(currentSection!.id, (section) => ({ ...section, children: move(section.children ?? [], node.id, -1) }))}><ArrowUp size={15}/></button>
                  <button aria-label={'Move ' + node.kind + ' down'} type="button" disabled={index === list.length - 1}
                    onClick={() => edit(currentSection!.id, (section) => ({ ...section, children: move(section.children ?? [], node.id, 1) }))}><ArrowDown size={15}/></button>
                  <button aria-label={'Duplicate ' + node.kind} type="button"
                    onClick={() => duplicateBlock(node.id)}><Copy size={15}/></button>
                  <button aria-label={'Remove ' + node.kind} type="button"
                    onClick={() => deleteBlock(node.id)}><Trash2 size={15}/></button>
                </div></div>
                {draft.nodes.length > 1 ? <label>Move block to section
                  <select value="" onChange={(event) => { if (event.target.value) moveBlock(node.id, event.target.value); }}>
                    <option value="">Choose destination…</option>
                    {draft.nodes.filter((section) => section.id !== currentSection?.id).map((section) =>
                      <option key={section.id} value={section.id}>Section {draft.nodes.indexOf(section) + 1}</option>)}
                  </select>
                </label> : null}
                <label>{node.kind === 'image' ? 'Alternative text' : node.kind === 'button' ? 'Button label' : node.kind === 'form' ? 'Accessible form title' : 'Content'}
                  <textarea value={node.text ?? ''} rows={node.kind === 'paragraph' ? 3 : 2} maxLength={10000}
                    onChange={(event) => edit(node.id, (item) => ({ ...item, text: event.target.value }))}/></label>
                {(node.kind === 'image' || node.kind === 'button') && <label>URL
                  <input value={node.url ?? ''} onChange={(event) => edit(node.id, (item) => ({ ...item, url: event.target.value }))}/></label>}
                <WebsiteNodeStyleEditor node={node}
                  onChange={(appearance) => edit(node.id, (item) => ({ ...item, appearance }))}/>
              </div>)}
            </Card><Card><h3>Draft preview</h3><p>Private preview. Tracking scripts are not loaded.</p>
              <div className="site-cms-preview">{draft.nodes.map(render)}</div>
            </Card></div>
            <Card><h3>Revision history</h3><p>Restore any prior revision as a new private draft. No version is deleted.</p>
              <div className="site-cms-history">
                {revisions.map((revision) => <div key={revision.version}>
                  <span><strong>Version {revision.version}</strong> · {revision.title} {revision.isPublished ? '(published)' : ''}</span>
                  <Button size="sm" variant="secondary" disabled={busy || dirty || revision.version === selected.draftVersion}
                    onClick={() => void restore(revision.version)}>Restore</Button>
                </div>)}
              </div>
            </Card>
          </>}
        </div>
      </div>}
  </div>;
}
