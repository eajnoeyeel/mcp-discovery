import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/config", () => ({
  config: {
    api: { isConfigured: true, url: "http://api.test", key: "test-key" },
    supabase: { isConfigured: true, url: "http://supabase.test", anonKey: "anon" },
  },
}));

vi.mock("@/lib/supabase", () => ({
  supabase: {
    from: vi.fn(() => {
      throw new Error("Dashboard page should not query Supabase directly");
    }),
  },
}));

vi.mock("@/lib/api", () => ({
  getProviderDashboard: vi.fn(async () => ({
    summary: {
      total_tools: 1,
      avg_geo_score: 0.42,
      needs_improvement: 1,
      indexed_count: 1,
    },
    tools: [
      {
        tool_id: "srv::lookup",
        tool_name: "lookup",
        server_id: "srv",
        server_name: "Owned Server",
        index_status: "indexed",
        geo_score: {
          total: 0.42,
          clarity: 0.5,
          disambiguation: 0.4,
          parameter_coverage: 0.4,
          boundary: 0.4,
          stats: 0.4,
          precision: 0.4,
        },
      },
    ],
  })),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    session: { access_token: "access-token-123" },
    user: { id: "user-123" },
    loading: false,
  }),
}));

import { getProviderDashboard } from "@/lib/api";
import Dashboard from "./Dashboard";

const mockedGetProviderDashboard = vi.mocked(getProviderDashboard);

describe("Dashboard page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders provider data from the backend API", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("Provider Dashboard")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("link", { name: "lookup" })).toBeInTheDocument();
    });
    expect(screen.getByText("Owned Server")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /register a server/i })).toBeInTheDocument();
  });

  it("shows the indexing-pending banner after registration", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/dashboard?registration=pending&server=srv"]}>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText(/registration submitted/i)).toBeInTheDocument();
    expect(screen.getByText("srv")).toBeInTheDocument();
  });

  it("surfaces the worst tool cue with a link to the tool detail page", async () => {
    mockedGetProviderDashboard.mockResolvedValueOnce({
      summary: {
        total_tools: 2,
        avg_geo_score: 0.42,
        needs_improvement: 1,
        indexed_count: 1,
      },
      tools: [
        {
          tool_id: "srv::lookup",
          tool_name: "lookup",
          server_id: "srv",
          server_name: "Owned Server",
          index_status: "indexed",
          geo_score: {
            total: 0.42,
            clarity: 0.5,
            disambiguation: 0.25,
            parameter_coverage: 0.4,
            boundary: 0.4,
            stats: 0.4,
            precision: 0.4,
          },
        },
        {
          tool_id: "srv::pending",
          tool_name: "pending",
          server_id: "srv",
          server_name: "Owned Server",
          index_status: "pending",
          geo_score: null,
        },
      ],
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByRole("link", { name: "lookup" })).toBeInTheDocument();
    });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Needs attention now");
    expect(alert).toHaveTextContent("Start with Disambig");

    const reviewLink = screen.getByRole("link", { name: "Review tool detail" });
    expect(reviewLink).toBeInTheDocument();
    expect(reviewLink).toHaveAttribute("href", "/dashboard/tools/srv%3A%3Alookup");

    const unscoredLink = screen.getByRole("link", { name: "pending" });
    expect(unscoredLink).toBeInTheDocument();
    expect(unscoredLink).toHaveAttribute("href", "/dashboard/tools/srv%3A%3Apending");
  });
});
