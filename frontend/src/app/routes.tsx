import { lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { EducationLayout } from '@/components/materialm/EducationLayout';
import { OrganizationProfilePage, WorkspaceStarterPanel } from '@/components/WorkspaceSetup';
import { OrganizationLayout } from './guards/OrganizationLayout';
import { ProtectedLayout } from './guards/ProtectedLayout';

const AgentBuilderPage = lazy(() => import('@/pages/AgentBuilderPage').then((module) => ({ default: module.AgentBuilderPage })));
const AgentsPage = lazy(() => import('@/features/dashboard/AgentsRoutePage').then((module) => ({ default: module.AgentsRoutePage })));
const AnalyticsPage = lazy(() => import('@/pages/AnalyticsPage').then((module) => ({ default: module.AnalyticsPage })));
const AuditPage = lazy(() => import('@/pages/AuditPage').then((module) => ({ default: module.AuditPage })));
const BatchesPage = lazy(() => import('@/pages/BatchesPage').then((module) => ({ default: module.BatchesPage })));
const BotWorkflowBuilderPage = lazy(() => import('@/pages/BotWorkflowBuilderPage').then((module) => ({ default: module.BotWorkflowBuilderPage })));
const ConversationsPage = lazy(() => import('@/pages/ConversationsPage').then((module) => ({ default: module.ConversationsPage })));
const CoursesPage = lazy(() => import('@/pages/CoursesPage').then((module) => ({ default: module.CoursesPage })));
const CourseKnowledgePage = lazy(() => import('@/features/knowledge').then((module) => ({ default: module.CourseKnowledgePage })));
const CRMWorkflowPage = lazy(() => import('@/pages/CRMWorkflowPage').then((module) => ({ default: module.CRMWorkflowPage })));
const DeployPage = lazy(() => import('@/pages/DeployPage').then((module) => ({ default: module.DeployPage })));
const EducationAccessRecoveryPage = lazy(() => import('@/pages/EducationAccessRecoveryPage').then((module) => ({ default: module.EducationAccessRecoveryPage })));
const EducationAccessRequestsPage = lazy(() => import('@/pages/EducationAccessRequestsPage').then((module) => ({ default: module.EducationAccessRequestsPage })));
const EducationActivityPage = lazy(() => import('@/pages/EducationActivityPage').then((module) => ({ default: module.EducationActivityPage })));
const EducationEnrollmentsPage = lazy(() => import('@/pages/EducationEnrollmentsPage').then((module) => ({ default: module.EducationEnrollmentsPage })));
const EducationHubPage = lazy(() => import('@/pages/EducationHubPage').then((module) => ({ default: module.EducationHubPage })));
const EducationStudentDetailPage = lazy(() => import('@/pages/EducationStudentDetailPage').then((module) => ({ default: module.EducationStudentDetailPage })));
const EducationStudentImportPage = lazy(() => import('@/pages/EducationStudentImportPage').then((module) => ({ default: module.EducationStudentImportPage })));
const ForgotPasswordPageView = lazy(() => import('@/features/website/pages/ForgotPasswordPage').then((module) => ({ default: module.ForgotPasswordPage })));
const IntegrationsHubPage = lazy(() => import('@/pages/IntegrationsHubPage').then((module) => ({ default: module.IntegrationsHubPage })));
const IntegrationManagementPage = lazy(() => import('@/pages/IntegrationManagementPage').then((module) => ({ default: module.IntegrationManagementPage })));
const HelpArticlePage = lazy(() => import('@/pages/HelpArticlePage').then((module) => ({ default: module.HelpArticlePage })));
const HelpAskPage = lazy(() => import('@/pages/HelpAskPage').then((module) => ({ default: module.HelpAskPage })));
const HelpCategoryPage = lazy(() => import('@/pages/HelpCategoryPage').then((module) => ({ default: module.HelpCategoryPage })));
const HelpCenterPage = lazy(() => import('@/pages/HelpCenterPage').then((module) => ({ default: module.HelpCenterPage })));
const HelpSearchPage = lazy(() => import('@/pages/HelpSearchPage').then((module) => ({ default: module.HelpSearchPage })));
const HelpSupportPage = lazy(() => import('@/pages/HelpSupportPage').then((module) => ({ default: module.HelpSupportPage })));
const HelpSupportRequestPage = lazy(() => import('@/pages/HelpSupportRequestPage').then((module) => ({ default: module.HelpSupportRequestPage })));
const LeadsPage = lazy(() => import('@/pages/LeadsPage').then((module) => ({ default: module.LeadsPage })));
const LoginPageView = lazy(() => import('@/features/website/pages/LoginPage').then((module) => ({ default: module.LoginPage })));
const MFAChallengePageView = lazy(() => import('@/features/website/pages/MFAChallengePage').then((module) => ({ default: module.MFAChallengePage })));
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage').then((module) => ({ default: module.NotFoundPage })));
const OverviewPage = lazy(() => import('@/pages/OverviewPage').then((module) => ({ default: module.OverviewPage })));
const PlatformAdminPageView = lazy(() => import('@/features/super-admin').then((module) => ({ default: module.SuperAdminPage })));
const ResetPasswordPageView = lazy(() => import('@/features/website/pages/ResetPasswordPage').then((module) => ({ default: module.ResetPasswordPage })));
const SignupPageView = lazy(() => import('@/features/website/pages/SignupPage').then((module) => ({ default: module.SignupPage })));
const StudentsPage = lazy(() => import('@/pages/StudentsPage').then((module) => ({ default: module.StudentsPage })));
const VerifyEmailPageView = lazy(() => import('@/features/website/pages/VerifyEmailPage').then((module) => ({ default: module.VerifyEmailPage })));
const WorkspaceInvitationPageView = lazy(() => import('@/features/website/pages/WorkspaceInvitationPage').then((module) => ({ default: module.WorkspaceInvitationPage })));
const WorkspaceSettingsPageView = lazy(() => import('@/features/admin').then((module) => ({ default: module.WorkspaceSettingsPage })));
const SitePrivacyPageView = lazy(() => import('@/features/website/pages/SitePrivacyPage').then((module) => ({ default: module.SitePrivacyPage })));
const WebsiteCampaignPageView = lazy(() => import('@/pages/WebsiteCampaignPage').then((module) => ({ default: module.WebsiteCampaignPage })));
const WebsiteCMSPageView = lazy(() => import('@/pages/WebsiteCMSPage').then((module) => ({ default: module.WebsiteCMSPage })));
const WidgetDemoPageView = lazy(() => import('@/features/website/pages/WidgetDemoPage').then((module) => ({ default: module.WidgetDemoPage })));

const OrganizationsPage = lazy(() => import('@/pages/OrganizationsPage').then((module) => ({ default: module.OrganizationsPage })));
const OrganizationBillingPage = lazy(() => import('@/pages/OrganizationBillingPage').then((module) => ({ default: module.OrganizationBillingPage })));

export function AppRoutes() {
  return <Routes>
    <Route path="privacy/site/:workspaceId" element={<SitePrivacyPageView />} />
    <Route path="/login" element={<LoginPageView />} />
    <Route path="/signup" element={<SignupPageView />} />
    <Route path="/verify-email" element={<VerifyEmailPageView />} />
    <Route path="/forgot-password" element={<ForgotPasswordPageView />} />
    <Route path="/reset-password" element={<ResetPasswordPageView />} />
    <Route path="/mfa-challenge" element={<MFAChallengePageView />} />
    <Route path="/workspace-invitation" element={<WorkspaceInvitationPageView />} />
    <Route path="/education-access-recovery" element={<EducationAccessRecoveryPage />} />
    <Route path="/demo/:agentId?" element={<WidgetDemoPageView />} />
    <Route path="/widget/:agentId" element={<WidgetDemoPageView embedded />} />
    <Route element={<OrganizationLayout />}>
      <Route path="organizations" element={<OrganizationsPage />} />
      <Route path="organization/billing" element={<OrganizationBillingPage />} />
    </Route>
    <Route element={<ProtectedLayout />}>
      <Route index element={<><WorkspaceStarterPanel /><OverviewPage /></>} />
      <Route path="organization/profile" element={<OrganizationProfilePage />} />
      <Route path="agents" element={<AgentsPage />} />
      <Route path="agents/:agentId/:tab?" element={<AgentBuilderPage />} />
      <Route path="education" element={<EducationLayout />}>
        <Route index element={<EducationHubPage />} />
        <Route path="courses" element={<CoursesPage />} />
        <Route path="knowledge" element={<CourseKnowledgePage />} />
        <Route path="batches" element={<BatchesPage />} />
        <Route path="students" element={<StudentsPage />} />
        <Route path="enrollments" element={<EducationEnrollmentsPage />} />
        <Route path="students/import" element={<EducationStudentImportPage />} />
        <Route path="students/:studentId" element={<EducationStudentDetailPage />} />
        <Route path="access-requests" element={<EducationAccessRequestsPage />} />
        <Route path="activity" element={<EducationActivityPage />} />
      </Route>
      <Route path="conversations" element={<ConversationsPage />} />
      <Route path="leads" element={<LeadsPage />} />
      <Route path="crm-workflow" element={<CRMWorkflowPage />} />
      <Route path="workflows" element={<BotWorkflowBuilderPage />} />
      <Route path="analytics" element={<AnalyticsPage />} />
      <Route path="site-cms" element={<WebsiteCMSPageView />} />
      <Route path="site-campaigns" element={<WebsiteCampaignPageView />} />
      <Route path="audit" element={<AuditPage />} />
      <Route path="integrations" element={<IntegrationsHubPage />} />
      <Route path="integrations/advanced" element={<IntegrationManagementPage />} />
      <Route path="deploy" element={<DeployPage />} />
      {/* The settings center is the single workspace administration entry point. */}
      <Route path="workspace" element={<Navigate to="/workspace/settings/general" replace />} />
      {/* Keep the legacy URL, but route it to the complete draft/preview/
          publish white-label control center. */}
      <Route path="workspace/white-label" element={<Navigate to="/workspace/settings/branding" replace />} />
      <Route path="workspace/settings" element={<Navigate to="/workspace/settings/general" replace />} />
      <Route path="workspace/settings/:section" element={<WorkspaceSettingsPageView />} />
      {/* Platform control-plane aliases keep the admin hierarchy addressable
          while the current control-plane screen owns the shared data loaders. */}
      <Route path="platform-admin" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/dashboard" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/tenants" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/workspaces" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/users" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/subscriptions" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/plans" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/usage" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/channels" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/integrations" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/jobs" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/webhooks" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/audit" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/security" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/support" element={<PlatformAdminPageView />} />
      <Route path="platform-admin/system" element={<PlatformAdminPageView />} />
      <Route path="help" element={<HelpCenterPage />} />
      <Route path="help/search" element={<HelpSearchPage />} />
      <Route path="help/categories/:slug" element={<HelpCategoryPage />} />
      <Route path="help/articles/:slug" element={<HelpArticlePage />} />
      <Route path="help/ask" element={<HelpAskPage />} />
      <Route path="help/support" element={<HelpSupportPage />} />
      <Route path="help/support/:requestId" element={<HelpSupportRequestPage />} />
      <Route path="settings" element={<Navigate to="/workspace/settings/general" replace />} />
    </Route>
    <Route path="*" element={<NotFoundPage />} />
  </Routes>;
}
