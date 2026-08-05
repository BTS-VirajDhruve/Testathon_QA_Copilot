"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Download, FileCode2, Loader2, X } from "lucide-react";
import { api } from "@/lib/api";
import type {
  BDDExcludedTest,
  BDDExportOptions,
  BDDExportPreview,
  BDDExportScope,
  QACopilotResponse,
} from "@/lib/types";

type ExportPhase = "idle" | "preparing" | "validating" | "packaging" | "done" | "error";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function parseExportError(err: unknown): {
  message: string;
  code?: string;
  excluded?: BDDExcludedTest[];
  validOnlyAvailable?: boolean;
} {
  if (err && typeof err === "object" && "message" in err) {
    const e = err as {
      message?: string;
      code?: string;
      details?: { excluded_tests?: BDDExcludedTest[]; valid_only_available?: boolean };
    };
    return {
      message: e.message || "Export failed",
      code: e.code,
      excluded: e.details?.excluded_tests,
      validOnlyAvailable: Boolean(e.details?.valid_only_available),
    };
  }
  if (err instanceof Error) return { message: err.message };
  return { message: "Export failed" };
}

function Portal({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted || typeof document === "undefined") return null;
  return createPortal(children, document.body);
}

export type BddExportApi = ReturnType<typeof useBddExport>;

export function useBddExport(projectId: string, result: QACopilotResponse | null) {
  const [phase, setPhase] = useState<ExportPhase>("idle");
  const [error, setError] = useState<ReturnType<typeof parseExportError> | null>(null);
  const [preview, setPreview] = useState<BDDExportPreview | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [scope, setScope] = useState<BDDExportScope>("all_final_generated");
  const [includeComments, setIncludeComments] = useState(true);
  const [includeTags, setIncludeTags] = useState(true);
  const [includeImportCsv, setIncludeImportCsv] = useState(true);
  const [strict, setStrict] = useState(true);

  const testCount = result?.test_cases?.length ?? 0;
  const busy =
    phase === "preparing" || phase === "validating" || phase === "packaging";
  const disabled = !projectId || !result || testCount === 0 || busy;

  useEffect(() => {
    setPreview(null);
    setError(null);
    setToast(null);
    setPhase("idle");
    setOptionsOpen(false);
    setPreviewOpen(false);
  }, [projectId, result?.query]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const options: BDDExportOptions = useMemo(
    () => ({
      scope,
      include_traceability_comments: includeComments,
      include_tags: includeTags,
      include_import_csv: includeImportCsv,
      language: "en",
      strict,
    }),
    [scope, includeComments, includeTags, includeImportCsv, strict]
  );

  async function runPreview(opts?: BDDExportOptions) {
    if (!projectId || !result || testCount === 0 || busy) return;
    setPhase("preparing");
    setError(null);
    try {
      const data = await api.previewBddExport(projectId, opts || options);
      setPreview(data);
      setPhase("done");
      setPreviewOpen(true);
      setOptionsOpen(false);
    } catch (err) {
      setError(parseExportError(err));
      setPhase("error");
    }
  }

  async function runExport(opts?: BDDExportOptions) {
    if (!projectId || !result || testCount === 0 || busy) return;
    const payload = opts || options;
    setPhase("validating");
    setError(null);
    try {
      setPhase("packaging");
      const file = await api.exportBddAnalysis(projectId, payload);
      downloadBlob(file.blob, file.filename);
      setPhase("done");
      setToast(`Exported ${file.scenarioCount || "BDD"} scenario(s) · ${file.filename}`);
      setOptionsOpen(false);
      setPreviewOpen(false);
    } catch (err) {
      setError(parseExportError(err));
      setPhase("error");
    }
  }

  async function exportValidOnly() {
    await runExport({
      ...options,
      scope: "valid_only",
      strict: false,
    });
  }

  const label =
    phase === "preparing"
      ? "Preparing BDD…"
      : phase === "validating"
        ? "Validating Gherkin…"
        : phase === "packaging"
          ? "Creating download…"
          : "Export BDD";

  return {
    phase,
    label,
    busy,
    disabled,
    testCount,
    error,
    toast,
    preview,
    optionsOpen,
    setOptionsOpen,
    previewOpen,
    setPreviewOpen,
    scope,
    setScope,
    includeComments,
    setIncludeComments,
    includeTags,
    setIncludeTags,
    includeImportCsv,
    setIncludeImportCsv,
    strict,
    setStrict,
    runPreview,
    runExport,
    exportValidOnly,
    clearError: () => setError(null),
  };
}

export function BddExportTrigger({
  exportApi,
  compact = false,
}: {
  exportApi: BddExportApi;
  compact?: boolean;
}) {
  return (
    <button
      type="button"
      className={compact ? "btn-secondary text-xs" : "btn-secondary"}
      disabled={exportApi.disabled}
      title={
        exportApi.testCount === 0
          ? "No generated tests are available to export."
          : "Export Cucumber CSV for New Test Case forms"
      }
      onClick={() => exportApi.setOptionsOpen(true)}
      aria-haspopup="dialog"
    >
      {exportApi.busy ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Download className="h-4 w-4" />
      )}
      {exportApi.label}
    </button>
  );
}

export function BddExportOverlays({ exportApi }: { exportApi: BddExportApi }) {
  return (
    <Portal>
      {exportApi.toast ? (
        <div
          className="fixed bottom-5 right-5 z-[80] rounded-xl border border-pine-700/20 bg-white px-4 py-3 text-sm text-pine-800 shadow-soft"
          role="status"
          aria-live="polite"
        >
          {exportApi.toast}
        </div>
      ) : null}

      {exportApi.optionsOpen ? <BddExportOptionsDialog exportApi={exportApi} /> : null}
      {exportApi.previewOpen && exportApi.preview ? (
        <BddExportPreviewDialog
          preview={exportApi.preview}
          onClose={() => exportApi.setPreviewOpen(false)}
          onExport={() => exportApi.runExport()}
          busy={exportApi.busy}
        />
      ) : null}
      {exportApi.error && !exportApi.optionsOpen ? (
        <BddExportErrorBanner
          error={exportApi.error}
          onDismiss={exportApi.clearError}
          onValidOnly={exportApi.error.validOnlyAvailable ? exportApi.exportValidOnly : undefined}
          onOpenOptions={() => exportApi.setOptionsOpen(true)}
        />
      ) : null}
    </Portal>
  );
}

function BddExportOptionsDialog({ exportApi }: { exportApi: BddExportApi }) {
  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-ink-900/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="bdd-export-title"
      onClick={(e) => {
        if (e.target === e.currentTarget && !exportApi.busy) exportApi.setOptionsOpen(false);
      }}
    >
      <div className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-ink-700/10 bg-white shadow-soft">
        <div className="shrink-0 border-b border-ink-700/10 px-6 py-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="label">Cucumber BDD export</div>
              <h2 id="bdd-export-title" className="mt-1 font-display text-2xl text-ink-900">
                Export options
              </h2>
              <p className="mt-2 text-sm text-ink-700/80">
                {exportApi.testCount} generated test(s) in the current analysis. By default
                downloads a CSV for New Test Case forms (scenario name, tags, Given/When/Then).
                Uncheck CSV to export Gherkin `.feature` files instead.
              </p>
            </div>
            <button
              type="button"
              className="rounded-full p-1 hover:bg-mist-100"
              onClick={() => exportApi.setOptionsOpen(false)}
              aria-label="Close export options"
              disabled={exportApi.busy}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <fieldset className="space-y-2">
            <legend className="text-[11px] uppercase tracking-[0.14em] text-ink-600/60">
              Export scope
            </legend>
            {(
              [
                ["all_final_generated", "All Final Generated Tests"],
                ["valid_only", "Valid Tests Only"],
                ["current_filtered", "Current Filtered Tests"],
              ] as const
            ).map(([value, label]) => (
              <label key={value} className="flex items-center gap-2 text-sm text-ink-800">
                <input
                  type="radio"
                  name="bdd-export-scope"
                  checked={exportApi.scope === value}
                  onChange={() => exportApi.setScope(value)}
                />
                {label}
              </label>
            ))}
          </fieldset>

          <div className="mt-4 space-y-2 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={exportApi.includeComments}
                onChange={(e) => exportApi.setIncludeComments(e.target.checked)}
              />
              Traceability comments
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={exportApi.includeTags}
                onChange={(e) => exportApi.setIncludeTags(e.target.checked)}
              />
              Tags
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={exportApi.includeImportCsv}
                onChange={(e) => exportApi.setIncludeImportCsv(e.target.checked)}
              />
              Form import CSV (download .csv — scenario name, tags, Given/When/Then)
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={exportApi.strict}
                onChange={(e) => exportApi.setStrict(e.target.checked)}
              />
              Strict validation (block incomplete conversions)
            </label>
            <div className="text-xs text-ink-600/70">Language: English (en)</div>
          </div>

          {exportApi.error ? (
            <div className="mt-4 rounded-xl border border-signal-high/30 bg-signal-high/10 px-3 py-2 text-sm text-signal-high">
              <div className="font-medium">{exportApi.error.code || "Error"}</div>
              <div className="mt-1">{exportApi.error.message}</div>
              {exportApi.error.excluded?.length ? (
                <ul className="mt-2 max-h-28 space-y-1 overflow-auto text-xs">
                  {exportApi.error.excluded.slice(0, 8).map((ex) => (
                    <li key={ex.test_id}>
                      {ex.test_id}: {ex.reason}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="shrink-0 border-t border-ink-700/10 bg-white px-6 py-4">
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded-xl border border-ink-700/15 bg-white px-3.5 py-2 text-sm font-medium text-ink-900 hover:bg-mist-100 disabled:opacity-50"
              disabled={exportApi.busy}
              onClick={() => exportApi.runPreview()}
            >
              {exportApi.phase === "preparing" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileCode2 className="h-4 w-4" />
              )}
              Preview BDD
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded-xl bg-ink-900 px-3.5 py-2 text-sm font-medium text-white hover:bg-ink-800 disabled:opacity-50"
              disabled={exportApi.busy}
              onClick={() => exportApi.runExport()}
            >
              {exportApi.busy && exportApi.phase !== "preparing" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              Export
            </button>
            {exportApi.error?.validOnlyAvailable ? (
              <button
                type="button"
                className="inline-flex items-center gap-2 rounded-xl border border-ink-700/15 bg-white px-3.5 py-2 text-sm font-medium text-ink-900 hover:bg-mist-100"
                onClick={exportApi.exportValidOnly}
              >
                Export Valid Tests Only
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function BddExportPreviewDialog({
  preview,
  onClose,
  onExport,
  busy,
}: {
  preview: BDDExportPreview;
  onClose: () => void;
  onExport: () => void;
  busy: boolean;
}) {
  const [activeFile, setActiveFile] = useState(preview.files[0]?.filename || "");
  const current = preview.files.find((f) => f.filename === activeFile) || preview.files[0];
  const showingCsv = activeFile === "__csv__";
  const previewText = showingCsv
    ? preview.csv_preview || "No CSV preview"
    : current?.content || "No content";

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-ink-900/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="bdd-preview-title"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-ink-700/10 bg-white shadow-soft">
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-ink-700/10 px-5 py-4">
          <div>
            <div className="label">BDD preview</div>
            <h2 id="bdd-preview-title" className="mt-1 font-display text-xl text-ink-900">
              {preview.file_count} file(s) · {preview.scenario_count} scenario(s)
            </h2>
            <p className="mt-1 text-xs text-ink-600/70">
              Validation: {preview.status}
              {preview.excluded_tests.length
                ? ` · ${preview.excluded_tests.length} excluded`
                : ""}
              {preview.csv_preview ? " · form CSV included" : ""}
            </p>
          </div>
          <button
            type="button"
            className="rounded-full p-1 hover:bg-mist-100"
            onClick={onClose}
            aria-label="Close preview"
            disabled={busy}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-4 md:flex-row">
          <div className="w-full shrink-0 space-y-1 overflow-y-auto md:w-48">
            {preview.files.map((f) => (
              <button
                key={f.filename}
                type="button"
                className={`block w-full rounded-lg px-2 py-1.5 text-left text-xs ${
                  !showingCsv && current?.filename === f.filename
                    ? "bg-ink-900 text-white"
                    : "hover:bg-mist-100"
                }`}
                onClick={() => setActiveFile(f.filename)}
              >
                {f.filename}
                <div className="opacity-70">{f.scenario_count} scenarios</div>
              </button>
            ))}
            {preview.csv_preview ? (
              <button
                type="button"
                className={`block w-full rounded-lg px-2 py-1.5 text-left text-xs ${
                  showingCsv ? "bg-ink-900 text-white" : "hover:bg-mist-100"
                }`}
                onClick={() => setActiveFile("__csv__")}
              >
                test-cases-import.csv
                <div className="opacity-70">form import</div>
              </button>
            ) : null}
          </div>
          <pre className="min-h-[280px] flex-1 overflow-auto rounded-xl bg-ink-900 p-4 font-mono text-xs leading-relaxed text-mist-50">
            {previewText}
          </pre>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-ink-700/10 bg-white px-5 py-3">
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-xl border border-ink-700/15 bg-white px-3.5 py-2 text-sm font-medium text-ink-900 hover:bg-mist-100"
            onClick={() => {
              navigator.clipboard.writeText(previewText);
            }}
          >
            Copy
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-xl bg-ink-900 px-3.5 py-2 text-sm font-medium text-white hover:bg-ink-800 disabled:opacity-50"
            disabled={busy}
            onClick={onExport}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            Export
          </button>
        </div>
      </div>
    </div>
  );
}

function BddExportErrorBanner({
  error,
  onDismiss,
  onValidOnly,
  onOpenOptions,
}: {
  error: ReturnType<typeof parseExportError>;
  onDismiss: () => void;
  onValidOnly?: () => void;
  onOpenOptions?: () => void;
}) {
  return (
    <div className="fixed bottom-5 left-5 right-5 z-[80] mx-auto max-w-xl rounded-xl border border-signal-high/30 bg-white p-4 text-sm shadow-soft">
      <div className="font-medium text-signal-high">{error.code || "Export failed"}</div>
      <p className="mt-1 text-ink-800">{error.message}</p>
      {error.excluded?.length ? (
        <ul className="mt-2 max-h-24 space-y-1 overflow-auto text-xs text-ink-700">
          {error.excluded.slice(0, 6).map((ex) => (
            <li key={ex.test_id}>
              <strong>{ex.test_id}</strong>: {ex.reason}
              {ex.suggested_correction ? ` — ${ex.suggested_correction}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {onValidOnly ? (
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-xl border border-ink-700/15 bg-white px-3 py-1.5 text-xs font-medium text-ink-900 hover:bg-mist-100"
            onClick={onValidOnly}
          >
            Export Valid Tests Only
          </button>
        ) : null}
        {onOpenOptions ? (
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-xl border border-ink-700/15 bg-white px-3 py-1.5 text-xs font-medium text-ink-900 hover:bg-mist-100"
            onClick={onOpenOptions}
          >
            Open options
          </button>
        ) : null}
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-xl border border-ink-700/15 bg-white px-3 py-1.5 text-xs font-medium text-ink-900 hover:bg-mist-100"
          onClick={onDismiss}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
