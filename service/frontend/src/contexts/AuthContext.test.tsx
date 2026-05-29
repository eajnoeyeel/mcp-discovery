import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const authMocks = vi.hoisted(() => ({
  signInWithOAuth: vi.fn(),
  signOut: vi.fn(),
  getSession: vi.fn(async () => ({ data: { session: null } })),
  unsubscribe: vi.fn(),
  onAuthStateChange: vi.fn(),
}));

vi.mock("@/lib/config", () => ({
  config: {
    supabase: { isConfigured: true, url: "http://supabase.test", anonKey: "anon" },
    api: { isConfigured: true, url: "http://api.test", key: "test-key" },
  },
}));

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      onAuthStateChange: authMocks.onAuthStateChange,
      getSession: authMocks.getSession,
      signInWithOAuth: authMocks.signInWithOAuth,
      signOut: authMocks.signOut,
    },
  },
}));

import { AuthProvider, useAuth } from "./AuthContext";

function AuthProbe() {
  const { signInWithGoogle } = useAuth();

  return (
    <button onClick={() => signInWithGoogle("/dashboard/tools/srv::lookup")}>
      Sign in with Google
    </button>
  );
}

describe("AuthContext", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMocks.onAuthStateChange.mockReturnValue({
      data: { subscription: { unsubscribe: authMocks.unsubscribe } },
    });
    authMocks.getSession.mockResolvedValue({ data: { session: null } });
    authMocks.signInWithOAuth.mockResolvedValue({ error: null });
  });

  it("starts Google OAuth with the requested redirect path", async () => {
    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Sign in with Google" }));

    await waitFor(() => {
      expect(authMocks.signInWithOAuth).toHaveBeenCalledWith({
        provider: "google",
        options: {
          redirectTo: "http://localhost:3000/dashboard/tools/srv::lookup",
        },
      });
    });
  });

  it("clears the query cache on SIGNED_OUT", async () => {
    let capturedCallback: ((event: string, session: unknown) => void) | undefined;
    authMocks.onAuthStateChange.mockImplementation((cb: (event: string, session: unknown) => void) => {
      capturedCallback = cb;
      return { data: { subscription: { unsubscribe: authMocks.unsubscribe } } };
    });
    const queryClient = { clear: vi.fn() };

    render(
      <AuthProvider queryClient={queryClient as unknown as import("@tanstack/react-query").QueryClient}>
        <AuthProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(authMocks.onAuthStateChange).toHaveBeenCalled());

    // Baseline event so the listener treats the test event as a real change, not a
    // first-mount baseline. Without this, the cold-mount-stale-render guard skips the
    // first event's cache wipe (see AuthContext.tsx:hasReceivedFirstEventRef).
    capturedCallback?.("INITIAL_SESSION", { user: { id: "user-a" }, access_token: "a" });

    capturedCallback?.("SIGNED_OUT", null);

    expect(queryClient.clear).toHaveBeenCalledTimes(1);
  });

  it("does NOT clear the query cache on TOKEN_REFRESHED", async () => {
    let capturedCallback: ((event: string, session: unknown) => void) | undefined;
    authMocks.onAuthStateChange.mockImplementation((cb: (event: string, session: unknown) => void) => {
      capturedCallback = cb;
      return { data: { subscription: { unsubscribe: authMocks.unsubscribe } } };
    });
    const queryClient = { clear: vi.fn() };

    render(
      <AuthProvider queryClient={queryClient as unknown as import("@tanstack/react-query").QueryClient}>
        <AuthProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(authMocks.onAuthStateChange).toHaveBeenCalled());

    capturedCallback?.("TOKEN_REFRESHED", { user: { id: "same-user" }, access_token: "rotated" });

    expect(queryClient.clear).not.toHaveBeenCalled();
  });

  it("clears the query cache when SIGNED_IN brings a different user id", async () => {
    let capturedCallback: ((event: string, session: unknown) => void) | undefined;
    authMocks.onAuthStateChange.mockImplementation((cb: (event: string, session: unknown) => void) => {
      capturedCallback = cb;
      return { data: { subscription: { unsubscribe: authMocks.unsubscribe } } };
    });
    authMocks.getSession.mockResolvedValue({ data: { session: { user: { id: "user-a" }, access_token: "a" } } });
    const queryClient = { clear: vi.fn() };

    render(
      <AuthProvider queryClient={queryClient as unknown as import("@tanstack/react-query").QueryClient}>
        <AuthProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(authMocks.onAuthStateChange).toHaveBeenCalled());

    // Baseline event so the listener has a known prior identity before the under-test
    // user-switch event fires. Without this, the cold-mount guard would skip the wipe.
    capturedCallback?.("INITIAL_SESSION", { user: { id: "user-a" }, access_token: "a" });

    capturedCallback?.("SIGNED_IN", { user: { id: "user-b" }, access_token: "b" });

    expect(queryClient.clear).toHaveBeenCalledTimes(1);
  });

  it("does NOT clear the query cache on the first event of the page lifecycle (cold-mount guard)", async () => {
    // Regression for https://github.com/.../#cold-mount-stale-render: the first
    // onAuthStateChange event after mount must NOT wipe the cache, because in-flight
    // queries registered during initial render would otherwise be orphaned.
    let capturedCallback: ((event: string, session: unknown) => void) | undefined;
    authMocks.onAuthStateChange.mockImplementation((cb: (event: string, session: unknown) => void) => {
      capturedCallback = cb;
      return { data: { subscription: { unsubscribe: authMocks.unsubscribe } } };
    });
    const queryClient = { clear: vi.fn() };

    render(
      <AuthProvider queryClient={queryClient as unknown as import("@tanstack/react-query").QueryClient}>
        <AuthProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(authMocks.onAuthStateChange).toHaveBeenCalled());

    // Simulate a session restored from localStorage on cold mount: Supabase emits
    // SIGNED_IN (older minors) or INITIAL_SESSION (>= 2.27) with the persisted user.
    capturedCallback?.("SIGNED_IN", { user: { id: "user-a" }, access_token: "a" });

    expect(queryClient.clear).not.toHaveBeenCalled();
  });

  it("does NOT clear the query cache when SIGNED_IN keeps the same user id", async () => {
    let capturedCallback: ((event: string, session: unknown) => void) | undefined;
    authMocks.onAuthStateChange.mockImplementation((cb: (event: string, session: unknown) => void) => {
      capturedCallback = cb;
      return { data: { subscription: { unsubscribe: authMocks.unsubscribe } } };
    });
    authMocks.getSession.mockResolvedValue({ data: { session: { user: { id: "user-a" }, access_token: "a" } } });
    const queryClient = { clear: vi.fn() };

    render(
      <AuthProvider queryClient={queryClient as unknown as import("@tanstack/react-query").QueryClient}>
        <AuthProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(authMocks.getSession).toHaveBeenCalled());

    capturedCallback?.("SIGNED_IN", { user: { id: "user-a" }, access_token: "a2" });

    expect(queryClient.clear).not.toHaveBeenCalled();
  });
});
