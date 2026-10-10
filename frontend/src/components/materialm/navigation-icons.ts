import {
  BarChart3, BookOpen, ClipboardList, Code2, ContactRound, FileSpreadsheet,
  createLucideIcon, GraduationCap, History, MessageSquare, LayoutDashboard, Layers, PlugZap, Route, ShieldCheck, Sparkles, UsersRound,
} from 'lucide-react';
import type { NavigationItem } from '@/lib/materialm-navigation';
import type { LucideIcon } from 'lucide-react';

const CrmWorkflowIcon = createLucideIcon('crm-workflow', [
  ['path', { d: 'm8 8.5 4-2.5 4 2.5v5L12 16l-4-2.5z', key: 'cube' }],
  ['path', { d: 'm8 8.5 4 2.5 4-2.5M12 11v5', key: 'cube-lines' }],
  ['circle', { cx: '4', cy: '5', r: '1.8', key: 'node-top-left' }],
  ['circle', { cx: '20', cy: '6.5', r: '1.8', key: 'node-top-right' }],
  ['circle', { cx: '20', cy: '16.5', r: '1.8', key: 'node-bottom-right' }],
  ['circle', { cx: '4', cy: '19', r: '1.8', key: 'node-bottom-left' }],
  ['path', { d: 'm5.6 5.8 2.6 1.7m7.7.6 2.4-1m0 7.7-2.4-1.3m-7.8 1.1-2.4 2.8', key: 'connections' }],
]);

export const navigationIcons: Record<NavigationItem['icon'], LucideIcon> = {
  overview: LayoutDashboard, agents: Sparkles, inbox: MessageSquare, leads: ContactRound,
  integrations: PlugZap, workflows: Route, 'crm-workflow': CrmWorkflowIcon, education: GraduationCap, analytics: BarChart3, audit: ShieldCheck,
  deploy: Code2, students: UsersRound, courses: BookOpen, batches: Layers,
  enrollments: ClipboardList, imports: FileSpreadsheet, access: ShieldCheck, activity: History,
};
