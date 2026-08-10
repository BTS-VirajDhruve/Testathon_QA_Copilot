import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UsersPageClient } from "./UsersPageClient";

const authMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  usePathname: () => "/users",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => authMock(),
}));

describe("UsersPageClient access + shell rendering", () => {
  beforeEach(() => {
    authMock.mockReset();
  });

  it("renders session shimmer while auth is loading", () => {
    authMock.mockReturnValue({
      status: "loading",
      session: { user: null },
    });

    const html = renderToStaticMarkup(createElement(UsersPageClient));
    expect(html).toContain("Checking session");
    expect(html).not.toContain("Invite user");
    expect(html).not.toContain("Redirecting to login");
  });

  it("renders restricted panel for unauthorized role", () => {
    authMock.mockReturnValue({
      status: "authenticated",
      session: { user: { role: "qa" } },
    });

    const html = renderToStaticMarkup(createElement(UsersPageClient));
    expect(html).toContain("Access restricted");
    expect(html).toContain("Back to workspace");
    expect(html).toContain("QA Copilot");
    expect(html).not.toContain("Invite user");
  });

  it("renders management sections for admin role in app-like shell", () => {
    authMock.mockReturnValue({
      status: "authenticated",
      session: { user: { role: "admin" } },
    });

    const html = renderToStaticMarkup(createElement(UsersPageClient));
    expect(html).toContain("QA Copilot");
    expect(html).toContain("User Management");
    expect(html).toContain("Invite user");
    expect(html).toContain("panel p-5");
  });
});
