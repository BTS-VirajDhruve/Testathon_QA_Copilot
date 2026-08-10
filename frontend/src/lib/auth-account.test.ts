import { describe, expect, it } from "vitest";
import {
  resolveAccountErrorMessage,
  validateAccountPasswordInput,
  validateAccountProfileInput,
} from "@/lib/auth-account";
import { ApiError } from "@/lib/api";

describe("auth account helpers", () => {
  it("validates profile form values", () => {
    expect(validateAccountProfileInput({ name: "", email: "qa@example.com" })).toContain("Name");
    expect(validateAccountProfileInput({ name: "QA", email: "" })).toContain("Email");
    expect(validateAccountProfileInput({ name: "QA", email: "bad-email" })).toContain("invalid");
    expect(validateAccountProfileInput({ name: "QA User", email: "qa@example.com" })).toBeNull();
  });

  it("validates password-change form values", () => {
    expect(
      validateAccountPasswordInput({
        currentPassword: "short",
        newPassword: "NewPass123!",
        confirmPassword: "NewPass123!",
      })
    ).toContain("Current password");
    expect(
      validateAccountPasswordInput({
        currentPassword: "CurrentPass123!",
        newPassword: "short",
        confirmPassword: "short",
      })
    ).toContain("New password");
    expect(
      validateAccountPasswordInput({
        currentPassword: "CurrentPass123!",
        newPassword: "CurrentPass123!",
        confirmPassword: "CurrentPass123!",
      })
    ).toContain("different");
    expect(
      validateAccountPasswordInput({
        currentPassword: "CurrentPass123!",
        newPassword: "NewPass123!",
        confirmPassword: "Mismatch123!",
      })
    ).toContain("do not match");
    expect(
      validateAccountPasswordInput({
        currentPassword: "CurrentPass123!",
        newPassword: "NewPass123!",
        confirmPassword: "NewPass123!",
      })
    ).toBeNull();
  });

  it("maps API and runtime errors", () => {
    expect(resolveAccountErrorMessage(new ApiError("Conflict", 409), "fallback")).toBe("Conflict");
    expect(resolveAccountErrorMessage(new Error("boom"), "fallback")).toBe("boom");
    expect(resolveAccountErrorMessage("x", "fallback")).toBe("fallback");
  });
});
