import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/contexts/AuthContext";
import Layout from "@/components/Layout";
import ProtectedRoute from "@/components/ProtectedRoute";
import Landing from "@/pages/Landing";
import Search from "@/pages/Search";
import Servers from "@/pages/Servers";
import ServerDetail from "@/pages/ServerDetail";
import ToolDetail from "@/pages/ToolDetail";
import Dashboard from "@/pages/Dashboard";
import DashboardToolDetail from "@/pages/DashboardToolDetail";
import DashboardServerDetail from "@/pages/DashboardServerDetail";
import DashboardInsights from "@/pages/DashboardInsights";
import DashboardSettings from "@/pages/DashboardSettings";
import RegisterServer from "@/pages/RegisterServer";
import HostedConnect from "@/pages/HostedConnect";
import HostedConnectUnavailable from "@/pages/HostedConnectUnavailable";
import ConnectComplete from "@/pages/ConnectComplete";
import OAuthComplete from "@/pages/OAuthComplete";
import { config } from "@/lib/config";
import Login from "@/pages/Login";
import NotFound from "@/pages/NotFound";

const App = () => {
  const [queryClient] = useState(() => new QueryClient());

  return (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Sonner />
      <BrowserRouter>
        <AuthProvider queryClient={queryClient}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<Landing />} />
              <Route path="/search" element={<Search />} />
              <Route path="/servers" element={<Servers />} />
              <Route path="/servers/:serverId" element={<ServerDetail />} />
              <Route path="/tools/:toolId" element={<ToolDetail />} />
              <Route path="/login" element={<Login />} />
              <Route path="/oauth/complete" element={<ProtectedRoute><OAuthComplete /></ProtectedRoute>} />
              <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
              <Route path="/dashboard/register" element={<ProtectedRoute><RegisterServer /></ProtectedRoute>} />
              <Route
                path="/connect"
                element={
                  <ProtectedRoute>
                    {config.hostedConnect.enabled ? <HostedConnect /> : <HostedConnectUnavailable />}
                  </ProtectedRoute>
                }
              />
              <Route
                path="/connect/complete"
                element={
                  <ProtectedRoute>
                    {config.hostedConnect.enabled ? <ConnectComplete /> : <HostedConnectUnavailable />}
                  </ProtectedRoute>
                }
              />
              <Route path="/dashboard/tools/:toolId" element={<ProtectedRoute><DashboardToolDetail /></ProtectedRoute>} />
              <Route path="/dashboard/servers/:serverId" element={<ProtectedRoute><DashboardServerDetail /></ProtectedRoute>} />
              <Route path="/dashboard/insights" element={<ProtectedRoute><DashboardInsights /></ProtectedRoute>} />
              <Route path="/dashboard/settings" element={<ProtectedRoute><DashboardSettings /></ProtectedRoute>} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
  );
};

export default App;
