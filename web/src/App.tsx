import { useEffect, useRef } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { shouldSkipQuiz } from "./findMyEbike";
import { Header } from "./components/Header";
import { Footer } from "./components/Footer";
import { CompareDrawer } from "./components/CompareDrawer";
import { Browse } from "./pages/Browse";
import { FindMyEbike } from "./pages/FindMyEbike";
import { BikeDetail } from "./pages/BikeDetail";
import { Compare } from "./pages/Compare";
import { Analysis } from "./pages/Analysis";
import { Disclosure } from "./pages/Disclosure";
import { QaAnomalies } from "./pages/QaAnomalies";

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const routed = useRef(false);
  // First load only: a fresh landing on the bare root opens the beginner quiz,
  // unless the visitor chose "Hide this screen in the future". Deep links and
  // quiz/filter links (which carry a search string) are left alone, and in-app
  // navigation back to "/" afterwards shows Browse normally.
  useEffect(() => {
    if (routed.current) return;
    routed.current = true;
    if (location.pathname === "/" && !location.search && !shouldSkipQuiz()) {
      // next tick: a navigate() fired inside the very first effect pass loses
      // to the router's own initial-location settling under StrictMode. No
      // cleanup on purpose -- StrictMode's simulated unmount would cancel the
      // timer while the `routed` ref (which survives it) blocks the rerun;
      // App itself never truly unmounts.
      setTimeout(() => navigate("/find", { replace: true }), 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Browse />} />
          <Route path="/find" element={<FindMyEbike />} />
          <Route path="/bike/:id" element={<BikeDetail />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/disclosure" element={<Disclosure />} />
          {/* DEV-ONLY: the QA anomalies page is registered only in development
              (import.meta.env.DEV); it's tree-shaken out of the production build,
              and its data (anomalies.json) is never copied into production. */}
          {import.meta.env.DEV && <Route path="/qa" element={<QaAnomalies />} />}
          <Route path="*" element={<Browse />} />
        </Routes>
      </main>
      <CompareDrawer />
      <Footer />
    </div>
  );
}
