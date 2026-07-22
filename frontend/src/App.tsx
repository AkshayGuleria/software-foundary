import { NavLink, Route, Routes } from "react-router-dom";
import FleetPage from "./pages/FleetPage";
import KnowledgePage from "./pages/KnowledgePage";
import PacksPage from "./pages/PacksPage";
import PortfolioHomePage from "./pages/PortfolioHomePage";
import ProjectsPage from "./pages/ProjectsPage";
import RunDetailPage from "./pages/RunDetailPage";
import RunsHomePage from "./pages/RunsHomePage";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex items-center gap-4 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold">Foundry</h1>
        <nav className="flex gap-3 text-sm">
          <NavLink to="/" end className="text-slate-400 hover:text-orange-400">
            Portfolio
          </NavLink>
          <NavLink to="/projects" className="text-slate-400 hover:text-orange-400">
            Projects
          </NavLink>
          <NavLink to="/runs" className="text-slate-400 hover:text-orange-400">
            Runs
          </NavLink>
          <NavLink to="/knowledge" className="text-slate-400 hover:text-orange-400">
            Knowledge
          </NavLink>
          <NavLink to="/fleet" className="text-slate-400 hover:text-orange-400">
            Fleet
          </NavLink>
          <NavLink to="/packs" className="text-slate-400 hover:text-orange-400">
            Packs
          </NavLink>
        </nav>
      </header>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<PortfolioHomePage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/runs" element={<RunsHomePage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/fleet" element={<FleetPage />} />
          <Route path="/packs" element={<PacksPage />} />
        </Routes>
      </main>
    </div>
  );
}
