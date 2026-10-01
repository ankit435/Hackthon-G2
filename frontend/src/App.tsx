import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AskPage } from "./pages/AskPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { FilePage } from "./pages/FilePage";
import { LibraryPage } from "./pages/LibraryPage";
import { SearchPage } from "./pages/SearchPage";
import { SystemPage } from "./pages/SystemPage";
import { UploadPage } from "./pages/UploadPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/search" replace />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="library" element={<LibraryPage />} />
        <Route path="files/:fileId" element={<FilePage />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="ask" element={<AskPage />} />
        <Route path="evaluation" element={<EvaluationPage />} />
        <Route path="system" element={<SystemPage />} />
        <Route path="*" element={<Navigate to="/search" replace />} />
      </Route>
    </Routes>
  );
}
