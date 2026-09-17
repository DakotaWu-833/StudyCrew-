import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ErrorBoundary from "./components/ErrorBoundary";
import ContributionsPage from "./pages/ContributionsPage";
import DashboardPage from "./pages/DashboardPage";
import InvitationsPage from "./pages/InvitationsPage";
import MeetingsPage from "./pages/MeetingsPage";
import NotificationsPage from "./pages/NotificationsPage";
import ProfilePage from "./pages/ProfilePage";
import ProjectOverviewPage from "./pages/ProjectOverviewPage";
import TaskDetailPage from "./pages/TaskDetailPage";
import TasksPage from "./pages/TasksPage";
import "./styles.css";

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
        <BrowserRouter>
          <Routes>
          <Route path="/app" element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="projects/:projectId/overview" element={<ProjectOverviewPage />} />
            <Route path="projects/:projectId/tasks" element={<TasksPage />} />
            <Route path="projects/:projectId/tasks/:taskId" element={<TaskDetailPage />} />
            <Route path="projects/:projectId/meetings" element={<MeetingsPage />} />
            <Route path="projects/:projectId/contributions" element={<ContributionsPage />} />
            <Route path="invitations" element={<InvitationsPage />} />
            <Route path="invitations/:invitationId" element={<InvitationsPage />} />
            <Route path="notifications" element={<NotificationsPage />} />
            <Route path="profile" element={<ProfilePage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
