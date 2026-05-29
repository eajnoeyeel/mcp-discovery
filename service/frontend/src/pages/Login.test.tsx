import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigate = vi.fn();
const signInWithGoogle = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    signInWithGoogle,
  }),
}));

import Login from "./Login";

describe("Login page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWithGoogle.mockResolvedValue({ error: null });
  });

  it("shows only Google sign-in and forwards the redirect target", async () => {
    render(
      <MemoryRouter initialEntries={["/login?redirect=%2Fdashboard%2Ftools%2Fsrv%3A%3Alookup"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: /continue with google/i })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Email")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Password")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /continue with google/i }));

    await waitFor(() => {
      expect(signInWithGoogle).toHaveBeenCalledWith("/dashboard/tools/srv::lookup");
    });
    expect(navigate).not.toHaveBeenCalled();
  });
});
