"use client";

import { useCallback, useEffect, useState } from "react";
import { FileText, Loader2, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { AtlassianSourcePicker } from "@/components/AtlassianSourcePicker";

type Chooser = "menu" | "paste" | "upload" | null;
type PickerMode = "jira" | "confluence" | null;

export function KnowledgePanel({
  projectId,
  onDocumentsChanged,
}: {
  projectId: string;
  onDocumentsChanged?: (count: number) => void;
}) {
  const [docs, setDocs] = useState<Array<{ id: string; filename: string; chunk_count: number }>>(
    []
  );
  const [imports, setImports] = useState<Array<Record<string, unknown>>>([]);
  const [filename, setFilename] = useState("qa-notes.md");
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [chooser, setChooser] = useState<Chooser>(null);
  const [pickerMode, setPickerMode] = useState<PickerMode>(null);
  const [atlStatus, setAtlStatus] = useState<string>("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, imported] = await Promise.all([
        api.listDocuments(projectId),
        api.atlassianListImports(projectId).catch(() => []),
      ]);
      setDocs(list);
      setImports(imported);
      onDocumentsChanged?.(list.length);
      const st = await api.atlassianStatus().catch(() => null);
      if (st) {
        setAtlStatus(
          !st.enabled
            ? "disabled"
            : !st.configured
              ? "not_configured"
              : st.connected
                ? "connected"
                : "disconnected"
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
      setDocs([]);
      setImports([]);
      onDocumentsChanged?.(0);
    } finally {
      setLoading(false);
    }
  }, [projectId, onDocumentsChanged]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function ingest() {
    if (!text.trim()) return;
    setIngesting(true);
    setError(null);
    setStatus("");
    try {
      await api.ingestText(projectId, filename, text);
      setStatus(`Indexed ${filename}`);
      setText("");
      setChooser(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
    } finally {
      setIngesting(false);
    }
  }

  async function onUpload(file: File | null) {
    if (!file) return;
    setIngesting(true);
    setError(null);
    try {
      await api.uploadDocument(projectId, file);
      setStatus(`Uploaded ${file.name}`);
      setChooser(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIngesting(false);
    }
  }

  async function syncOne(sourceId: string) {
    try {
      await api.atlassianSyncImport(sourceId, projectId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed");
    }
  }

  async function removeOne(sourceId: string) {
    if (!window.confirm("Remove this Atlassian source from the Knowledge Base?")) return;
    try {
      await api.atlassianDeleteImport(sourceId, projectId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Remove failed");
    }
  }

  return (
    <section className="panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="label">Knowledge Base</div>
          <h2 className="mt-2 font-display text-2xl">Documents for Vector RAG</h2>
          <p className="mt-2 text-sm text-ink-700/75">
            Upload, paste, or import Jira/Confluence sources. Chunks are embedded and fused with the
            system flow graph.
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={() => setChooser("menu")}>
          Add Knowledge
        </button>
      </div>

      {error ? (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-signal-high/30 bg-signal-high/10 px-3 py-2 text-sm text-signal-high">
          <span>{error}</span>
          <button className="btn-secondary" onClick={refresh}>
            Retry
          </button>
        </div>
      ) : null}
      {status ? <div className="mt-2 text-sm text-pine-700">{status}</div> : null}

      {chooser === "menu" ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <button
            type="button"
            className="rounded-2xl border border-ink-700/10 bg-white px-4 py-5 text-left hover:border-pine-700/40"
            onClick={() => setChooser("upload")}
          >
            <Upload className="mb-2 h-5 w-5 text-pine-800" />
            <div className="font-medium">Upload Files</div>
            <div className="text-xs text-ink-600/70">PDF, DOCX, or text</div>
          </button>
          <button
            type="button"
            className="rounded-2xl border border-ink-700/10 bg-white px-4 py-5 text-left hover:border-pine-700/40"
            onClick={() => setChooser("paste")}
          >
            <FileText className="mb-2 h-5 w-5 text-pine-800" />
            <div className="font-medium">Paste Text</div>
            <div className="text-xs text-ink-600/70">Requirements or QA notes</div>
          </button>
          <button
            type="button"
            className="rounded-2xl border border-ink-700/10 bg-white px-4 py-5 text-left hover:border-pine-700/40"
            onClick={() => {
              setChooser(null);
              setPickerMode("jira");
            }}
          >
            <div className="mb-2 text-sm font-semibold text-blue-700">Jira</div>
            <div className="font-medium">Import from Jira</div>
            <div className="text-xs text-ink-600/70">
              {atlStatus === "connected" ? "Browse issues" : "Connect Atlassian"}
            </div>
          </button>
          <button
            type="button"
            className="rounded-2xl border border-ink-700/10 bg-white px-4 py-5 text-left hover:border-pine-700/40"
            onClick={() => {
              setChooser(null);
              setPickerMode("confluence");
            }}
          >
            <div className="mb-2 text-sm font-semibold text-teal-700">Confluence</div>
            <div className="font-medium">Import from Confluence</div>
            <div className="text-xs text-ink-600/70">
              {atlStatus === "connected" ? "Browse pages" : "Connect Atlassian"}
            </div>
          </button>
        </div>
      ) : null}

      {chooser === "paste" ? (
        <div className="mt-5 max-w-2xl">
          <input
            className="w-full rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            disabled={ingesting}
          />
          <textarea
            className="mt-3 min-h-40 w-full rounded-2xl border border-ink-700/15 px-3 py-2 text-sm"
            placeholder="Paste requirements, policies, or QA notes..."
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={ingesting}
          />
          <div className="mt-3 flex gap-2">
            <button className="btn-primary" onClick={ingest} disabled={ingesting || !text.trim()}>
              {ingesting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Ingest & embed
            </button>
            <button type="button" className="btn-secondary" onClick={() => setChooser(null)}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {chooser === "upload" ? (
        <div className="mt-5">
          <input
            type="file"
            accept=".pdf,.docx,.md,.txt,.csv"
            onChange={(e) => void onUpload(e.target.files?.[0] || null)}
            disabled={ingesting}
          />
          <button type="button" className="btn-secondary ml-2" onClick={() => setChooser(null)}>
            Cancel
          </button>
        </div>
      ) : null}

      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <div className="space-y-2">
          <div className="label">Indexed documents</div>
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-ink-600/70">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading documents…
            </div>
          ) : null}
          {docs.map((d) => (
            <div key={d.id} className="rounded-2xl border border-ink-700/10 bg-white/70 px-4 py-3">
              <div className="font-medium">{d.filename}</div>
              <div className="text-xs text-ink-600/70">{d.chunk_count} chunks</div>
            </div>
          ))}
          {!loading && docs.length === 0 && (
            <div className="text-sm text-ink-600/70">No documents indexed for this project.</div>
          )}
        </div>

        <div className="space-y-2">
          <div className="label">Atlassian sources</div>
          {imports.map((src) => (
            <div
              key={String(src.source_id)}
              className="rounded-2xl border border-ink-700/10 bg-white/70 px-4 py-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-ink-600/60">
                    {String(src.source_type || "atlassian")}
                  </div>
                  <div className="font-medium">{String(src.title || src.external_key)}</div>
                  <div className="text-xs text-ink-600/70">
                    {String(src.sync_status || "imported")} · {Number(src.chunk_count || 0)} chunks
                    {src.last_synced_at ? ` · synced ${String(src.last_synced_at).slice(0, 19)}` : ""}
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  {src.source_url ? (
                    <a
                      className="text-xs text-pine-800 underline"
                      href={String(src.source_url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open
                    </a>
                  ) : null}
                  <button
                    type="button"
                    className="text-xs text-ink-700 underline"
                    onClick={() => void syncOne(String(src.source_id))}
                  >
                    Sync Now
                  </button>
                  <button
                    type="button"
                    className="text-xs text-signal-high underline"
                    onClick={() => void removeOne(String(src.source_id))}
                  >
                    Remove
                  </button>
                </div>
              </div>
              {src.error ? <div className="mt-1 text-xs text-signal-high">{String(src.error)}</div> : null}
            </div>
          ))}
          {!loading && imports.length === 0 ? (
            <div className="text-sm text-ink-600/70">No Atlassian sources imported yet.</div>
          ) : null}
        </div>
      </div>

      <AtlassianSourcePicker
        projectId={projectId}
        mode={pickerMode || "jira"}
        open={Boolean(pickerMode)}
        onClose={() => setPickerMode(null)}
        onImported={() => void refresh()}
      />
    </section>
  );
}
