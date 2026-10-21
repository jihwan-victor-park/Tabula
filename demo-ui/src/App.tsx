import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AgentsPage } from './pages/AgentsPage';
import { DashboardPage } from './pages/DashboardPage';
import { InventoryPage } from './pages/InventoryPage';
import { OrdersPage } from './pages/OrdersPage';
import { PriceScoutPage } from './pages/PriceScoutPage';
import { SalesHistoryPage } from './pages/SalesHistoryPage';
import { TrendsPage } from './pages/TrendsPage';
import { ConnectionsPage } from './ops/ConnectionsPage';
import { ImportsPage } from './ops/ImportsPage';
import { OrderPage, OrdersPage as PurchaseOrdersPage } from './ops/OrdersPage';
import { ReceiveOrderPage, ReceivingPage } from './ops/ReceivingPage';
import { SetupPage } from './ops/SetupPage';
import { TodayPage } from './ops/TodayPage';

const SimulationPage = lazy(() => import('./simulation/SimulationPage'));

export function App() {

  return (
    <Routes>
      <Route path="/" element={<Navigate to="/ops/today" replace />} />
      <Route path="/ops" element={<Navigate to="/ops/today" replace />} />
      <Route path="/ops/today" element={<TodayPage />} />
      <Route path="/ops/imports" element={<ImportsPage />} />
      <Route path="/ops/orders" element={<PurchaseOrdersPage />} />
      <Route path="/ops/orders/:id" element={<OrderPage />} />
      <Route path="/ops/receiving" element={<ReceivingPage />} />
      <Route path="/ops/receiving/:id" element={<ReceiveOrderPage />} />
      <Route path="/ops/connections" element={<ConnectionsPage />} />
      <Route path="/ops/setup" element={<SetupPage />} />
      <Route path="/dashboard" element={<DashboardPage />} />
      <Route path="/agents" element={<AgentsPage />} />
      <Route
        path="/agentic-simulation"
        element={
          <Suspense fallback={<div style={{ color: '#1B3A4B', padding: 40 }}>Loading simulation…</div>}>
            <SimulationPage />
          </Suspense>
        }
      />
      <Route path="/inventory" element={<InventoryPage />} />
      <Route path="/orders" element={<OrdersPage />} />
      <Route path="/sales-history" element={<SalesHistoryPage />} />
      <Route path="/trends" element={<TrendsPage />} />
      <Route path="/price-scout" element={<PriceScoutPage />} />
    </Routes>
  );
}
