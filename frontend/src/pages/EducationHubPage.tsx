import { ArrowRight, BookOpen, GraduationCap, ShieldCheck, UsersRound } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth, useWorkspace } from '@/components/providers';
import { educationNavigation, visibleNavigation } from '@/lib/materialm-navigation';
import { navigationIcons } from '@/components/materialm/navigation-icons';

/** A navigation hub, not a second education database or a mock dashboard. */
export function EducationHubPage() {
  const { activeWorkspace } = useWorkspace();
  const { session } = useAuth();
  const sections = visibleNavigation(educationNavigation, {
    role: session?.user.role, permissions: activeWorkspace?.permissions,
  }).filter((item) => item.to !== '/education');
  return <div className="mm-education-home">
    <section className="mm-welcome">
      <div><span className="mm-eyebrow">{activeWorkspace?.name ?? 'Active workspace'}</span>
        <h2>Your academy, in one place.</h2>
        <p>Manage students, learning access and academy activity without jumping between unrelated menus.</p>
        <Link className="button button--primary" to="/education/students">Open students <ArrowRight aria-hidden="true" /></Link>
      </div>
      <div className="mm-welcome__art" aria-hidden="true"><GraduationCap /><BookOpen /><UsersRound /></div>
    </section>
    <div className="mm-section-heading"><h3>Education workspace</h3><p>Open the existing tools for the selected workspace.</p></div>
    <div className="mm-module-grid">
      {sections.map((item) => {
        const Icon = navigationIcons[item.icon];
        return <Link to={item.to} key={item.to} className="mm-module-card">
          <span className="mm-module-card__icon"><Icon aria-hidden="true" /></span>
          <h3>{item.label}</h3><p>{item.description}</p>
          <span className="mm-module-card__action">Open {item.label.toLowerCase()} <ArrowRight aria-hidden="true" /></span>
        </Link>;
      })}
    </div>
    <section className="mm-learning-boundary"><ShieldCheck aria-hidden="true" /><div>
      <h3>Education stays in Education</h3>
      <p>This hub manages student records and academy history. Commercial Lead and Support CRM tools remain in their own navigation area.</p>
    </div></section>
  </div>;
}
