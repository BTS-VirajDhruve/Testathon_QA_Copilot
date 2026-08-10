import { buildLoginHref, buildUsersAccessDeniedHref } from "@/lib/auth-routing";
import { canManageUsers } from "@/lib/user-admin";

export type ClientAuthStatus = "loading" | "authenticated" | "unauthenticated";

export type UsersRouteAccess =
  | {
      state: "authorized";
      canManage: true;
      message: null;
      redirectHref: null;
    }
  | {
      state: "unauthenticated";
      canManage: false;
      message: "Redirecting to login...";
      redirectHref: string;
    }
  | {
      state: "unauthorized";
      canManage: false;
      message: "Access restricted. Redirecting to workspace...";
      redirectHref: string;
    };

export function resolveUsersRouteAccess(params: {
  authStatus: ClientAuthStatus;
  role: string | null | undefined;
  pathname: string;
  search: string;
}): UsersRouteAccess {
  const { authStatus, role, pathname, search } = params;
  if (authStatus !== "authenticated") {
    return {
      state: "unauthenticated",
      canManage: false,
      message: "Redirecting to login...",
      redirectHref: buildLoginHref(pathname, search),
    };
  }
  if (!canManageUsers(role)) {
    return {
      state: "unauthorized",
      canManage: false,
      message: "Access restricted. Redirecting to workspace...",
      redirectHref: buildUsersAccessDeniedHref(),
    };
  }
  return {
    state: "authorized",
    canManage: true,
    message: null,
    redirectHref: null,
  };
}
