import { ApiError } from "@/lib/api";

export type AccountProfileInput = {
  name: string;
  email: string;
};

export type AccountPasswordInput = {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
};

export function validateAccountProfileInput(input: AccountProfileInput): string | null {
  const name = input.name.trim();
  const email = input.email.trim().toLowerCase();
  if (!name) return "Name is required.";
  if (!email) return "Email is required.";
  if (!email.includes("@")) return "Email format looks invalid.";
  return null;
}

export function validateAccountPasswordInput(input: AccountPasswordInput): string | null {
  if (input.currentPassword.length < 8) {
    return "Current password must be at least 8 characters.";
  }
  if (input.newPassword.length < 8) {
    return "New password must be at least 8 characters.";
  }
  if (input.currentPassword === input.newPassword) {
    return "New password must be different from current password.";
  }
  if (input.newPassword !== input.confirmPassword) {
    return "New password and confirmation do not match.";
  }
  return null;
}

export function resolveAccountErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}
