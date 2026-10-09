import { ArrowLeft, BookOpen, CalendarDays, Info, ShieldCheck } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';

interface Props { open: boolean; onClose: () => void; title: string; description?: string; children: ReactNode; footer?: ReactNode; closeDisabled?: boolean; name: string; code: string; courseName?: string; startsOn: string; endsOn: string; status: string; }
/** Inline page, not a modal: preserves the exported two-column cohort editor. */
export function BatchEditorFrame({ open, onClose, title, description, children, footer, closeDisabled, name, code, courseName, startsOn, endsOn, status }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (open) { heading.current?.focus(); } }, [open]);
  if (!open) return null;
  return <section className="ed-editor" role="region" aria-label={title}>
    <button className="ed-back" type="button" onClick={onClose} disabled={closeDisabled}><ArrowLeft />Back to Batches</button>
    <h2 ref={heading} tabIndex={-1}>{title}</h2><p>{description}</p>
    <div className="ed-editor__columns"><div className="ed-editor__main"><div className="ed-editor__form">{children}</div><div className="ed-editor__footer">{footer}</div></div>
    <aside aria-label="Cohort Live Preview"><section className="ed-detail-panel"><div className="ed-section-heading"><h3>Cohort Live Preview</h3><span className="ed-chip">Preview</span></div><div className="ed-preview-record"><small>{code || 'BATCH CODE'}</small><h4>{name || 'Your new cohort'}</h4><p><BookOpen />{courseName || 'Select an academic course'}</p><p><CalendarDays />{startsOn || 'Open start'} → {endsOn || 'Open end'}</p><span className="ed-chip ed-chip--green">{status}</span></div><p className="ed-muted"><Info />Preview updates as you complete the form.</p></section><section className="ed-detail-panel"><h3><ShieldCheck />Access &amp; Enrollment Rules</h3><p>Course selection is fixed after creation to protect enrollment references.</p><p>Start and end dates are inclusive. Archived courses cannot receive active batches.</p><p>Faculty, class-meeting times, seat capacity, and publication schedules are not stored by the existing batch service; they are not silently applied here.</p></section></aside></div>
  </section>;
}
