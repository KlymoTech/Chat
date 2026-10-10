import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { ArrowDown, ArrowUp, Check, Copy, ExternalLink, FilePlus2, GripVertical, Plus, RefreshCw, Save, Send, ShieldCheck, Trash2 } from 'lucide-react';
import { useWorkspace } from '@/components/providers';
import { Button, Card, Badge } from '@/components/ui';
import { apiConfig, request } from '@/lib/api';
import { duplicateSibling, moveBlockBetweenSections, removeChild, reorderNodes, type BuilderNode } from './websiteBuilderOperations';
import './WebsiteCMSPage.css';

type Kind = 'section' | 'heading' | 'paragraph' | 'image' | 'button';
type Action = 'submit' | 'approve' | 'publish';
type Node = BuilderNode;
interface PageSEO { description: string; canonical_url: string | null; indexable: boolean }
interface BlogMetadata { author: string; category: string; summary: string; reviewer: string | null; locale: string }
interface PageDocument {
  schema_version: 1; title: string; slug: string; nodes: Node[]; seo?: PageSEO;
  content_type?: 'page' | 'article'; blog?: BlogMetadata | null;
}
interface WebsiteMetrics { days: number; pageViews: number; ctaClicks: number; pages: Array<{ slug: string; pageViews: number }> }
interface Revision { version: number; title: string; createdAt: string; isPublished: boolean }
interface CMSPage { id: string; slug: string; title: string; status: string; draftVersion: number; publishedVersion: number | null; document: PageDocument }
const id = () => crypto.randomUUID();
const defaultSEO: PageSEO = { description: '', canonical_url: null, indexable: false };
const newDocument = (title: string, slug: string, asArticle = false): PageDocument => ({
  schema_version: 1, title, slug, seo: { ...defaultSEO },
  content_type: asArticle ? 'article' : 'page',
  blog: asArticle ? { author: 'Editorial team', category: 'General', summary: 'Update this article summary before publishing.', reviewer: null, locale: 'en' } : null,
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
  if (node.kind === 'heading') return <h2 key={node.id}>{node.text}</h2>;
  if (node.kind === 'paragraph') return <p key={node.id}>{node.text}</p>;
  if (node.kind === 'image') return <img key={node.id} src={node.url ?? ''} alt={node.text ?? ''} loading="lazy"/>;
  if (node.kind === 'button') return <span className="button button--primary" key={node.id}>{node.text}</span>;
  return <section key={node.id} className="site-cms-preview-section">{(node.children ?? []).map(render)}</section>;
}
function message(reason: unknown): string {
  if (reason && typeof reason === 'object' && 'detail' in reason) {
    const detail = (reason as { detail?: unknown }).detail;
    if (detail && typeof detail === 'object' && 'detail' in detail) return String((detail as { detail: unknown }).detail);
  }
  return reason instanceof Error ? reason.message : 'The request could not be completed.';
}

export function WebsiteCMSPage() {
  const { activeWorkspace } = useWorkspace();
  const workspaceId = activeWorkspace?.id;
  const [pages, setPages] = useState<CMSPage[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [metrics, setMetrics] = useState<WebsiteMetrics | null>(null);
  const [selected, setSelected] = useState<CMSPage | null>(null);
  const [draft, setDraft] = useState<PageDocument | null>(null);
  const [sectionId, setSectionId] = useState<string | null>(null);
  const [draggedItem, setDraggedItem] = useState<{ id: string; type: 'section' | 'block' } | null>(null);
  const [name, setName] = useState('New page');
  const [slug, setSlug] = useState('new-page');
  const [newContentType, setNewContentType] = useState<'page' | 'article'>('page');
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
      setMetrics(await request<WebsiteMetrics>('/site-analytics/summary?days=30').catch(() => null));
      setSelected((current) => current ? saved.find((page) => page.id === current.id) ?? null : null);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }, [workspaceId]);
  useEffect(() => { setPages([]); setSelected(null); setDraft(null); void load(); }, [load]);
  const refreshRevisions = async (pageId: string) => {
    try { setRevisions(await request<Revision[]>('/site-cms/pages/' + pageId + '/revisions')); }
    catch (reason) { setError(message(reason)); }
  };
  const open = (page: CMSPage, force = false) => {
    if (!force && dirty && !window.confirm('Discard unsaved content changes?')) return;
    setSelected(page); setDraft(page.document); setSectionId(page.document.nodes[0]?.id ?? null); setError('');
    setCopyTitle('Copy of ' + page.title);
    setCopySlug((page.slug + '-copy').slice(0, 160));
    void refreshRevisions(page.id);
  };
  const create = async () => {
    setBusy(true); setError('');
    try {
      const page = await request<CMSPage>('/site-cms/pages', { method: 'POST', body: JSON.stringify(newDocument(name.trim(), slug.trim(), newContentType === 'article')) });
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
      const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' });
      const downloadUrl = URL.createObjectURL(blob);
      try {
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = selected.slug + '.site-page.json';
        document.body.appendChild(link);
        link.click();
        link.remove();
      } finally {
        URL.revokeObjectURL(downloadUrl);
      }
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const importPage = async () => {
    if (!importContent || busy || dirty) return;
    setBusy(true); setError('');
    try {
      const imported: unknown = JSON.parse(importContent);
      if (!imported || typeof imported !== 'object' || Array.isArray(imported)) {
        throw new Error('Choose a valid site page JSON manifest.');
      }
      const manifest = imported as Record<string, unknown>;
      const result = await request<CMSPage>('/site-cms/pages/import', {
        method: 'POST',
        body: JSON.stringify({
          ...manifest, new_slug: importSlug.trim(), new_title: importTitle.trim(),
        }),
      });
      setPages((pages) => [result, ...pages]);
      setImportContent('');
      open(result, true);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
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

  const dirty = !!selected && !!draft && JSON.stringify(draft) !== JSON.stringify(selected.document);
  const replace = (page: CMSPage) => {
    setSelected(page); setDraft(page.document); setPages((items) => items.map((item) => item.id === page.id ? page : item));
    void refreshRevisions(page.id);
  };
  const save = async () => {
    if (!selected || !draft) return;
    setBusy(true); setError('');
    try {
      replace(await request<CMSPage>('/site-cms/pages/' + selected.id, {
        method: 'PUT', body: JSON.stringify({ expected_version: selected.draftVersion, document: draft }),
      }));
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const transition = async (action: Action) => {
    if (!selected || dirty) return;
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
      <Button variant="secondary" icon={RefreshCw} disabled={busy} onClick={() => void load()}>Refresh</Button></div>
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
          <Button type="submit" icon={FilePlus2} disabled={busy || !name.trim()}>Create draft</Button>
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
          <Card><h3>Website engagement</h3><p>First-party, consent-eligible events from published pages (last 30 days).</p>
            <div className="site-cms-metrics">
              <div><strong>{metrics?.pageViews ?? '—'}</strong><span>Page views</span></div>
              <div><strong>{metrics?.ctaClicks ?? '—'}</strong><span>CTA clicks</span></div>
              <div><strong>{metrics?.pages.length ?? '—'}</strong><span>Viewed pages</span></div>
            </div>
            {metrics && metrics.pages.length > 0 ? <p>Top page: /{metrics.pages[0]?.slug} · {metrics.pages[0]?.pageViews} views</p> : null}
            <a className="site-cms-public-link" href={apiConfig.baseUrl + '/site-blog/' + activeWorkspace.id}
              target="_blank" rel="noopener noreferrer">View published blog <ExternalLink size={15} aria-hidden="true" /></a>
            <a className="site-cms-public-link" href={apiConfig.baseUrl + '/site-discovery/sitemap/' + activeWorkspace.id + '.xml'}
              target="_blank" rel="noopener noreferrer">View published XML sitemap <ExternalLink size={15} aria-hidden="true" /></a>
          </Card>
          {!draft || !selected ? <Card><h3>Select a page</h3><p>Choose an existing page or create a draft.</p></Card> : <>
            <Card><div className="site-cms-toolbar"><div><strong>{selected.title}</strong> <Badge tone={selected.status === 'published' ? 'success' : 'warning'}>{selected.status}</Badge>
              <small>{draft.content_type === 'article' ? 'Article' : 'Page'} · Draft revision {selected.draftVersion} · Published {selected.publishedVersion ?? 'never'}</small></div>
              <div className="site-cms-actions">
                <Button icon={Save} disabled={busy || !dirty} onClick={() => void save()}>Save draft</Button>
                <Button variant="secondary" icon={Send} disabled={busy || dirty || selected.status !== 'draft'} onClick={() => void transition('submit')}>Submit review</Button>
                <Button variant="secondary" icon={Check} disabled={busy || dirty || selected.status !== 'in_review'} onClick={() => void transition('approve')}>Approve</Button>
                <Button variant="secondary" icon={ShieldCheck} disabled={busy || dirty || selected.status !== 'approved'} onClick={() => void transition('publish')}>Publish</Button>
              </div></div>
              {dirty ? <p className="site-cms-unsaved">Unsaved changes. Save before publishing.</p> : null}
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
              <h4>Add content block</h4><div className="site-cms-add" role="group" aria-label="Add block">
                {(['heading', 'paragraph', 'image', 'button'] as const).map((kind) =>
                  <Button key={kind} size="sm" variant="secondary" icon={Plus} onClick={() => addBlock(kind)}>{kind}</Button>)}
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
                <label>{node.kind === 'image' ? 'Alternative text' : node.kind === 'button' ? 'Button label' : 'Content'}
                  <textarea value={node.text ?? ''} rows={node.kind === 'paragraph' ? 3 : 2} maxLength={10000}
                    onChange={(event) => edit(node.id, (item) => ({ ...item, text: event.target.value }))}/></label>
                {(node.kind === 'image' || node.kind === 'button') && <label>URL
                  <input value={node.url ?? ''} onChange={(event) => edit(node.id, (item) => ({ ...item, url: event.target.value }))}/></label>}
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
