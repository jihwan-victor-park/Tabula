import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes, useParams } from 'react-router-dom';
import { SignInPage, StoresPage, WelcomePage } from './app/Auth';
import { DataPage, ImportPage } from './app/Data';
import { InsightsPage } from './app/Insights';
import { InventoryPage } from './app/Inventory';
import { OrdersPage, PlanPage } from './app/Orders';
import { OverviewPage } from './app/Overview';
import { ScanPage } from './app/Scan';
import { SettingsPage, TeamPage } from './app/Settings';
import { SetupPage } from './app/Setup';
import { SupplierPage, SuppliersPage } from './app/Suppliers';
import { ConnectionsPage } from './ops/ConnectionsPage';
import { OrderPage } from './ops/OrdersPage';
import { ReceiveOrderPage } from './ops/ReceivingPage';
import { AgentsPage } from './pages/AgentsPage';
import { DashboardPage } from './pages/DashboardPage';

const SimulationPage = lazy(() => import('./simulation/SimulationPage'));

function Moved({ to }: { to: string }) {
  const { id } = useParams();
  return <Navigate to={`${to}${id}`} replace />;
}

function LegacyOrder() {
  const { id } = useParams();
  return <Navigate to={`/app/orders/${id}`} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/app" replace />} />
      <Route path="/signin" element={<SignInPage mode="signin" />} />
      <Route path="/signup" element={<SignInPage mode="signup" />} />
      <Route path="/app" element={<OverviewPage />} />
      <Route path="/app/setup" element={<SetupPage />} />
      <Route path="/app/welcome" element={<WelcomePage />} />
      <Route path="/app/stores" element={<StoresPage />} />
      <Route path="/app/inventory" element={<InventoryPage />} />
      <Route path="/app/inventory/scan" element={<ScanPage />} />
      <Route path="/app/inventory/:id" element={<InventoryPage />} />
      <Route path="/app/insights" element={<InsightsPage />} />
      <Route path="/app/orders" element={<OrdersPage />} />
      <Route path="/app/orders/plan" element={<PlanPage />} />
      <Route path="/app/orders/suppliers" element={<SuppliersPage />} />
      <Route path="/app/orders/suppliers/:id" element={<SupplierPage />} />
      <Route path="/app/orders/:id" element={<OrderPage />} />
      <Route path="/app/receiving/:id" element={<ReceiveOrderPage />} />
      <Route path="/app/settings" element={<SettingsPage />} />
      <Route path="/app/settings/team" element={<TeamPage />} />
      <Route path="/app/settings/data" element={<DataPage />} />
      <Route path="/app/settings/data/import" element={<ImportPage />} />
      <Route path="/app/settings/data/square" element={<ConnectionsPage />} />
      {/* earlier addresses */}
      <Route path="/app/scan" element={<Navigate to="/app/inventory/scan" replace />} />
      <Route path="/app/orders/list" element={<Navigate to="/app/orders" replace />} />
      <Route path="/app/receiving" element={<Navigate to="/app/orders?tab=progress" replace />} />
      <Route path="/app/suppliers" element={<Navigate to="/app/orders/suppliers" replace />} />
      <Route path="/app/suppliers/:id" element={<Moved to="/app/orders/suppliers/" />} />
      <Route path="/app/data" element={<Navigate to="/app/settings/data" replace />} />
      <Route path="/app/data/import" element={<Navigate to="/app/settings/data/import" replace />} />
      <Route path="/app/data/square" element={<Navigate to="/app/settings/data/square" replace />} />
      <Route path="/ops/*" element={<Navigate to="/app" replace />} />
      <Route path="/ops/orders/:id" element={<LegacyOrder />} />
      {/* hackathon prototype, kept for reference */}
      <Route path="/legacy/dashboard" element={<DashboardPage />} />
      <Route path="/legacy/agents" element={<AgentsPage />} />
      <Route path="/legacy/simulation" element={<Suspense fallback={<div style={{ padding: 40 }}>Loading…</div>}><SimulationPage /></Suspense>} />
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  );
}
