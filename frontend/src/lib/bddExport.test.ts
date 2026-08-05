/**
 * BDD export UI helper tests.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

describe("BDD export UI wiring", () => {
  it("Analysis Results header includes Export BDD trigger", () => {
    const src = readFileSync(
      join(__dirname, "../components/AnalysisResultsPanel.tsx"),
      "utf8"
    );
    expect(src).toContain("BddExportTrigger");
    expect(src).toContain("useBddExport");
    expect(src).toContain("BddExportOverlays");
  });

  it("Tests toolbar shares the same export api prop", () => {
    const results = readFileSync(
      join(__dirname, "../components/AnalysisResultsPanel.tsx"),
      "utf8"
    );
    const artifacts = readFileSync(
      join(__dirname, "../components/ArtifactLists.tsx"),
      "utf8"
    );
    expect(results).toContain("bddExport={bddExport}");
    expect(artifacts).toContain("bddExport?: BddExportApi");
    expect(artifacts).toContain("BddExportTrigger");
  });

  it("default export scope is all_final_generated", () => {
    const src = readFileSync(
      join(__dirname, "../components/BddExportControls.tsx"),
      "utf8"
    );
    expect(src).toContain('useState<BDDExportScope>("all_final_generated")');
  });

  it("form import CSV option is enabled by default", () => {
    const src = readFileSync(
      join(__dirname, "../components/BddExportControls.tsx"),
      "utf8"
    );
    expect(src).toContain("includeImportCsv");
    expect(src).toContain("include_import_csv: includeImportCsv");
    expect(src).toContain("Form import CSV");
  });

  it("API client exposes preview and analysis export", () => {
    const src = readFileSync(join(__dirname, "./api.ts"), "utf8");
    expect(src).toContain("previewBddExport");
    expect(src).toContain("exportBddAnalysis");
    expect(src).toContain("/analyses/latest/exports/bdd");
  });
});
