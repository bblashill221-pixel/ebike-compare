import { Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { Footer } from "./components/Footer";
import { CompareDrawer } from "./components/CompareDrawer";
import { Browse } from "./pages/Browse";
import { BikeDetail } from "./pages/BikeDetail";
import { Compare } from "./pages/Compare";
import { Analysis } from "./pages/Analysis";
import { Disclosure } from "./pages/Disclosure";

export default function App() {
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Browse />} />
          <Route path="/bike/:id" element={<BikeDetail />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/disclosure" element={<Disclosure />} />
          <Route path="*" element={<Browse />} />
        </Routes>
      </main>
      <CompareDrawer />
      <Footer />
    </div>
  );
}
