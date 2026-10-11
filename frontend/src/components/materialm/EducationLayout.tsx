import { Link, Outlet, useLocation } from 'react-router-dom';
import { ChevronRight, GraduationCap } from 'lucide-react';
import { useAuth, useWorkspace } from '@/components/providers';
import { educationNavigation, educationPage } from '@/lib/materialm-navigation';
import '@/features/education/education-design.css';
import { canUseDashboardCapability } from '@/features/dashboard/dashboardPermissions';
import { navigationIcons } from './navigation-icons';

export function EducationLayout() {
  const { activeWorkspace, loading } = useWorkspace();
  const { session } = useAuth();
  const { pathname } = useLocation();
  const scope = { role: session?.user.role, permissions: activeWorkspace?.permissions };
  const knowledgePage = pathname.startsWith('/education/knowledge');
  const selected = knowledgePage ? { to: '/education/knowledge', label: 'Course knowledge', permission: 'knowledge.view' } : educationPage(pathname);
  if (loading && !activeWorkspace) return <div className="mm-empty" role="status">Loading education workspace…</div>;
  if (!activeWorkspace) return <div className="mm-empty">Select an authorized workspace to open Education.</div>;
  if (!canUseDashboardCapability(scope, 'education.view') || (selected && !canUseDashboardCapability(scope, selected.permission))) {
    return <section className="mm-empty" aria-label="Education access unavailable"><h2>Education access unavailable</h2><p>Your workspace role does not include access to this Education section.</p></section>;
  }
  return <div className="mm-education" data-business-domain="education">
    <div className="mm-education__bar">
      <nav aria-label="Education breadcrumb" className="mm-breadcrumb">
        <Link to="/education"><GraduationCap aria-hidden="true" />Education</Link>
        {selected && selected.to !== '/education' ? <><ChevronRight aria-hidden="true" /><span>{selected.label}</span></> : null}
      </nav>
      <span className="mm-domain-label">Learning workspace</span>
    </div>
    <nav className="mm-education__nav" aria-label="Education navigation">
      {educationNavigation.filter((item) => canUseDashboardCapability(scope, item.permission)).map((item) => {
        const Icon = navigationIcons[item.icon];
        const active = selected?.to === item.to;
        return <Link key={item.to} to={item.to} aria-current={active ? 'page' : undefined} className={active ? 'is-active' : undefined}>
          <Icon aria-hidden="true" /><span>{item.label}</span>
        </Link>;
      })}

    </nav>
    <div className="mm-education__content"><Outlet key={activeWorkspace.id} /></div>
  </div>;
}
