import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes, useParams } from 'react-router-dom';
import { SignInPage, StoresPage, WelcomePage } from './app/Auth';
import { DataPage, ImportPage } from './app/Data';
import { HomePage } from './app/Home';
import { InsightsPage } from './app/Insights';
import { InventoryPage, ItemPage } from './app/Inventory';
import { OrdersListPage, SuggestionsPage } from './app/Orders';
import { ScanPage } from './app/Scan';
import { SettingsPage } from './app/Settings';
import { SupplierPage, SuppliersPage } from './app/Suppliers';
import { ConnectionsPage } from './ops/ConnectionsPage';
import { OrderPage } from './ops/OrdersPage';
import { ReceiveOrderPage, ReceivingPage } from './ops/ReceivingPage';
import { AgentsPage } from './pages/AgentsPage';
import { DashboardPage } from './pages/DashboardPage';

const SimulationPage = lazy(() => import('./simulation/SimulationPage'));

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
      <Route path="/app" element={<HomePage />} />
      <Route path="/app/welcome" element={<WelcomePage />} />
      <Route path="/app/stores" element={<StoresPage />} />
      <Route path="/app/inventory" element={<InventoryPage />} />
      <Route path="/app/inventory/:id" element={<ItemPage />} />
      <Route path="/app/scan" element={<ScanPage />} />
      <Route path="/app/insights" element={<InsightsPage />} />
      <Route path="/app/orders" element={<SuggestionsPage />} />
      <Route path="/app/orders/list" element={<OrdersListPage />} />
      <Route path="/app/orders/:id" element={<OrderPage />} />
      <Route path="/app/receiving" element={<ReceivingPage />} />
      <Route path="/app/receiving/:id" element={<ReceiveOrderPage />} />
      <Route path="/app/suppliers" element={<SuppliersPage />} />
      <Route path="/app/suppliers/:id" element={<SupplierPage />} />
      <Route path="/app/data" element={<DataPage />} />
      <Route path="/app/data/import" element={<ImportPage />} />
      <Route path="/app/data/square" element={<ConnectionsPage />} />
      <Route path="/app/settings" element={<SettingsPage />} />
      {/* earlier addresses */}
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
