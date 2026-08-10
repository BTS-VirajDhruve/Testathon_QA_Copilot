export const USER_ADMIN_ROLES = ["systemadmin", "admin"] as const;
export const ALL_USER_ROLES = ["systemadmin", "admin", "qa"] as const;

export type UserRole = (typeof ALL_USER_ROLES)[number];

export type UserAdminRecord = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  isActive: boolean;
  createdAt?: string;
  updatedAt?: string;
  deletedAt?: string | null;
};

export type UserAdminCreateInput = {
  name: string;
  email: string;
  password: string;
  role: UserRole;
  isActive: boolean;
};

export type UserAdminUpdateInput = {
  name?: string;
  role?: UserRole;
  isActive?: boolean;
  password?: string;
};

export function normalizeRole(value: unknown): UserRole {
  if (value === "systemadmin" || value === "admin") return value;
  return "qa";
}

export function canManageUsers(role: string | null | undefined): boolean {
  if (typeof role !== "string") return false;
  const normalized = role.trim().toLowerCase();
  return normalized === "systemadmin" || normalized === "admin";
}

export function validateUserCreateInput(input: UserAdminCreateInput): string[] {
  const errors: string[] = [];
  if (!input.name.trim()) {
    errors.push("Name is required.");
  }
  const email = input.email.trim();
  if (!email) {
    errors.push("Email is required.");
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    errors.push("Email must be valid.");
  }
  if (!input.password || input.password.length < 8) {
    errors.push("Password must be at least 8 characters.");
  }
  if (!ALL_USER_ROLES.includes(input.role)) {
    errors.push("Role is invalid.");
  }
  return errors;
}

export function validateUserUpdateInput(input: UserAdminUpdateInput): string[] {
  const errors: string[] = [];
  if (input.name !== undefined && !input.name.trim()) {
    errors.push("Name cannot be empty.");
  }
  if (input.password !== undefined && input.password.length > 0 && input.password.length < 8) {
    errors.push("Password must be at least 8 characters.");
  }
  if (input.role !== undefined && !ALL_USER_ROLES.includes(input.role)) {
    errors.push("Role is invalid.");
  }
  return errors;
}
