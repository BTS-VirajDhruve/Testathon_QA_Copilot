"use client";

import type { LucideIcon } from "lucide-react";
import type { AppView } from "@/lib/types";
import clsx from "clsx";

export function Sidebar({
  items,
  view,
  onChange,
}: {
  items: { id: AppView; label: string; icon: LucideIcon }[];
  view: AppView;
  onChange: (v: AppView) => void;
}) {
  return (
    <aside className="panel sticky top-5 hidden h-[calc(100vh-6.5rem)] w-60 shrink-0 overflow-auto p-3 lg:block">
      <div className="px-3 pb-3 pt-2">
        <div className="label">Workspace</div>
      </div>
      <nav className="space-y-1">
        {items.map((item) => {
          const Icon = item.icon;
          const active = view === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onChange(item.id)}
              className={clsx(
                "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition",
                active
                  ? "bg-ink-900 text-mist-50"
                  : "text-ink-800 hover:bg-mist-100"
              )}
            >
              <Icon className="h-4 w-4 shrink-0 opacity-80" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}