import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import {
  getResetPasswordErrorMessage,
  normalizeForgotPasswordEmail,
  resolveResetToken,
  validateForgotPasswordEmail,
  validateResetPasswordForm,
} from "@/lib/auth-password";

describe("auth password helpers", () => {
  it("normalizes forgot-password email input", () => {
    expect(normalizeForgotPasswordEmail("  QA@Example.COM  ")).toBe("qa@example.com");
  });

  it("validates forgot-password email requirement", () => {
    expect(validateForgotPasswordEmail("   ")).toBe("Email is required.");
    expect(validateForgotPasswordEmail("qa@example.com")).toBeNull();
  });

  it("resolves reset token from query parameter", () => {
    expect(resolveResetToken("  abc-token  ")).toBe("abc-token");
    expect(resolveResetToken(null)).toBe("");
  });

  it("validates reset-password form constraints", () => {
    expect(
      validateResetPasswordForm({
        token: "",
        newPassword: "Password123!",
        confirmPassword: "Password123!",
      })
    ).toContain("Reset token is missing");

    expect(
      validateResetPasswordForm({
        token: "token-12345678901234567890",
        newPassword: "short",
        confirmPassword: "short",
      })
    ).toContain("at least 8 characters");

    expect(
      validateResetPasswordForm({
        token: "token-12345678901234567890",
        newPassword: "Password123!",
        confirmPassword: "Mismatch123!",
      })
    ).toContain("do not match");

    expect(
      validateResetPasswordForm({
        token: "token-12345678901234567890",
        newPassword: "Password123!",
        confirmPassword: "Password123!",
      })
    ).toBeNull();
  });

  it("maps invalid token API errors to a user-friendly reset message", () => {
    const message = getResetPasswordErrorMessage(
      new ApiError("Invalid or expired reset token", 400)
    );
    expect(message).toContain("invalid or expired");
  });
});
