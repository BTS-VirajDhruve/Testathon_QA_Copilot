export function buildLoginHref(pathname: string, search = ""): string {
  const target = `${pathname}${search || ""}`;
  return `/login?redirect=${encodeURIComponent(target)}`;
}

export const USERS_ACCESS_NOTICE = "users-access-denied";

export function buildUsersAccessDeniedHref(): string {
  return `/?notice=${encodeURIComponent(USERS_ACCESS_NOTICE)}`;
}

export function resolvePostLoginRedirect(redirect: string | null | undefined): string {
  if (!redirect) return "/";
  if (!redirect.startsWith("/") || redirect.startsWith("//")) return "/";
  if (redirect.startsWith("/login")) return "/";
  return redirect;
}
