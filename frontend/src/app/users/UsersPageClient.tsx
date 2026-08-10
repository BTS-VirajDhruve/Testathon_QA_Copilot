"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Loader2, ShieldAlert, Sparkles, Trash2, UserPlus, UserX } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  ALL_USER_ROLES,
  validateUserInviteInput,
  validateUserUpdateInput,
  type UserInviteInput,
  type UserAdminRecord,
  type UserAdminUpdateInput,
  type UserRole,
} from "@/lib/user-admin";
import { resolveUsersRouteAccess } from "@/lib/users-access";
import { AuthSessionShimmer } from "@/components/AuthSessionShimmer";

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}

function formatDate(value: string | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

const defaultCreateState: UserInviteInput = {
  name: "",
  email: "",
  role: "qa",
};

const defaultEditState: UserAdminUpdateInput = {
  name: "",
  role: "qa",
  isActive: true,
  password: "",
};

export function UsersPageClient() {
  const router = useRouter();
  const pathname = usePathname() || "/users";
  const { status: authStatus, session } = useAuth();
  const access = resolveUsersRouteAccess({
    authStatus,
    role: session.user?.role,
    pathname,
    search: typeof window === "undefined" ? "" : window.location.search,
  });
  const allowManage = access.canManage;

  const [items, setItems] = useState<UserAdminRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<"all" | UserRole>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "inactive">("all");
  const [createForm, setCreateForm] = useState<UserInviteInput>(defaultCreateState);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<UserAdminUpdateInput>(defaultEditState);

  const loadUsers = useCallback(async () => {
    if (!allowManage) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await api.listUsers();
      setItems(rows);
    } catch (loadError) {
      setError(getErrorMessage(loadError, "Failed to load users."));
    } finally {
      setLoading(false);
    }
  }, [allowManage]);

  useEffect(() => {
    if (authStatus === "authenticated") {
      void loadUsers();
    }
  }, [authStatus, loadUsers]);

  useEffect(() => {
    if (!access.redirectHref) return;
    router.replace(access.redirectHref);
  }, [access.redirectHref, router]);

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      const query = search.trim().toLowerCase();
      const matchesSearch =
        !query ||
        item.name.toLowerCase().includes(query) ||
        item.email.toLowerCase().includes(query) ||
        item.role.toLowerCase().includes(query);
      const matchesRole = roleFilter === "all" ? true : item.role === roleFilter;
      const matchesStatus =
        statusFilter === "all"
          ? true
          : statusFilter === "active"
            ? item.isActive
            : !item.isActive;
      return matchesSearch && matchesRole && matchesStatus;
    });
  }, [items, roleFilter, search, statusFilter]);

  async function handleInviteUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!allowManage || saving) return;
    const form = {
      ...createForm,
      name: createForm.name.trim(),
      email: createForm.email.trim().toLowerCase(),
    };
    const validationErrors = validateUserInviteInput(form);
    if (validationErrors.length > 0) {
      setError(validationErrors.join(" "));
      return;
    }

    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const invited = await api.inviteUser(form);
      setCreateForm(defaultCreateState);
      setSuccess(invited.message);
      await loadUsers();
    } catch (inviteError) {
      setError(getErrorMessage(inviteError, "Failed to send user invitation."));
    } finally {
      setSaving(false);
    }
  }

  function beginEdit(user: UserAdminRecord) {
    setEditingUserId(user.id);
    setEditForm({
      name: user.name,
      role: user.role,
      isActive: user.isActive,
      password: "",
    });
  }

  async function handleUpdateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!allowManage || !editingUserId || saving) return;
    const payload: UserAdminUpdateInput = {
      name: editForm.name?.trim(),
      role: editForm.role,
      isActive: editForm.isActive,
      password: editForm.password?.trim() || undefined,
    };
    const validationErrors = validateUserUpdateInput(payload);
    if (validationErrors.length > 0) {
      setError(validationErrors.join(" "));
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const updated = await api.updateUser(editingUserId, payload);
      setItems((prev) => prev.map((row) => (row.id === updated.id ? updated : row)));
      setEditingUserId(null);
      setSuccess(`Updated user ${updated.email}.`);
    } catch (updateError) {
      setError(getErrorMessage(updateError, "Failed to update user."));
    } finally {
      setSaving(false);
    }
  }

  async function handleDeactivate(user: UserAdminRecord) {
    if (!allowManage || saving) return;
    if (!window.confirm(`Deactivate ${user.email}?`)) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const updated = await api.deactivateUser(user.id);
      setItems((prev) => prev.map((row) => (row.id === updated.id ? updated : row)));
      setSuccess(`Deactivated user ${user.email}.`);
    } catch (deactivateError) {
      setError(getErrorMessage(deactivateError, "Failed to deactivate user."));
    } finally {
      setSaving(false);
    }
  }

  async function handleSoftDelete(user: UserAdminRecord) {
    if (!allowManage || saving) return;
    if (!window.confirm(`Soft-delete ${user.email}?`)) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await api.softDeleteUser(user.id);
      setItems((prev) => prev.filter((row) => row.id !== user.id));
      setSuccess(`Soft-deleted user ${user.email}.`);
    } catch (deleteError) {
      setError(getErrorMessage(deleteError, "Failed to delete user."));
    } finally {
      setSaving(false);
    }
  }

  if (access.state === "loading") {
    return <AuthSessionShimmer />;
  }

  if (access.state === "unauthenticated") {
    return (
      <div className="min-h-screen bg-hero-wash">
        <header className="sticky top-0 z-30 border-b border-ink-700/10 bg-mist-50/80 backdrop-blur-md">
          <div className="flex w-full items-center justify-between gap-3 px-3 py-3 sm:px-4 lg:px-5">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ink-900 text-brass-400">
                <Sparkles className="h-5 w-5" />
              </div>
              <div>
                <div className="font-display text-lg leading-none tracking-tight">QA Copilot</div>
                <div className="mt-1 text-[11px] uppercase tracking-[0.14em] text-ink-600/60">
                  User Management
                </div>
              </div>
            </div>
          </div>
        </header>
        <main className="flex w-full items-center justify-center px-3 py-10 sm:px-4 lg:px-5">
          <div className="panel flex items-center gap-3 px-6 py-5 text-sm text-ink-700/80">
            <Loader2 className="h-5 w-5 animate-spin text-pine-700" />
            {access.message}
          </div>
        </main>
      </div>
    );
  }

  if (access.state === "unauthorized") {
    return (
      <div className="min-h-screen bg-hero-wash">
        <header className="sticky top-0 z-30 border-b border-ink-700/10 bg-mist-50/80 backdrop-blur-md">
          <div className="flex w-full items-center justify-between gap-3 px-3 py-3 sm:px-4 lg:px-5">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ink-900 text-brass-400">
                <Sparkles className="h-5 w-5" />
              </div>
              <div>
                <div className="font-display text-lg leading-none tracking-tight">QA Copilot</div>
                <div className="mt-1 text-[11px] uppercase tracking-[0.14em] text-ink-600/60">
                  User Management
                </div>
              </div>
            </div>
            <Link href="/" className="btn-secondary">
              <ArrowLeft className="h-4 w-4" /> Back to workspace
            </Link>
          </div>
        </header>
        <main className="w-full px-3 py-8 sm:px-4 lg:px-5">
          <div className="panel p-6">
            <div className="flex items-center gap-2 text-signal-high">
              <ShieldAlert className="h-5 w-5" />
              <h1 className="font-display text-2xl text-ink-900">Access restricted</h1>
            </div>
            <p className="mt-3 text-sm text-ink-700/80">
              Your role does not have permission to manage users.
            </p>
            <p className="mt-2 text-sm text-ink-700/80">{access.message}</p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-hero-wash">
      <header className="sticky top-0 z-30 border-b border-ink-700/10 bg-mist-50/80 backdrop-blur-md">
        <div className="flex w-full items-center justify-between gap-3 px-3 py-3 sm:px-4 lg:px-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ink-900 text-brass-400">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <div className="font-display text-lg leading-none tracking-tight">QA Copilot</div>
              <div className="mt-1 text-[11px] uppercase tracking-[0.14em] text-ink-600/60">
                User Management
              </div>
            </div>
          </div>
          <Link href="/" className="btn-secondary">
            <ArrowLeft className="h-4 w-4" /> Back to workspace
          </Link>
        </div>
      </header>
      <main className="w-full space-y-5 px-3 py-8 sm:px-4 lg:px-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-display text-3xl text-ink-900">User Management</h1>
            <p className="mt-1 text-sm text-ink-700/70">
              Invite, update, deactivate, and soft-delete users with role-aware controls.
            </p>
          </div>
        </div>

        {(error || success) && (
          <div
            className={`rounded-2xl border px-4 py-3 text-sm ${
              error
                ? "border-signal-high/30 bg-signal-high/10 text-signal-high"
                : "border-pine-700/20 bg-pine-700/10 text-pine-800"
            }`}
          >
            {error || success}
          </div>
        )}

        <section className="panel p-5">
          <h2 className="font-display text-xl text-ink-900">Invite user</h2>
          <form className="mt-4 grid gap-3 md:grid-cols-2" onSubmit={handleInviteUser}>
            <input
              className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm"
              placeholder="Full name"
              value={createForm.name}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, name: event.target.value }))}
            />
            <input
              type="email"
              className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm"
              placeholder="Email"
              value={createForm.email}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, email: event.target.value }))}
            />
            <select
              className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm"
              value={createForm.role}
              onChange={(event) =>
                setCreateForm((prev) => ({ ...prev, role: event.target.value as UserRole }))
              }
            >
              {ALL_USER_ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
            <div className="md:col-span-2">
              <button className="btn-primary" type="submit" disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
                Send invite
              </button>
            </div>
          </form>
        </section>

        <section className="panel p-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <h2 className="font-display text-xl text-ink-900">Users</h2>
            <div className="flex flex-wrap gap-2">
              <input
                className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm"
                placeholder="Search by name, email, role"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <select
                className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm"
                value={roleFilter}
                onChange={(event) => setRoleFilter(event.target.value as "all" | UserRole)}
              >
                <option value="all">All roles</option>
                {ALL_USER_ROLES.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
              <select
                className="rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm"
                value={statusFilter}
                onChange={(event) =>
                  setStatusFilter(event.target.value as "all" | "active" | "inactive")
                }
              >
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
              <button className="btn-secondary" onClick={() => void loadUsers()} disabled={loading || saving}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Refresh"}
              </button>
            </div>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead>
                <tr className="border-b border-ink-700/10 text-ink-600">
                  <th className="px-2 py-2 font-medium">Name</th>
                  <th className="px-2 py-2 font-medium">Email</th>
                  <th className="px-2 py-2 font-medium">Role</th>
                  <th className="px-2 py-2 font-medium">Status</th>
                  <th className="px-2 py-2 font-medium">Updated</th>
                  <th className="px-2 py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((user) => {
                  const editing = editingUserId === user.id;
                  return (
                    <tr key={user.id} className="border-b border-ink-700/5 align-top">
                      <td className="px-2 py-3">
                        {editing ? (
                          <input
                            className="w-full rounded-lg border border-ink-200 px-2 py-1"
                            value={editForm.name || ""}
                            onChange={(event) =>
                              setEditForm((prev) => ({ ...prev, name: event.target.value }))
                            }
                          />
                        ) : (
                          user.name
                        )}
                      </td>
                      <td className="px-2 py-3">{user.email}</td>
                      <td className="px-2 py-3">
                        {editing ? (
                          <select
                            className="w-full rounded-lg border border-ink-200 px-2 py-1"
                            value={editForm.role || "qa"}
                            onChange={(event) =>
                              setEditForm((prev) => ({ ...prev, role: event.target.value as UserRole }))
                            }
                          >
                            {ALL_USER_ROLES.map((role) => (
                              <option key={role} value={role}>
                                {role}
                              </option>
                            ))}
                          </select>
                        ) : (
                          user.role
                        )}
                      </td>
                      <td className="px-2 py-3">
                        {editing ? (
                          <label className="inline-flex items-center gap-1">
                            <input
                              type="checkbox"
                              checked={Boolean(editForm.isActive)}
                              onChange={(event) =>
                                setEditForm((prev) => ({ ...prev, isActive: event.target.checked }))
                              }
                            />
                            Active
                          </label>
                        ) : user.isActive ? (
                          "Active"
                        ) : (
                          "Inactive"
                        )}
                      </td>
                      <td className="px-2 py-3 text-ink-600">{formatDate(user.updatedAt)}</td>
                      <td className="px-2 py-3">
                        {editing ? (
                          <form className="flex flex-wrap items-center gap-2" onSubmit={handleUpdateUser}>
                            <input
                              type="password"
                              className="rounded-lg border border-ink-200 px-2 py-1"
                              placeholder="New password (optional)"
                              value={editForm.password || ""}
                              onChange={(event) =>
                                setEditForm((prev) => ({ ...prev, password: event.target.value }))
                              }
                            />
                            <button className="btn-primary" type="submit" disabled={saving}>
                              Save
                            </button>
                            <button
                              className="btn-secondary"
                              type="button"
                              disabled={saving}
                              onClick={() => setEditingUserId(null)}
                            >
                              Cancel
                            </button>
                          </form>
                        ) : (
                          <div className="flex flex-wrap gap-2">
                            <button
                              className="btn-secondary"
                              type="button"
                              disabled={saving}
                              onClick={() => beginEdit(user)}
                            >
                              Edit
                            </button>
                            <button
                              className="btn-secondary"
                              type="button"
                              disabled={saving || !user.isActive}
                              onClick={() => void handleDeactivate(user)}
                            >
                              <UserX className="h-4 w-4" /> Deactivate
                            </button>
                            <button
                              className="btn-danger"
                              type="button"
                              disabled={saving}
                              onClick={() => void handleSoftDelete(user)}
                            >
                              <Trash2 className="h-4 w-4" /> Delete
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {!filteredItems.length && !loading && (
                  <tr>
                    <td className="px-2 py-5 text-sm text-ink-600" colSpan={6}>
                      No users found for the selected filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
