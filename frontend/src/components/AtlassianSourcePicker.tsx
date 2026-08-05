"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";
import { api } from "@/lib/api";

type Mode = "jira" | "confluence";
type Tab = "projects" | "issues" | "spaces" | "pages";

type SelectedItem = {
  source_type: "jira_issue" | "confluence_page";
  external_id: string;
  external_key?: string;
  container_id?: string;
  container_key?: string;
  title: string;
};

export function AtlassianSourcePicker({
  projectId,
  mode,
  open,
  onClose,
  onImported,
}: {
  projectId: string;
  mode: Mode;
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}) {
  const [status, setStatus] = useState<{
    configured: boolean;
    connected: boolean;
    selected_site_name?: string | null;
    status: string;
    error?: string | null;
  } | null>(null);
  const [sites, setSites] = useState<Array<{ cloud_id: string; name: string; url: string }>>([]);
  const [tab, setTab] = useState<Tab>(mode === "jira" ? "projects" : "spaces");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);
  const [selectedProject, setSelectedProject] = useState<{ id: string; key: string; name: string } | null>(
    null
  );
  const [selectedSpace, setSelectedSpace] = useState<{ id: string; key: string; name: string } | null>(
    null
  );
  const [selected, setSelected] = useState<SelectedItem[]>([]);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    const st = await api.atlassianStatus();
    setStatus(st);
    if (st.connected) {
      try {
        setSites(await api.atlassianSites());
      } catch {
        setSites([]);
      }
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setSelected([]);
    setPreview(null);
    setReport(null);
    setError(null);
    setTab(mode === "jira" ? "projects" : "spaces");
    void refreshStatus();
  }, [open, mode, projectId, refreshStatus]);

  const loadList = useCallback(async () => {
    if (!status?.connected) return;
    setLoading(true);
    setError(null);
    try {
      if (mode === "jira" && tab === "projects") {
        const res = await api.atlassianJiraProjects(query || undefined);
        setItems(res.items || []);
      } else if (mode === "jira" && tab === "issues") {
        if (!selectedProject?.key) {
          setItems([]);
          return;
        }
        const res = await api.atlassianJiraIssueSearch({
          project_key: selectedProject.key,
          text: query || undefined,
          max_results: 50,
        });
        setItems(res.items || []);
      } else if (mode === "confluence" && tab === "spaces") {
        const res = await api.atlassianConfluenceSpaces(query || undefined);
        setItems(res.items || []);
      } else if (mode === "confluence" && tab === "pages") {
        if (!selectedSpace?.id) {
          setItems([]);
          return;
        }
        const res = await api.atlassianConfluencePages(
          selectedSpace.id,
          query || undefined
        );
        setItems(res.items || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Atlassian sources");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [status?.connected, mode, tab, query, selectedProject, selectedSpace]);

  useEffect(() => {
    if (open && status?.connected) void loadList();
  }, [open, status?.connected, loadList]);

  const selectedKeys = useMemo(
    () => new Set(selected.map((s) => `${s.source_type}:${s.external_id}`)),
    [selected]
  );

  function toggleSelect(item: SelectedItem) {
    const key = `${item.source_type}:${item.external_id}`;
    setSelected((prev) =>
      prev.some((s) => `${s.source_type}:${s.external_id}` === key)
        ? prev.filter((s) => `${s.source_type}:${s.external_id}` !== key)
        : [...prev, item]
    );
  }

  async function showPreview(item: SelectedItem) {
    try {
      if (item.source_type === "jira_issue") {
        setPreview(await api.atlassianJiraPreview(item.external_key || item.external_id));
      } else {
        setPreview(await api.atlassianConfluencePreview(item.external_id));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed");
    }
  }

  async function runImport() {
    if (!selected.length) return;
    setImporting(true);
    setError(null);
    setReport(null);
    try {
      const result = (await api.atlassianImport({
        qa_project_id: projectId,
        sources: selected.map((s) => ({
          source_type: s.source_type,
          external_id: s.external_id,
          external_key: s.external_key,
          container_id: s.container_id,
          container_key: s.container_key,
        })),
        options: { include_comments: false, include_child_pages: false, replace_existing: true },
      })) as {
        imported?: number;
        updated?: number;
        unchanged?: number;
        failed?: number;
      };
      setReport(
        `Imported ${result.imported ?? 0}, updated ${result.updated ?? 0}, unchanged ${result.unchanged ?? 0}, failed ${result.failed ?? 0}`
      );
      setSelected([]);
      onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/40 p-4" role="dialog" aria-modal>
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-ink-700/10 px-5 py-4">
          <div>
            <div className="label">Atlassian</div>
            <h2 className="font-display text-xl text-ink-900">
              Import from {mode === "jira" ? "Jira" : "Confluence"}
            </h2>
            <p className="text-sm text-ink-600/75">
              {status?.selected_site_name || "No site selected"} · {status?.status || "…"}
            </p>
          </div>
          <button type="button" className="btn-secondary" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[1.2fr_0.8fr]">
          <div className="overflow-auto border-r border-ink-700/10 p-4">
            {!status?.configured ? (
              <p className="text-sm text-ink-700">
                Atlassian OAuth is not configured. Set client id/secret in the backend environment.
              </p>
            ) : !status.connected ? (
              <div className="space-y-3">
                <p className="text-sm text-ink-700">Connect your Atlassian account to browse sources.</p>
                <a className="btn-primary inline-flex" href={api.atlassianConnectUrl(projectId)}>
                  Connect Atlassian
                </a>
              </div>
            ) : (
              <>
                {sites.length > 1 ? (
                  <label className="mb-3 block text-sm">
                    Site
                    <select
                      className="mt-1 w-full rounded-xl border border-ink-700/15 px-3 py-2"
                      value={sites.find((s) => s.name === status.selected_site_name)?.cloud_id || ""}
                      onChange={(e) => {
                        void api.atlassianSelectSite(e.target.value).then(() => refreshStatus());
                      }}
                    >
                      {sites.map((s) => (
                        <option key={s.cloud_id} value={s.cloud_id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}

                <div className="mb-3 flex flex-wrap gap-2">
                  {(mode === "jira" ? (["projects", "issues"] as Tab[]) : (["spaces", "pages"] as Tab[])).map(
                    (t) => (
                      <button
                        key={t}
                        type="button"
                        className={`rounded-full px-3 py-1 text-xs ${
                          tab === t ? "bg-ink-900 text-white" : "bg-mist-100 text-ink-700"
                        }`}
                        onClick={() => setTab(t)}
                      >
                        {t}
                      </button>
                    )
                  )}
                </div>

                <div className="mb-3 flex gap-2">
                  <input
                    className="w-full rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
                    placeholder="Search…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void loadList();
                    }}
                  />
                  <button type="button" className="btn-secondary" onClick={() => void loadList()}>
                    Search
                  </button>
                </div>

                {selectedProject && mode === "jira" ? (
                  <div className="mb-2 text-xs text-ink-600/70">
                    Project: {selectedProject.key} — {selectedProject.name}
                  </div>
                ) : null}
                {selectedSpace && mode === "confluence" ? (
                  <div className="mb-2 text-xs text-ink-600/70">
                    Space: {selectedSpace.key} — {selectedSpace.name}
                  </div>
                ) : null}

                {loading ? (
                  <div className="flex items-center gap-2 text-sm text-ink-600/70">
                    <Loader2 className="h-4 w-4 animate-spin" /> Loading…
                  </div>
                ) : null}

                <ul className="space-y-2">
                  {items.map((row) => {
                    if (tab === "projects") {
                      const key = String(row.key || "");
                      const id = String(row.id || key);
                      return (
                        <li key={id}>
                          <button
                            type="button"
                            className="w-full rounded-xl border border-ink-700/10 px-3 py-2 text-left hover:bg-mist-50"
                            onClick={() => {
                              setSelectedProject({ id, key, name: String(row.name || key) });
                              setTab("issues");
                            }}
                          >
                            <div className="font-medium">{String(row.name)}</div>
                            <div className="text-xs text-ink-600/70">{key}</div>
                          </button>
                        </li>
                      );
                    }
                    if (tab === "spaces") {
                      const id = String(row.id || "");
                      const key = String(row.key || "");
                      return (
                        <li key={id}>
                          <button
                            type="button"
                            className="w-full rounded-xl border border-ink-700/10 px-3 py-2 text-left hover:bg-mist-50"
                            onClick={() => {
                              setSelectedSpace({ id, key, name: String(row.name || key) });
                              setTab("pages");
                            }}
                          >
                            <div className="font-medium">{String(row.name)}</div>
                            <div className="text-xs text-ink-600/70">{key}</div>
                          </button>
                        </li>
                      );
                    }
                    if (tab === "issues") {
                      const key = String(row.key || "");
                      const id = String(row.id || key);
                      const sel: SelectedItem = {
                        source_type: "jira_issue",
                        external_id: id,
                        external_key: key,
                        container_key: selectedProject?.key,
                        container_id: selectedProject?.id,
                        title: `${key} — ${String(row.summary || "")}`,
                      };
                      const checked = selectedKeys.has(`jira_issue:${id}`);
                      return (
                        <li
                          key={id}
                          className="flex items-start gap-2 rounded-xl border border-ink-700/10 px-3 py-2"
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleSelect(sel)}
                            aria-label={`Select ${key}`}
                          />
                          <button
                            type="button"
                            className="flex-1 text-left"
                            onClick={() => void showPreview(sel)}
                          >
                            <div className="font-medium">{sel.title}</div>
                            <div className="text-xs text-ink-600/70">
                              {String(row.status || "")} · {String(row.issue_type || "")}
                            </div>
                          </button>
                        </li>
                      );
                    }
                    const id = String(row.id || "");
                    const sel: SelectedItem = {
                      source_type: "confluence_page",
                      external_id: id,
                      container_id: selectedSpace?.id,
                      container_key: selectedSpace?.key,
                      title: String(row.title || id),
                    };
                    const checked = selectedKeys.has(`confluence_page:${id}`);
                    return (
                      <li
                        key={id}
                        className="flex items-start gap-2 rounded-xl border border-ink-700/10 px-3 py-2"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleSelect(sel)}
                          aria-label={`Select ${sel.title}`}
                        />
                        <button type="button" className="flex-1 text-left" onClick={() => void showPreview(sel)}>
                          <div className="font-medium">{sel.title}</div>
                          <div className="text-xs text-ink-600/70">{String(row.status || "")}</div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
                {!loading && items.length === 0 ? (
                  <p className="text-sm text-ink-600/70">No items found.</p>
                ) : null}
              </>
            )}
          </div>

          <aside className="overflow-auto bg-mist-50/60 p-4">
            <div className="label mb-2">Preview</div>
            {preview ? (
              <div className="space-y-2 text-sm">
                <div className="font-medium text-ink-900">
                  {String(preview.key || preview.title || "Preview")}
                </div>
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-xl bg-white p-3 text-xs text-ink-800">
                  {String(
                    preview.description_text ||
                      preview.body_text ||
                      preview.acceptance_criteria_text ||
                      "No body"
                  ).slice(0, 4000)}
                </pre>
                {preview.url || preview.web_url ? (
                  <a
                    className="text-pine-800 underline"
                    href={String(preview.url || preview.web_url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open in Atlassian
                  </a>
                ) : null}
              </div>
            ) : (
              <p className="text-sm text-ink-600/70">Select an issue or page to preview.</p>
            )}
          </aside>
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-ink-700/10 px-5 py-4">
          <div className="text-sm text-ink-700">
            {selected.length} selected
            {report ? <span className="ml-2 text-pine-700">{report}</span> : null}
            {error ? <span className="ml-2 text-signal-high">{error}</span> : null}
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-secondary" onClick={() => setSelected([])}>
              Clear
            </button>
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={!selected.length || importing}
              onClick={() => void runImport()}
            >
              {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Import Selected ({selected.length})
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
