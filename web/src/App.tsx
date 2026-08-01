import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"

import { TooltipProvider } from "@/components/ui/tooltip"
import { Toaster } from "@/components/ui/sonner"
import { Dashboard } from "@/components/Dashboard"
import { LandingPage } from "@/pages/LandingPage"

export function App() {
  return (
    <BrowserRouter>
      <TooltipProvider>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/console" element={<Dashboard />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <Toaster richColors theme="dark" position="bottom-right" />
      </TooltipProvider>
    </BrowserRouter>
  )
}
