"use client";

import type { LucideIcon } from "lucide-react";
import clsx from "clsx";
import {
  NAV_GROUPS,
  type NavGroupId,
  type PrimaryAppView,
} from "@/lib/workflow";

export function Sidebar({
  items,
  view,
  onChange,
}: {
  items: { id: PrimaryAppView; label: string; icon: LucideIcon; group: NavGroupId }[];
  view: PrimaryAppView;
  onChange: (v: PrimaryAppView) => void;
}) {
  return (
    <aside className="panel sticky top-5 hidden h-[calc(100vh-6.5rem)] w-60 shrink-0 overflow-auto p-3 lg:block">
      <div className="px-3 pb-3 pt-2">
        <div className="label">Workspace</div>
        <p className="mt-1 text-[11px] leading-relaxed text-ink-600/65">
          Setup → Analyze → Observe
        </p>
      </div>
      <nav className="space-y-4" aria-label="Primary">
        {NAV_GROUPS.map((group) => {
          const groupItems = items.filter((item) => item.group === group.id);
          if (!groupItems.length) return null;
          return (
            <div key={group.id}>
              <div className="px-3 pb-1 text-[10px] font-medium uppercase tracking-[0.16em] text-ink-600/50">
                {group.label}
              </div>
              <div className="space-y-1">
                {groupItems.map((item) => {
                  const Icon = item.icon;
                  const isActive = view === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => onChange(item.id)}
                      aria-current={isActive ? "page" : undefined}
                      className={clsx(
                        "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition",
                        isActive
                          ? "bg-ink-900 text-mist-50"
                          : "text-ink-800 hover:bg-mist-100"
                      )}
                    >
                      <Icon className="h-4 w-4 shrink-0 opacity-80" />
                      <span>{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
