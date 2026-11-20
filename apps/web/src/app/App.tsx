import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "@/auth/AuthProvider";
import { AppShell } from "@/components/layout/AppShell";
import { Spinner } from "@/components/ui";
import { LoginPage } from "@/features/auth/LoginPage";
import { TokenStatusPage } from "@/features/public/TokenStatusPage";
import { TodayPage } from "@/features/today/TodayPage";

const OnboardingPage = lazy(() => import("@/features/onboarding/OnboardingPage"));
const CalendarPage = lazy(() => import("@/features/appointments/CalendarPage"));
const QueuePage = lazy(() => import("@/features/queue/QueuePage"));
const PatientsPage = lazy(() => import("@/features/patients/PatientsPage"));
const PatientPage = lazy(() => import("@/features/patients/PatientPage"));
const InboxPage = lazy(() => import("@/features/inbox/InboxPage"));
const RecallPage = lazy(() => import("@/features/recall/RecallPage"));
const RevenuePage = lazy(() => import("@/features/revenue/RevenuePage"));
const DoctorsPage = lazy(() => import("@/features/doctors/DoctorsPage"));
const SettingsPage = lazy(() => import("@/features/settings/SettingsPage"));
const MissedCallsPage = lazy(() => import("@/features/calls/MissedCallsPage"));
const AdminPage = lazy(() => import("@/features/admin/AdminPage"));

function FullScreenLoading() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <Spinner />
    </div>
  );
}

function RequireClinic({ children }: { children: ReactNode }) {
  const { status, session } = useAuth();
  const location = useLocation();
  if (status === "loading") return <FullScreenLoading />;
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (!session?.clinicId) return <Navigate to={session?.isPlatformAdmin ? "/admin" : "/onboarding"} replace />;
  return <>{children}</>;
}

function RequireUser({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  if (status === "loading") return <FullScreenLoading />;
  if (status === "anonymous") return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function App() {
  return (
    <Suspense fallback={<FullScreenLoading />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/t/:code" element={<TokenStatusPage />} />
        <Route
          path="/admin"
          element={
            <RequireUser>
              <AdminPage />
            </RequireUser>
          }
        />
        <Route
          path="/onboarding"
          element={
            <RequireUser>
              <OnboardingPage />
            </RequireUser>
          }
        />
        <Route
          element={
            <RequireClinic>
              <AppShell />
            </RequireClinic>
          }
        >
          <Route index element={<TodayPage />} />
          <Route path="calendar" element={<CalendarPage />} />
          <Route path="queue" element={<QueuePage />} />
          <Route path="patients" element={<PatientsPage />} />
          <Route path="patients/:patientId" element={<PatientPage />} />
          <Route path="inbox" element={<InboxPage />} />
          <Route path="inbox/:conversationId" element={<InboxPage />} />
          <Route path="recall" element={<RecallPage />} />
          <Route path="revenue" element={<RevenuePage />} />
          <Route path="doctors" element={<DoctorsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="missed-calls" element={<MissedCallsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
