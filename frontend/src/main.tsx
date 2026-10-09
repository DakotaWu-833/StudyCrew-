import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ErrorBoundary from "./components/ErrorBoundary";
import DashboardPage from "./pages/DashboardPage";
import InvitationsPage from "./pages/InvitationsPage";
import MeetingsPage from "./pages/MeetingsPage";
import NotificationsPage from "./pages/NotificationsPage";
import ProfilePage from "./pages/ProfilePage";
import ProjectOverviewPage from "./pages/ProjectOverviewPage";
import TaskDetailPage from "./pages/TaskDetailPage";
import TasksPage from "./pages/TasksPage";
import "./styles.css";
import "./launch.css";
import OfflineCoordinator from "./components/OfflineCoordinator";

const ContributionsPage = React.lazy(() => import("./pages/ContributionsPage"));
const AccountSecurityPage = React.lazy(() => import("./pages/AccountSecurityPage"));
const CampusPage = React.lazy(() => import("./pages/CampusPage"));
const ProjectPlanPage = React.lazy(() => import("./pages/ProjectPlanPage"));
const ResourcesPage = React.lazy(() => import("./pages/ResourcesPage"));
const CalendarPage = React.lazy(() => import("./pages/CalendarPage"));
const CoordinationPage = React.lazy(() => import("./pages/CoordinationPage"));
const EvidencePage = React.lazy(() => import("./pages/EvidencePage"));
const NotificationSettingsPage = React.lazy(() => import("./pages/NotificationSettingsPage"));
const SupportPage = React.lazy(() => import("./pages/SupportPage"));
const OperationsPage = React.lazy(() => import("./pages/OperationsPage"));
const ProjectUpdatesPage = React.lazy(() => import("./pages/ProjectUpdatesPage"));
const TeamFinderPage = React.lazy(() => import("./pages/TeamFinderPage"));
const ProjectFilesPage = React.lazy(() => import("./pages/ProjectFilesPage"));
const LearningExchangePage = React.lazy(() => import("./pages/LearningExchangePage"));
const ProjectChatPage = React.lazy(() => import("./pages/ProjectChatPage"));
const WorkloadPage = React.lazy(() => import("./pages/WorkloadPage"));
const OfflineTasksPage = React.lazy(() => import("./pages/OfflineTasksPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: true },
    mutations: { retry: false },
  },
});

function NotFound() {
  return <div className="empty-state"><h2>Page not found</h2><p>The workspace page you requested does not exist.</p><a className="button button--primary" href="/app/">Return to overview</a></div>;
}

ReactDOM.createRoot(document.getElementById("workspace-root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <OfflineCoordinator />
        <BrowserRouter>
          <React.Suspense fallback={<p>Opening saved tasks…</p>}>
          <Routes>
          <Route path="/app/offline" element={<OfflineTasksPage />} />
          <Route path="/app" element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="projects/:projectId/overview" element={<ProjectOverviewPage />} />
            <Route path="projects/:projectId/tasks" element={<TasksPage />} />
            <Route path="projects/:projectId/tasks/:taskId" element={<TaskDetailPage />} />
            <Route path="projects/:projectId/workload" element={<WorkloadPage />} />
            <Route path="projects/:projectId/meetings" element={<MeetingsPage />} />
            <Route path="projects/:projectId/contributions" element={<ContributionsPage />} />
            <Route path="invitations" element={<InvitationsPage />} />
            <Route path="invitations/:invitationId" element={<InvitationsPage />} />
            <Route path="notifications" element={<NotificationsPage />} />
            <Route path="profile" element={<ProfilePage />} />
            <Route path="security" element={<AccountSecurityPage />} />
            <Route path="campus" element={<CampusPage />} />
            <Route path="find-team" element={<TeamFinderPage />} />
            <Route path="calendar" element={<CalendarPage />} />
            <Route path="projects/:projectId/plan" element={<ProjectPlanPage />} />
            <Route path="projects/:projectId/resources" element={<ResourcesPage />} />
            <Route path="projects/:projectId/files" element={<ProjectFilesPage />} />
            <Route path="projects/:projectId/learning" element={<LearningExchangePage />} />
            <Route path="projects/:projectId/updates" element={<ProjectUpdatesPage />} />
            <Route path="projects/:projectId/chat" element={<ProjectChatPage />} />
            <Route path="projects/:projectId/calendar" element={<CalendarPage />} />
            <Route path="projects/:projectId/coordination" element={<CoordinationPage />} />
            <Route path="projects/:projectId/evidence" element={<EvidencePage />} />
            <Route path="notification-settings" element={<NotificationSettingsPage />} />
            <Route path="support" element={<SupportPage />} />
            <Route path="operations" element={<OperationsPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
          </Routes>
          </React.Suspense>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
