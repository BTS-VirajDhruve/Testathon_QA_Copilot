import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TopBar } from "@/components/TopBar";

describe("TopBar user dropdown", () => {
  it("renders user menu entries when opened", () => {
    const html = renderToStaticMarkup(
      createElement(TopBar, {
        projects: [],
        projectId: "",
        onProjectChange: () => undefined,
        onCreateProject: () => undefined,
        onDeleteProject: () => Promise.resolve(),
        status: "Connected",
        busy: false,
        health: null,
        userDisplayName: "QA User",
        userInitials: "QU",
        defaultUserMenuOpen: true,
      })
    );
    expect(html).toContain("View/Edit Profile");
    expect(html).toContain("Change Password");
    expect(html).toContain("Logout");
    expect(html).toContain("QA User");
  });

  it("shows Manage Users only when explicitly allowed", () => {
    const withManage = renderToStaticMarkup(
      createElement(TopBar, {
        projects: [],
        projectId: "",
        onProjectChange: () => undefined,
        onCreateProject: () => undefined,
        onDeleteProject: () => Promise.resolve(),
        status: "Connected",
        busy: false,
        health: null,
        canManageUsers: true,
        onManageUsers: () => undefined,
      })
    );
    const withoutManage = renderToStaticMarkup(
      createElement(TopBar, {
        projects: [],
        projectId: "",
        onProjectChange: () => undefined,
        onCreateProject: () => undefined,
        onDeleteProject: () => Promise.resolve(),
        status: "Connected",
        busy: false,
        health: null,
        canManageUsers: false,
        onManageUsers: () => undefined,
      })
    );

    expect(withManage).toContain("Manage Users");
    expect(withoutManage).not.toContain("Manage Users");
  });
});
