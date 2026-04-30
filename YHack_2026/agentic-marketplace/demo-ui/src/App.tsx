import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AgentsPage } from './pages/AgentsPage';
import { DashboardPage } from './pages/DashboardPage';
import { InventoryPage } from './pages/InventoryPage';
import { OrdersPage } from './pages/OrdersPage';
import { SalesHistoryPage } from './pages/SalesHistoryPage';
import { TrendsPage } from './pages/TrendsPage';

const SimulationPage = lazy(() => import('./simulation/SimulationPage'));

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
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
    </Routes>
  );
}
