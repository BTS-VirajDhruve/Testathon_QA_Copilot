import { ApiError } from "@/lib/api";

export const FORGOT_PASSWORD_NEUTRAL_MESSAGE =
  "If an account exists for this email, a reset link has been sent.";

type ResetPasswordFormInput = {
  token: string;
  newPassword: string;
  confirmPassword: string;
};

export function normalizeForgotPasswordEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function validateForgotPasswordEmail(email: string): string | null {
  const normalized = normalizeForgotPasswordEmail(email);
  if (!normalized) return "Email is required.";
  return null;
}

export function resolveResetToken(tokenFromQuery: string | null): string {
  return (tokenFromQuery ?? "").trim();
}

export function validateResetPasswordForm(input: ResetPasswordFormInput): string | null {
  if (!input.token.trim()) {
    return "Reset token is missing. Request a new password reset link.";
  }
  if (input.newPassword.length < 8) {
    return "Password must be at least 8 characters.";
  }
  if (input.newPassword !== input.confirmPassword) {
    return "Passwords do not match.";
  }
  return null;
}

export function getResetPasswordErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 400) {
    return "This reset link is invalid or expired. Request a new link and try again.";
  }
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unable to reset password right now. Please try again.";
}

export function getAcceptInviteErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 400) {
    return "This invite link is invalid or expired. Request a new invitation link.";
  }
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unable to accept invite right now. Please try again.";
}
