import { describe, expect, it } from "vitest";
import {
  buildLoginHref,
  buildUsersAccessDeniedHref,
  resolvePostLoginRedirect,
  USERS_ACCESS_NOTICE,
} from "./auth-routing";

describe("auth routing helpers", () => {
  it("builds login href with encoded redirect", () => {
    expect(buildLoginHref("/", "")).toBe("/login?redirect=%2F");
    expect(buildLoginHref("/users", "?tab=active")).toBe(
      "/login?redirect=%2Fusers%3Ftab%3Dactive"
    );
    expect(buildLoginHref("/", "?view=results&section=tests")).toBe(
      "/login?redirect=%2F%3Fview%3Dresults%26section%3Dtests"
    );
  });

  it("accepts only local redirect paths", () => {
    expect(resolvePostLoginRedirect("/?view=flow")).toBe("/?view=flow");
    expect(resolvePostLoginRedirect("users")).toBe("/");
    expect(resolvePostLoginRedirect("https://evil.example.com")).toBe("/");
    expect(resolvePostLoginRedirect("//evil.example.com/path")).toBe("/");
  });

  it("blocks redirecting back to login route", () => {
    expect(resolvePostLoginRedirect("/login")).toBe("/");
    expect(resolvePostLoginRedirect("/login?redirect=%2F")).toBe("/");
  });

  it("builds a deterministic access-denied redirect", () => {
    expect(buildUsersAccessDeniedHref()).toBe(`/?notice=${encodeURIComponent(USERS_ACCESS_NOTICE)}`);
  });
});
