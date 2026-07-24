"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function KnowledgePanel({ projectId }: { projectId: string }) {
  const [docs, setDocs] = useState<Array<{ id: string; filename: string; chunk_count: number }>>(
    []
  );
  const [filename, setFilename] = useState("qa-notes.md");
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");

  async function refresh() {
    const list = await api.listDocuments(projectId);
    setDocs(list);
  }

  useEffect(() => {
    refresh().catch(() => setDocs([]));
  }, [projectId]);

  async function ingest() {
    if (!text.trim()) return;
    await api.ingestText(projectId, filename, text);
    setStatus(`Indexed ${filename}`);
    setText("");
    await refresh();
  }

  return (
    <section className="panel p-6">
      <div className="label">Knowledge Base</div>
      <h2 className="mt-2 font-display text-2xl">Documents for Vector RAG</h2>
      <p className="mt-2 text-sm text-ink-700/75">
        Upload requirements and QA docs. Chunks are embedded and fused with the system flow graph.
      </p>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <div>
          <input
            className="w-full rounded-xl border border-ink-700/15 px-3 py-2 text-sm"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
          />
          <textarea
            className="mt-3 min-h-40 w-full rounded-2xl border border-ink-700/15 px-3 py-2 text-sm"
            placeholder="Paste requirements, policies, or QA notes..."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button className="btn-primary mt-3" onClick={ingest}>
            Ingest & embed
          </button>
          {status ? <div className="mt-2 text-sm text-pine-700">{status}</div> : null}
        </div>
        <div className="space-y-2">
          {docs.map((d) => (
            <div key={d.id} className="rounded-2xl border border-ink-700/10 bg-white/70 px-4 py-3">
              <div className="font-medium">{d.filename}</div>
              <div className="text-xs text-ink-600/70">{d.chunk_count} chunks</div>
            </div>
          ))}
          {docs.length === 0 && (
            <div className="text-sm text-ink-600/70">No documents yet. Seed the demo or ingest text.</div>
          )}
        </div>
      </div>
    </section>
  );
}