import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

describe("Atlassian knowledge UI", () => {
  it("KnowledgePanel exposes Add Knowledge chooser options", () => {
    const src = readFileSync(join(__dirname, "../components/KnowledgePanel.tsx"), "utf8");
    expect(src).toContain("Add Knowledge");
    expect(src).toContain("Upload Files");
    expect(src).toContain("Paste Text");
    expect(src).toContain("Import from Jira");
    expect(src).toContain("Import from Confluence");
  });

  it("AtlassianSourcePicker supports connect, selection, and import", () => {
    const src = readFileSync(join(__dirname, "../components/AtlassianSourcePicker.tsx"), "utf8");
    expect(src).toContain("Connect Atlassian");
    expect(src).toContain("Import Selected");
    expect(src).toContain("Clear");
    expect(src).toContain("atlassianConnectUrl");
  });

  it("api client never exposes token fields", () => {
    const src = readFileSync(join(__dirname, "./api.ts"), "utf8");
    expect(src).toContain("atlassianStatus");
    expect(src).not.toMatch(/refresh_token|access_token|client_secret/);
  });

  it("clears picker selection when project changes via effect deps", () => {
    const src = readFileSync(join(__dirname, "../components/AtlassianSourcePicker.tsx"), "utf8");
    expect(src).toContain("setSelected([])");
    expect(src).toContain("projectId");
  });
});
