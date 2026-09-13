import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AppShell } from '@/components/app-shell';
import { useAuth } from '@/components/providers';
import { AgentBuilderPage } from '@/pages/AgentBuilderPage';
import { AgentsPage } from '@/pages/AgentsPage';
import { AnalyticsPage } from '@/pages/AnalyticsPage';
import { AuditPage } from '@/pages/AuditPage';
import { BatchesPage } from '@/pages/BatchesPage';
import { ConversationsPage } from '@/pages/ConversationsPage';
import { CoursesPage } from '@/pages/CoursesPage';
import { CRMIntegrationsPage } from '@/pages/CRMIntegrationsPage';
import { DeployPage } from '@/pages/DeployPage';
import { EducationAccessRecoveryPage } from '@/pages/EducationAccessRecoveryPage';
import { EducationAccessRequestsPage } from '@/pages/EducationAccessRequestsPage';
import { EducationActivityPage } from '@/pages/EducationActivityPage';
import { EducationEnrollmentsPage } from '@/pages/EducationEnrollmentsPage';
import { EducationStudentDetailPage } from '@/pages/EducationStudentDetailPage';
import { EducationStudentImportPage } from '@/pages/EducationStudentImportPage';
import { ForgotPasswordPage } from '@/pages/ForgotPasswordPage';
import { HelpArticlePage } from '@/pages/HelpArticlePage';
import { HelpAskPage } from '@/pages/HelpAskPage';
import { HelpCategoryPage } from '@/pages/HelpCategoryPage';
import { HelpCenterPage } from '@/pages/HelpCenterPage';
import { HelpSearchPage } from '@/pages/HelpSearchPage';
import { HelpSupportPage } from '@/pages/HelpSupportPage';
import { HelpSupportRequestPage } from '@/pages/HelpSupportRequestPage';
import { LeadsPage } from '@/pages/LeadsPage';
import { LoginPage } from '@/pages/LoginPage';
import { MFAChallengePage } from '@/pages/MFAChallengePage';
import { NotFoundPage } from '@/pages/NotFoundPage';
import { OverviewPage } from '@/pages/OverviewPage';
import { PlatformAdminPage } from '@/pages/PlatformAdminPage';
import { ResetPasswordPage } from '@/pages/ResetPasswordPage';
import { SignupPage } from '@/pages/SignupPage';
import { StudentsPage } from '@/pages/StudentsPage';
import { VerifyEmailPage } from '@/pages/VerifyEmailPage';
import { WhiteLabelPage } from '@/pages/WhiteLabelPage';
import { WorkspaceInvitationPage } from '@/pages/WorkspaceInvitationPage';
import { WorkspacePage } from '@/pages/WorkspacePage';
import { WidgetDemoPage } from '@/pages/WidgetDemoPage';

function ProtectedLayout() {
  const { session } = useAuth(); const location = useLocation();
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (session.user.emailVerified === false) return <Navigate to="/verify-email" replace />;
  return <AppShell />;
}

export function App() {
  return <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route path="/signup" element={<SignupPage />} />
    <Route path="/verify-email" element={<VerifyEmailPage />} />
    <Route path="/forgot-password" element={<ForgotPasswordPage />} />
    <Route path="/reset-password" element={<ResetPasswordPage />} />
    <Route path="/mfa-challenge" element={<MFAChallengePage />} />
    <Route path="/workspace-invitation" element={<WorkspaceInvitationPage />} />
    <Route path="/education-access-recovery" element={<EducationAccessRecoveryPage />} />
    <Route path="/demo/:agentId?" element={<WidgetDemoPage />} />
    <Route path="/widget/:agentId" element={<WidgetDemoPage embedded />} />
    <Route element={<ProtectedLayout />}>
      <Route index element={<OverviewPage />} />
      <Route path="agents" element={<AgentsPage />} />
      <Route path="agents/:agentId/:tab?" element={<AgentBuilderPage />} />
      <Route path="education/courses" element={<CoursesPage />} />
      <Route path="education/batches" element={<BatchesPage />} />
      <Route path="education/students" element={<StudentsPage />} />
      <Route path="education/enrollments" element={<EducationEnrollmentsPage />} />
      <Route path="education/students/import" element={<EducationStudentImportPage />} />
      <Route path="education/students/:studentId" element={<EducationStudentDetailPage />} />
      <Route path="education/access-requests" element={<EducationAccessRequestsPage />} />
      <Route path="education/activity" element={<EducationActivityPage />} />
      <Route path="conversations" element={<ConversationsPage />} />
      <Route path="leads" element={<LeadsPage />} />
      <Route path="analytics" element={<AnalyticsPage />} />
      <Route path="audit" element={<AuditPage />} />
      <Route path="integrations" element={<CRMIntegrationsPage />} />
      <Route path="deploy" element={<DeployPage />} />
      <Route path="workspace" element={<WorkspacePage />} />
      <Route path="workspace/white-label" element={<WhiteLabelPage />} />
      <Route path="platform-admin" element={<PlatformAdminPage />} />
      <Route path="help" element={<HelpCenterPage />} />
      <Route path="help/search" element={<HelpSearchPage />} />
      <Route path="help/categories/:slug" element={<HelpCategoryPage />} />
      <Route path="help/articles/:slug" element={<HelpArticlePage />} />
      <Route path="help/ask" element={<HelpAskPage />} />
      <Route path="help/support" element={<HelpSupportPage />} />
      <Route path="help/support/:requestId" element={<HelpSupportRequestPage />} />
      <Route path="settings" element={<Navigate to="/workspace" replace />} />
    </Route>
    <Route path="*" element={<NotFoundPage />} />
  </Routes>;
}
