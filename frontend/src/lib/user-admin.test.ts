import { describe, expect, it } from "vitest";
import {
  canManageUsers,
  normalizeRole,
  validateUserCreateInput,
  validateUserInviteInput,
  validateUserUpdateInput,
} from "./user-admin";

describe("user admin role rules", () => {
  it("allows only systemadmin/admin to manage users", () => {
    expect(canManageUsers("systemadmin")).toBe(true);
    expect(canManageUsers("admin")).toBe(true);
    expect(canManageUsers("ADMIN")).toBe(true);
    expect(canManageUsers("qa")).toBe(false);
    expect(canManageUsers("owner")).toBe(false);
    expect(canManageUsers(undefined)).toBe(false);
  });

  it("normalizes unknown or missing roles to qa", () => {
    expect(normalizeRole("systemadmin")).toBe("systemadmin");
    expect(normalizeRole("admin")).toBe("admin");
    expect(normalizeRole("qa")).toBe("qa");
    expect(normalizeRole("owner")).toBe("qa");
    expect(normalizeRole(undefined)).toBe("qa");
  });
});

describe("user admin validation", () => {
  it("validates create input fields", () => {
    expect(
      validateUserCreateInput({
        name: "",
        email: "invalid-email",
        password: "123",
        role: "qa",
        isActive: true,
      })
    ).toEqual([
      "Name is required.",
      "Email must be valid.",
      "Password must be at least 8 characters.",
    ]);
  });

  it("validates update input fields", () => {
    expect(
      validateUserUpdateInput({
        name: "   ",
        password: "short",
      })
    ).toEqual(["Name cannot be empty.", "Password must be at least 8 characters."]);
  });

  it("validates invite input fields", () => {
    expect(
      validateUserInviteInput({
        name: "",
        email: "invalid-email",
        role: "qa",
      })
    ).toEqual(["Name is required.", "Email must be valid."]);
  });
});
