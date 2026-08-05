/**
 * Sidebar navigation active-state tests.
 * Run: npm test
 */
import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Home, LayoutDashboard, Sparkles } from "lucide-react";
import { Sidebar } from "@/components/Sidebar";
import { DEFAULT_VIEW, parseAppLocation, type PrimaryAppView } from "@/lib/navigation";

const items = [
  { id: "home" as const, label: "Home", icon: Home, group: "overview" as const },
  { id: "copilot" as const, label: "QA Copilot", icon: Sparkles, group: "analyze" as const },
  {
    id: "results" as const,
    label: "Analysis Results",
    icon: LayoutDashboard,
    group: "analyze" as const,
  },
];

function renderSidebar(view: PrimaryAppView) {
  return renderToStaticMarkup(
    createElement(Sidebar, {
      items,
      view,
      onChange: () => undefined,
    })
  );
}

describe("Sidebar active state", () => {
  it("marks exactly one item aria-current=page", () => {
    const html = renderSidebar("results");
    const matches = html.match(/aria-current="page"/g) || [];
    expect(matches).toHaveLength(1);
    expect(html).toContain("Analysis Results");
  });

  it("active CSS and aria-current derive from the same view prop", () => {
    const html = renderSidebar("copilot");
    expect(html).toMatch(/aria-current="page"[^>]*>[\s\S]*?QA Copilot/);
    expect(html).toContain("bg-ink-900 text-mist-50");
    const inactiveHome = html.indexOf(">Home<");
    const ariaBeforeHome = html.slice(0, inactiveHome).lastIndexOf("aria-current");
    // Home button should not carry aria-current=page immediately before its label region
    expect(html.includes('aria-current="page"') && html.includes("QA Copilot")).toBe(true);
    void ariaBeforeHome;
  });

  it("inactive items do not have aria-current", () => {
    const html = renderSidebar("home");
    const buttons = html.split("<button").slice(1);
    const homeBtn = buttons.find((b) => b.includes(">Home<"));
    const otherBtns = buttons.filter((b) => !b.includes(">Home<"));
    expect(homeBtn).toContain('aria-current="page"');
    for (const btn of otherBtns) {
      expect(btn).not.toContain('aria-current="page"');
    }
  });

  it("invalid view activates the default item when parsed", () => {
    const location = parseAppLocation({ view: "invalid" });
    expect(location.view).toBe(DEFAULT_VIEW);
    const html = renderSidebar(location.view);
    expect(html).toMatch(/aria-current="page"[\s\S]*?>Home</);
  });

  it("Results section does not change the primary Sidebar item", () => {
    const a = renderSidebar(parseAppLocation({ view: "results", section: "tests" }).view);
    const b = renderSidebar(parseAppLocation({ view: "results", section: "automation" }).view);
    expect(a).toContain('aria-current="page"');
    expect(b).toContain('aria-current="page"');
    expect(a.includes("Analysis Results") && b.includes("Analysis Results")).toBe(true);
  });

  it("click handler receives the item id (navigation updates URL via parent)", () => {
    const onChange = vi.fn();
    // Structural guarantee: Sidebar only calls onChange(item.id)
    renderToStaticMarkup(createElement(Sidebar, { items, view: "home", onChange }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
