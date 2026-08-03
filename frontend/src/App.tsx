import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { TopBar } from "./components/TopBar";
import FleetPage from "./pages/FleetPage";
import KnowledgePage from "./pages/KnowledgePage";
import MetricsPage from "./pages/MetricsPage";
import PacksPage from "./pages/PacksPage";
import PortfolioHomePage from "./pages/PortfolioHomePage";
import ProjectDetailPage from "./pages/ProjectDetailPage";
import ProjectPlaybookEditorPage from "./pages/ProjectPlaybookEditorPage";
import ProjectsPage from "./pages/ProjectsPage";
import QueuePage from "./pages/QueuePage";
import RunDetailPage from "./pages/RunDetailPage";
import RunsHomePage from "./pages/RunsHomePage";
import UiKit from "./pages/dev/UiKit";

export default function App() {
  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)]">
      <Shell />
      <div className="pl-60">
        <TopBar />
        <main className="p-6">
          <Routes>
            <Route path="/" element={<PortfolioHomePage />} />
            <Route path="/queue" element={<QueuePage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/:id" element={<ProjectDetailPage />} />
            <Route path="/projects/:id/playbooks/new" element={<ProjectPlaybookEditorPage />} />
            <Route path="/projects/:id/playbooks/:slug" element={<ProjectPlaybookEditorPage />} />
            <Route path="/runs" element={<RunsHomePage />} />
            <Route path="/runs/:id" element={<RunDetailPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/fleet" element={<FleetPage />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="/packs" element={<PacksPage />} />
            <Route path="/dev/ui-kit" element={<UiKit />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
