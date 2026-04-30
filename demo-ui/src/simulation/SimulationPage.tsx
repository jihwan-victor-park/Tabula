import { AnimatePresence } from "framer-motion";
import { useState } from "react";
import { Background } from "./components/Background";
import { StoreNode } from "./components/StoreNode";
import { PhaseHud } from "./components/PhaseHud";
import { SecureTunnels } from "./components/SecureTunnels";
import { AggregationCore } from "./components/AggregationCore";
import { BusinessPlanDrawer } from "./components/BusinessPlanDrawer";
import { STORES } from "./data/stores";
import { useDemoController } from "./hooks/useDemoController";
import { useLayout } from "./hooks/useLayout";

export default function SimulationPage() {
  const layout = useLayout();
  const { phase, loadingApi, apiError, nextPhase, reset, run, fetchLiveResults } =
    useDemoController();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const pebble = STORES[0]!;

  const isMapPhase = phase === "idle" || phase === "signals";
  const nodePositions = isMapPhase ? layout.mapPositions : layout.circlePositions;
  const canOpenDrawer = phase === "recommend" || phase === "complete";

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 0, overflow: "hidden" }}>
      <Background showMap={isMapPhase} />

      <SecureTunnels
        circlePositions={layout.circlePositions}
        center={layout.center}
        stores={STORES}
        phase={phase}
        w={layout.w}
        h={layout.h}
      />

      <AggregationCore center={layout.center} phase={phase} />

      {STORES.map((store, i) => (
        <StoreNode
          key={store.id}
          store={store}
          pos={nodePositions[i]!}
          phase={phase}
          index={i}
          isPrimary={i === 0}
          onSelect={() => {
            if (canOpenDrawer) setDrawerOpen((prev) => !prev);
          }}
        />
      ))}

      <AnimatePresence>
        {drawerOpen && canOpenDrawer && (
          <BusinessPlanDrawer
            key="drawer"
            business={pebble}
            onClose={() => setDrawerOpen(false)}
          />
        )}
      </AnimatePresence>

      <PhaseHud
        phase={phase}
        onRun={() => { setDrawerOpen(false); run(); }}
        onReset={() => { setDrawerOpen(false); reset(); }}
        onNext={nextPhase}
        onRefreshData={fetchLiveResults}
        loadingApi={loadingApi}
        apiError={apiError}
      />
    </div>
  );
}
