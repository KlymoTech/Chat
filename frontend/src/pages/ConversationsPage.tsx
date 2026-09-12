import { Archive, BadgeDollarSign, Bot, CheckCircle2, ChevronDown, CircleAlert, Clock3, ExternalLink, Filter, Inbox, Mail, MessageCircle, MoreHorizontal, Search, Send, Smile, Sparkles, UserRound } from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useToast, useWorkspace } from '@/components/providers';
import { Badge, Button, EmptyState, PageLoader } from '@/components/ui';
import { api } from '@/lib/api';
import { conversationApi } from '@/lib/conversation-api';
import { educationApi, type EducationBatch, type EducationCourse } from '@/lib/education-api';
import { educationEnrollmentApi, type EducationEnrollment } from '@/lib/education-enrollment-api';
import { educationSalesSettingsApi } from '@/lib/education-sales-settings-api';
import { educationStudentApi, type EducationStudent } from '@/lib/education-student-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import type { Conversation, ConversationState } from '@/types';
import './ConversationsPage.css';

type ChannelFilter = 'all' | 'widget' | 'api' | 'slack' | 'whatsapp';

export function ConversationsPage() {
  const [params, setParams] = useSearchParams();
  const { pushToast } = useToast();
  const { activeWorkspace } = useWorkspace();
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [filter, setFilter] = useState<'all' | ConversationState>('all');
  const [agentId, setAgentId] = useState('all');
  const [courseId, setCourseId] = useState('all');
  const [batchId, setBatchId] = useState('all');
  const [studentId, setStudentId] = useState('all');
  const [channel, setChannel] = useState<ChannelFilter>('all');
  const [reply, setReply] = useState('');
  const [sending, setSending] = useState(false);
  const [routingUpsell, setRoutingUpsell] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const agents = useApi(() => api.agents.list(), [activeWorkspace?.id]);
  const educationSales = useApi(
    () => educationSalesSettingsApi.get().catch(() => ({ createUpsellLeads: false })),
    [activeWorkspace?.id],
  );
  const filterAgent = agentId === 'all' ? null : agents.data?.find((item) => item.id === agentId) ?? null;
  const isEducationAgent = filterAgent?.purpose === 'education';

  const courses = useApi(
    () => isEducationAgent
      ? educationApi.courses.list({ status: 'active' })
      : Promise.resolve([] as EducationCourse[]),
    [activeWorkspace?.id, isEducationAgent],
  );
  const batches = useApi(
    () => isEducationAgent && courseId !== 'all'
      ? educationApi.batches.list({ courseId, status: 'active' })
      : Promise.resolve([] as EducationBatch[]),
    [activeWorkspace?.id, isEducationAgent, courseId],
  );
  const enrollments = useApi(
    () => isEducationAgent && courseId !== 'all' && batchId !== 'all'
      ? educationEnrollmentApi.list({ agentId, courseId, batchId })
      : Promise.resolve([] as EducationEnrollment[]),
    [activeWorkspace?.id, isEducationAgent, agentId, courseId, batchId],
  );
  const students = useApi(
    () => isEducationAgent && batchId !== 'all'
      ? educationStudentApi.list({ status: 'active' })
      : Promise.resolve([] as EducationStudent[]),
    [activeWorkspace?.id, isEducationAgent, batchId],
  );
  const eligibleStudentIds = useMemo(
    () => new Set((enrollments.data ?? []).map((item) => item.studentId)),
    [enrollments.data],
  );
  const eligibleStudents = useMemo(
    () => (students.data ?? []).filter((student) => eligibleStudentIds.has(student.id)),
    [students.data, eligibleStudentIds],
  );

  useEffect(() => {
    if (!isEducationAgent) {
      setCourseId('all');
      setBatchId('all');
      setStudentId('all');
    }
  }, [isEducationAgent]);

  useEffect(() => {
    if (
      studentId !== 'all'
      && !eligibleStudents.some((student) => student.id === studentId)
      && !students.loading
    ) {
      setStudentId('all');
    }
  }, [eligibleStudents, studentId, students.loading]);

  const result = useApi(
    () => conversationApi.list({
      agentId: agentId === 'all' ? undefined : agentId,
      educationScope: isEducationAgent,
      courseId: isEducationAgent && courseId !== 'all' ? courseId : undefined,
      batchId: isEducationAgent && batchId !== 'all' ? batchId : undefined,
      studentId: isEducationAgent && studentId !== 'all' ? studentId : undefined,
      channel: channel === 'all' ? undefined : channel,
      state: filter === 'all' ? undefined : filter,
      search: debouncedSearch || undefined,
      page: 1,
      pageSize: 50,
    }),
    [activeWorkspace?.id, agentId, courseId, batchId, studentId, isEducationAgent, channel, filter, debouncedSearch],
  );

  const conversations = result.data?.items ?? [];
  const selectedId = params.get('selected') ?? conversations[0]?.id;
  const selected = conversations.find((item) => item.id === selectedId) ?? null;
  const selectedAgent = selected ? agents.data?.find((item) => item.id === selected.agentId) : null;
  const canRouteEducationUpsell = selectedAgent?.purpose === 'education'
    && educationSales.data?.createUpsellLeads === true;

  useEffect(() => {
    const selectedParam = params.get('selected');
    if ((!selectedParam || !conversations.some((item) => item.id === selectedParam)) && conversations[0]) {
      setParams({ selected: conversations[0].id }, { replace: true });
    }
  }, [conversations, params, setParams]);

  const changeAgent = (nextAgentId: string) => {
    setAgentId(nextAgentId);
    setCourseId('all');
    setBatchId('all');
    setStudentId('all');
  };

  const changeCourse = (nextCourseId: string) => {
    setCourseId(nextCourseId);
    setBatchId('all');
    setStudentId('all');
  };

  const changeBatch = (nextBatchId: string) => {
    setBatchId(nextBatchId);
    setStudentId('all');
  };

  const setState = async (state: ConversationState) => {
    if (!selected) return;
    if (state === 'resolved') await conversationApi.resolve(selected.id);
    else await api.conversations.updateState(selected.id, state);
    const resolvedMessage = selectedAgent?.purpose === 'lead_generation'
      ? 'Conversation resolved and lead finalized'
      : selectedAgent?.purpose === 'education'
        ? 'Education conversation resolved and student history updated'
        : 'Conversation resolved';
    pushToast(state === 'resolved' ? resolvedMessage : `Conversation marked ${state}`);
    result.reload();
  };

  const resolveEducationSalesIntent = async () => {
    if (!selected || routingUpsell) return;
    setRoutingUpsell(true);
    try {
      const routed = await conversationApi.resolveEducationSalesIntent(selected.id);
      pushToast(routed.leadCreated
        ? 'Education conversation resolved and sales Lead created'
        : 'Education sales Lead is already linked to this conversation');
      await result.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Education sales Lead could not be created', 'error');
    } finally {
      setRoutingUpsell(false);
    }
  };

  const submitReply = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !reply.trim() || sending) return;
    setSending(true);
    try {
      await api.conversations.reply(selected.id, reply.trim());
      setReply('');
      await result.reload();
      pushToast('Reply sent');
    } catch {
      pushToast('Reply could not be sent', 'error');
    } finally {
      setSending(false);
    }
  };

  if (result.loading && !result.data) return <PageLoader />;
  return <div className="inbox-page">
    <section className={`conversation-list-panel ${selected ? 'has-selection' : ''}`}>
      <div className="inbox-title"><div><h2>Conversations</h2><Badge tone="brand">{result.data?.total ?? 0} results</Badge></div><button className="icon-button" aria-label="Conversation actions"><MoreHorizontal /></button></div>
      <div className="inbox-tools">
        <div className="search-box"><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search conversations" /></div>
        <div className="filter-select"><Filter /><select value={agentId} onChange={(event) => changeAgent(event.target.value)} aria-label="Filter by agent"><option value="all">All agents</option>{agents.data?.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select><ChevronDown /></div>
        <div className="filter-select"><Filter /><select value={channel} onChange={(event) => setChannel(event.target.value as ChannelFilter)} aria-label="Filter by channel"><option value="all">All channels</option><option value="widget">Website</option><option value="whatsapp">WhatsApp</option><option value="slack">Slack</option><option value="api">API</option></select><ChevronDown /></div>
        <div className="filter-select"><Filter /><select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)} aria-label="Filter conversations"><option value="all">All statuses</option><option value="open">Open</option><option value="escalated">Escalated</option><option value="resolved">Resolved</option></select><ChevronDown /></div>
      </div>
      {isEducationAgent ? <div className="education-inbox-filters" aria-label="Education conversation filters">
        <div className="education-inbox-filters__heading"><strong>Education scope</strong><span>Course → Batch → Student</span></div>
        <div className="filter-select"><Filter /><select value={courseId} onChange={(event) => changeCourse(event.target.value)} aria-label="Filter by course"><option value="all">All courses</option>{courses.data?.map((course) => <option key={course.id} value={course.id}>{course.code} · {course.name}</option>)}</select><ChevronDown /></div>
        <div className="filter-select"><Filter /><select value={batchId} disabled={courseId === 'all'} onChange={(event) => changeBatch(event.target.value)} aria-label="Filter by batch"><option value="all">All batches</option>{batches.data?.map((batch) => <option key={batch.id} value={batch.id}>{batch.code} · {batch.name}</option>)}</select><ChevronDown /></div>
        <div className="filter-select"><Filter /><select value={studentId} disabled={batchId === 'all'} onChange={(event) => setStudentId(event.target.value)} aria-label="Filter by student"><option value="all">All students</option>{eligibleStudents.map((student) => <option key={student.id} value={student.id}>{student.studentNumber} · {student.name}</option>)}</select><ChevronDown /></div>
      </div> : null}
      <div className="conversation-items">{conversations.map((conversation) => <button key={conversation.id} className={`conversation-item ${conversation.id === selectedId ? 'is-active' : ''}`} onClick={() => setParams({ selected: conversation.id })}><span className="mini-avatar">{conversation.visitorName.charAt(0)}</span><span className="conversation-item__copy"><span><strong>{conversation.visitorName}</strong><time>{relativeTime(conversation.updatedAt)}</time></span><small>{conversation.preview}</small><span className="conversation-item__tags"><Badge tone={conversation.state === 'escalated' ? 'danger' : conversation.state === 'resolved' ? 'neutral' : 'brand'}>{conversation.state}</Badge><em className={`sentiment sentiment--${conversation.sentiment}`}>{conversation.sentiment}</em></span></span>{conversation.unread ? <i className="unread-count">{conversation.unread}</i> : null}</button>)}</div>
      {!conversations.length ? <EmptyState icon={Inbox} title="No conversations here" description={isEducationAgent ? 'Try another Course, Batch, Student, channel, status, or search.' : 'Try another workspace, agent, channel, status, or search.'} /> : null}
    </section>
    {selected ? <ConversationDetail conversation={selected} agentName={selectedAgent?.name ?? 'Assigned agent'} workspaceName={activeWorkspace?.name ?? 'Workspace'} reply={reply} setReply={setReply} submitReply={submitReply} setState={setState} canRouteEducationUpsell={canRouteEducationUpsell} resolveEducationSalesIntent={resolveEducationSalesIntent} routingUpsell={routingUpsell} onBack={() => setParams({})} sending={sending} /> : <div className="conversation-empty"><MessageCircle /><h3>Select a conversation</h3><p>Read the full context, step in, or mark it resolved.</p></div>}
  </div>;
}

function ConversationDetail({ conversation, agentName, workspaceName, reply, setReply, submitReply, setState, canRouteEducationUpsell, resolveEducationSalesIntent, routingUpsell, onBack, sending }: { conversation: Conversation; agentName: string; workspaceName: string; reply: string; setReply: (value: string) => void; submitReply: (event: FormEvent) => void; setState: (state: ConversationState) => Promise<void>; canRouteEducationUpsell: boolean; resolveEducationSalesIntent: () => Promise<void>; routingUpsell: boolean; onBack: () => void; sending: boolean }) {
  return <section className="conversation-detail">
    <header className="conversation-detail__header"><button className="mobile-back" onClick={onBack}>←</button><span className="mini-avatar mini-avatar--lg">{conversation.visitorName.charAt(0)}</span><div><h3>{conversation.visitorName}</h3><p><i className="status-dot status-dot--success" /> {workspaceName} · {agentName} · {conversation.channel}</p></div><div className="conversation-actions"><Button variant="secondary" size="sm" icon={Archive}>Archive</Button>{canRouteEducationUpsell ? <Button variant="secondary" size="sm" icon={BadgeDollarSign} disabled={routingUpsell} onClick={() => void resolveEducationSalesIntent()}>{routingUpsell ? 'Routing…' : conversation.state === 'resolved' ? 'Create sales lead' : 'Resolve + sales lead'}</Button> : null}{conversation.state !== 'resolved' ? <Button size="sm" icon={CheckCircle2} onClick={() => void setState('resolved')}>Resolve</Button> : <Button variant="secondary" size="sm" onClick={() => void setState('open')}>Reopen</Button>}</div></header>
    <div className="conversation-layout"><div className="conversation-thread"><div className="thread-notice"><Sparkles /> <span><strong>{conversation.state === 'escalated' ? 'Human attention requested' : 'Northstar handled this conversation'}</strong><small>The complete AI context is available below.</small></span></div><div className="message-day"><span>{new Date(conversation.startedAt).toLocaleDateString('en', { month: 'long', day: 'numeric' })}</span></div>
      {conversation.messages.map((message) => <div className={`inbox-message inbox-message--${message.role}`} key={message.id}>{message.role === 'user' ? <span className="message-avatar message-avatar--visitor">{conversation.visitorName.charAt(0)}</span> : <span className="message-avatar"><>{message.role === 'agent' ? <UserRound /> : <Sparkles />}</></span>}<div><span className="message-author">{message.role === 'user' ? conversation.visitorName : message.role === 'agent' ? 'You' : 'Northstar AI'} <time>{new Date(message.createdAt).toLocaleTimeString('en', { hour: 'numeric', minute: '2-digit' })}</time></span><div className="message-bubble">{message.content}</div>{message.citations?.map((citation) => <button className="citation-chip" key={citation.title}><ExternalLink />{citation.title}</button>)}</div></div>)}
    </div><form className="human-composer" onSubmit={(event) => void submitReply(event)}><textarea value={reply} onChange={(event) => setReply(event.target.value)} placeholder="Reply as a teammate…" rows={2} disabled={sending} onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') event.currentTarget.form?.requestSubmit(); }} /><div><span><button type="button" aria-label="Insert emoji"><Smile /></button><small>⌘ Enter to send</small></span><Button size="sm" icon={Send} disabled={!reply.trim() || sending}>{sending ? 'Sending…' : 'Send'}</Button></div></form></div>
    <aside className="visitor-panel"><div className="visitor-profile"><span className="mini-avatar mini-avatar--xl">{conversation.visitorName.charAt(0)}</span><h3>{conversation.visitorName}</h3><Badge tone={conversation.sentiment === 'positive' ? 'success' : conversation.sentiment === 'negative' ? 'danger' : 'neutral'}>{conversation.sentiment} sentiment</Badge></div><dl><div><dt><Mail /> Email</dt><dd>{conversation.visitorEmail ?? 'Not provided'}</dd></div><div><dt><Bot /> Workspace</dt><dd>{workspaceName}</dd></div><div><dt><Bot /> Agent</dt><dd>{agentName}</dd></div><div><dt><MessageCircle /> Channel</dt><dd className="capitalize">{conversation.channel}</dd></div><div><dt><Clock3 /> Started</dt><dd>{relativeTime(conversation.startedAt)}</dd></div><div><dt><CircleAlert /> Status</dt><dd className="capitalize">{conversation.state}</dd></div></dl><div className="conversation-summary"><strong><Sparkles /> AI summary</strong><p>{conversation.preview} The visitor may benefit from a short, direct follow-up.</p></div></aside>
  </section>;
}
