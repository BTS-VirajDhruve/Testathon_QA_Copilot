import { describe, expect, it } from "vitest";
import { USERS_ACCESS_NOTICE } from "@/lib/auth-routing";
import { resolveUsersRouteAccess } from "@/lib/users-access";

describe("users route access guard", () => {
  it("allows only systemadmin/admin when authenticated", () => {
    expect(
      resolveUsersRouteAccess({
        authStatus: "authenticated",
        role: "systemadmin",
        pathname: "/users",
        search: "",
      }).state
    ).toBe("authorized");
    expect(
      resolveUsersRouteAccess({
        authStatus: "authenticated",
        role: "admin",
        pathname: "/users",
        search: "",
      }).state
    ).toBe("authorized");
    expect(
      resolveUsersRouteAccess({
        authStatus: "authenticated",
        role: "qa",
        pathname: "/users",
        search: "",
      }).state
    ).toBe("unauthorized");
  });

  it("redirects unauthenticated users to login with encoded return URL", () => {
    const access = resolveUsersRouteAccess({
      authStatus: "unauthenticated",
      role: null,
      pathname: "/users",
      search: "?tab=active",
    });
    expect(access.state).toBe("unauthenticated");
    expect(access.redirectHref).toBe("/login?redirect=%2Fusers%3Ftab%3Dactive");
    expect(access.message).toContain("Redirecting to login");
  });

  it("waits while session auth is still loading", () => {
    const access = resolveUsersRouteAccess({
      authStatus: "loading",
      role: null,
      pathname: "/users",
      search: "?tab=active",
    });
    expect(access.state).toBe("loading");
    expect(access.redirectHref).toBeNull();
    expect(access.canManage).toBe(false);
    expect(access.message).toContain("Checking session");
  });

  it("redirects unauthorized users to workspace with explicit notice", () => {
    const access = resolveUsersRouteAccess({
      authStatus: "authenticated",
      role: "guest",
      pathname: "/users",
      search: "",
    });
    expect(access.state).toBe("unauthorized");
    expect(access.redirectHref).toBe(`/?notice=${encodeURIComponent(USERS_ACCESS_NOTICE)}`);
    expect(access.message).toContain("Access restricted");
  });

  it("denies missing or unknown roles by default", () => {
    const unknownRole = resolveUsersRouteAccess({
      authStatus: "authenticated",
      role: undefined,
      pathname: "/users",
      search: "",
    });
    expect(unknownRole.state).toBe("unauthorized");
  });
});
