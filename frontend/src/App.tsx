import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import FleetPage from "./pages/FleetPage";
import ProjectsPage from "./pages/ProjectsPage";
import RunDetailPage from "./pages/RunDetailPage";
import RunsHomePage from "./pages/RunsHomePage";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex items-center gap-4 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold">Foundry</h1>
        <nav className="flex gap-3 text-sm">
          <NavLink to="/projects" className="text-slate-400 hover:text-orange-400">
            Projects
          </NavLink>
          <NavLink to="/runs" className="text-slate-400 hover:text-orange-400">
            Runs
          </NavLink>
          <NavLink to="/fleet" className="text-slate-400 hover:text-orange-400">
            Fleet
          </NavLink>
        </nav>
      </header>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/runs" element={<RunsHomePage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/fleet" element={<FleetPage />} />
        </Routes>
      </main>
    </div>
  );
}
