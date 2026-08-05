/**
 * Agentic QA Copilot — 5-slide Demo Deck
 * Dark premium enterprise theme · 16:9 · AI-generated visuals
 */
const PptxGenJS = require("pptxgenjs");
const path = require("path");

const ASSETS = path.join(__dirname, "assets");
const OUT = path.join(__dirname, "Agentic_QA_Copilot_Demo.pptx");

const C = {
  bg: "080B12",
  card: "111827",
  cardAlt: "151C2E",
  violet: "7C3AED",
  teal: "06B6D4",
  green: "22C55E",
  gold: "F59E0B",
  text: "F8FAFC",
  muted: "CBD5E1",
  dim: "64748B",
  danger: "EF4444",
};

function addAccentBar(slide, x, y, w) {
  slide.addShape("rect", {
    x,
    y,
    w,
    h: 0.055,
    fill: { color: C.teal },
  });
}

function addSlideNumber(slide, n) {
  slide.addText(`${n}  /  5`, {
    x: 11.6,
    y: 7.08,
    w: 1.4,
    h: 0.28,
    fontSize: 11,
    fontFace: "Arial",
    color: C.dim,
    align: "right",
    valign: "middle",
  });
}

function baseSlide(pptx) {
  const s = pptx.addSlide();
  s.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: 13.333,
    h: 7.5,
    fill: { color: C.bg },
  });
  s.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: 13.333,
    h: 0.06,
    fill: { color: C.violet },
  });
  return s;
}

/* ─────────────────────────────────────────────
   SLIDE 1 — Title / Vision
   ───────────────────────────────────────────── */
function slide1(pptx) {
  const s = baseSlide(pptx);

  s.addImage({
    path: path.join(ASSETS, "slide1_vision.png"),
    x: 6.4,
    y: 0.8,
    w: 6.5,
    h: 5.85,
  });
  s.addShape(pptx.ShapeType.rect, {
    x: 6.4,
    y: 0.8,
    w: 0.55,
    h: 5.85,
    fill: { color: C.bg, transparency: 35 },
  });

  s.addText("AGENTIC QA COPILOT", {
    x: 0.7,
    y: 1.35,
    w: 5.6,
    h: 0.35,
    fontSize: 13,
    fontFace: "Arial",
    color: C.teal,
    bold: true,
    charSpacing: 4,
  });

  s.addText("Agentic QA Copilot", {
    x: 0.7,
    y: 1.85,
    w: 5.6,
    h: 0.85,
    fontSize: 40,
    fontFace: "Arial",
    color: C.text,
    bold: true,
  });

  s.addText(
    "Evidence-backed test generation powered by Graph RAG, Vector RAG, and AI agents",
    {
      x: 0.7,
      y: 2.8,
      w: 5.4,
      h: 0.85,
      fontSize: 18,
      fontFace: "Arial",
      color: C.muted,
    }
  );

  addAccentBar(s, 0.7, 3.85, 0.9);

  s.addText("From software context to complete QA intelligence.", {
    x: 0.7,
    y: 4.1,
    w: 5.4,
    h: 0.45,
    fontSize: 16,
    fontFace: "Arial",
    color: C.gold,
    italic: true,
  });

  const tags = [
    { label: "System Flow Graph", color: C.violet },
    { label: "QA Knowledge", color: C.teal },
    { label: "Agentic Test Generation", color: C.violet },
    { label: "Coverage Closure", color: C.gold },
  ];
  tags.forEach((t, i) => {
    const row = Math.floor(i / 2);
    const col = i % 2;
    const x = 0.7 + col * 2.7;
    const y = 4.85 + row * 0.55;
    s.addShape(pptx.ShapeType.roundRect, {
      x,
      y,
      w: 2.5,
      h: 0.42,
      fill: { color: C.cardAlt },
      rectRadius: 0.08,
      line: { color: t.color, width: 1.2 },
    });
    s.addText(t.label, {
      x,
      y,
      w: 2.5,
      h: 0.42,
      fontSize: 12,
      fontFace: "Arial",
      color: C.text,
      align: "center",
      valign: "middle",
    });
  });

  addSlideNumber(s, 1);
}

/* ─────────────────────────────────────────────
   SLIDE 2 — Problem & Solution
   ───────────────────────────────────────────── */
function slide2(pptx) {
  const s = baseSlide(pptx);

  s.addText("The QA Challenge", {
    x: 0.6,
    y: 0.3,
    w: 8,
    h: 0.6,
    fontSize: 36,
    fontFace: "Arial",
    color: C.text,
    bold: true,
  });
  addAccentBar(s, 0.6, 0.95, 0.7);

  s.addImage({
    path: path.join(ASSETS, "slide2_problem_solution.png"),
    x: 8.55,
    y: 0.25,
    w: 4.5,
    h: 2.55,
  });

  // Problem card
  s.addShape(pptx.ShapeType.roundRect, {
    x: 0.55,
    y: 1.25,
    w: 5.85,
    h: 5.0,
    fill: { color: C.card },
    rectRadius: 0.12,
  });
  s.addShape(pptx.ShapeType.rect, {
    x: 0.55,
    y: 1.25,
    w: 0.1,
    h: 5.0,
    fill: { color: C.danger },
  });
  s.addText("PROBLEM", {
    x: 0.9,
    y: 1.45,
    w: 5.2,
    h: 0.35,
    fontSize: 13,
    fontFace: "Arial",
    color: C.danger,
    bold: true,
    charSpacing: 3,
  });
  s.addText("Fragmented QA Reality", {
    x: 0.9,
    y: 1.8,
    w: 5.2,
    h: 0.4,
    fontSize: 22,
    fontFace: "Arial",
    color: C.text,
    bold: true,
  });

  const problems = [
    "Requirements scattered across tickets, docs, and tribal knowledge",
    "Generic AI produces generic test cases",
    "Coverage gaps are hard to detect manually",
    "Regression planning is slow and inconsistent",
  ];
  problems.forEach((p, i) => {
    const y = 2.45 + i * 0.8;
    s.addShape(pptx.ShapeType.ellipse, {
      x: 0.95,
      y: y + 0.08,
      w: 0.18,
      h: 0.18,
      fill: { color: C.danger },
    });
    s.addText(p, {
      x: 1.35,
      y,
      w: 4.7,
      h: 0.7,
      fontSize: 15,
      fontFace: "Arial",
      color: C.muted,
      valign: "top",
    });
  });

  // Solution card
  s.addShape(pptx.ShapeType.roundRect, {
    x: 6.85,
    y: 3.0,
    w: 5.95,
    h: 3.85,
    fill: { color: C.cardAlt },
    rectRadius: 0.12,
  });
  s.addShape(pptx.ShapeType.rect, {
    x: 6.85,
    y: 3.0,
    w: 0.1,
    h: 3.85,
    fill: { color: C.teal },
  });
  s.addText("SOLUTION", {
    x: 7.2,
    y: 3.2,
    w: 5.3,
    h: 0.3,
    fontSize: 13,
    fontFace: "Arial",
    color: C.teal,
    bold: true,
    charSpacing: 3,
  });
  s.addText("Agentic QA Copilot combines:", {
    x: 7.2,
    y: 3.5,
    w: 5.3,
    h: 0.35,
    fontSize: 18,
    fontFace: "Arial",
    color: C.text,
    bold: true,
  });

  const solutions = [
    { t: "System Flow Graph", c: C.violet },
    { t: "Jira / Confluence / QA documents", c: C.teal },
    { t: "Graph RAG + Vector RAG", c: C.violet },
    { t: "Specialist QA agents", c: C.gold },
    { t: "Evidence-backed outputs", c: C.green },
  ];
  solutions.forEach((sol, i) => {
    const y = 4.0 + i * 0.48;
    s.addShape(pptx.ShapeType.roundRect, {
      x: 7.2,
      y,
      w: 0.22,
      h: 0.22,
      fill: { color: sol.c },
      rectRadius: 0.04,
    });
    s.addText(sol.t, {
      x: 7.6,
      y: y - 0.05,
      w: 4.9,
      h: 0.35,
      fontSize: 15,
      fontFace: "Arial",
      color: C.muted,
      valign: "middle",
    });
  });

  addSlideNumber(s, 2);
}

/* ─────────────────────────────────────────────
   SLIDE 3 — How It Works / Architecture
   ───────────────────────────────────────────── */
function slide3(pptx) {
  const s = baseSlide(pptx);

  s.addText("How the Copilot Works", {
    x: 0.55,
    y: 0.22,
    w: 8,
    h: 0.5,
    fontSize: 34,
    fontFace: "Arial",
    color: C.text,
    bold: true,
  });
  addAccentBar(s, 0.55, 0.75, 0.7);

  const steps = [
    { n: "1", label: "System\nFlow Graph", c: C.violet },
    { n: "2", label: "Knowledge\nBase", c: C.teal },
    { n: "3", label: "Graph\nRAG", c: C.violet },
    { n: "4", label: "Vector\nRAG", c: C.teal },
    { n: "5", label: "Context\nFusion", c: C.gold },
    { n: "6", label: "QA\nAgents", c: C.violet },
    { n: "7", label: "Review +\nCoverage", c: C.teal },
    { n: "8", label: "Final QA\nOutputs", c: C.green },
  ];

  const startX = 0.4;
  const stepW = 1.45;
  const gap = 0.15;
  steps.forEach((st, i) => {
    const x = startX + i * (stepW + gap);
    s.addShape(pptx.ShapeType.roundRect, {
      x,
      y: 1.0,
      w: stepW,
      h: 1.35,
      fill: { color: C.cardAlt },
      rectRadius: 0.1,
      line: { color: st.c, width: 1.25 },
    });
    s.addShape(pptx.ShapeType.ellipse, {
      x: x + 0.52,
      y: 1.12,
      w: 0.4,
      h: 0.4,
      fill: { color: st.c },
    });
    s.addText(st.n, {
      x: x + 0.52,
      y: 1.12,
      w: 0.4,
      h: 0.4,
      fontSize: 14,
      fontFace: "Arial",
      color: C.text,
      bold: true,
      align: "center",
      valign: "middle",
    });
    s.addText(st.label, {
      x: x + 0.05,
      y: 1.58,
      w: stepW - 0.1,
      h: 0.7,
      fontSize: 11,
      fontFace: "Arial",
      color: C.muted,
      align: "center",
      valign: "middle",
    });
    if (i < steps.length - 1) {
      s.addShape(pptx.ShapeType.rightArrow, {
        x: x + stepW - 0.02,
        y: 1.52,
        w: 0.18,
        h: 0.22,
        fill: { color: C.dim },
      });
    }
  });

  s.addImage({
    path: path.join(ASSETS, "slide3_architecture.png"),
    x: 8.7,
    y: 2.55,
    w: 4.25,
    h: 3.8,
  });

  const explains = [
    {
      title: "Graph RAG",
      body: "Understands user journeys, branches, dependencies, and failure paths.",
      c: C.violet,
    },
    {
      title: "Vector RAG",
      body: "Retrieves relevant requirements, bugs, tickets, and documents.",
      c: C.teal,
    },
    {
      title: "Context Fusion",
      body: "Combines graph structure + document evidence into one reliable prompt context.",
      c: C.gold,
    },
    {
      title: "Agents",
      body: "Generate, review, improve, and explain QA artifacts.",
      c: C.green,
    },
  ];

  explains.forEach((ex, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.55 + col * 4.0;
    const y = 2.65 + row * 2.0;
    s.addShape(pptx.ShapeType.roundRect, {
      x,
      y,
      w: 3.8,
      h: 1.8,
      fill: { color: C.card },
      rectRadius: 0.1,
    });
    s.addShape(pptx.ShapeType.rect, {
      x,
      y,
      w: 0.08,
      h: 1.8,
      fill: { color: ex.c },
    });
    s.addText(ex.title, {
      x: x + 0.3,
      y: y + 0.25,
      w: 3.3,
      h: 0.4,
      fontSize: 18,
      fontFace: "Arial",
      color: C.text,
      bold: true,
    });
    s.addText(ex.body, {
      x: x + 0.3,
      y: y + 0.75,
      w: 3.3,
      h: 0.85,
      fontSize: 14,
      fontFace: "Arial",
      color: C.muted,
    });
  });

  addSlideNumber(s, 3);
}

/* ─────────────────────────────────────────────
   SLIDE 4 — Live Demo Journey
   ───────────────────────────────────────────── */
function slide4(pptx) {
  const s = baseSlide(pptx);

  s.addText("Live Demo Journey", {
    x: 0.55,
    y: 0.22,
    w: 7,
    h: 0.5,
    fontSize: 34,
    fontFace: "Arial",
    color: C.text,
    bold: true,
  });
  addAccentBar(s, 0.55, 0.75, 0.7);

  const journey = [
    { n: "01", t: "Create System Flow Graph" },
    { n: "02", t: "Inspect Graph Explorer" },
    { n: "03", t: "Import Knowledge" },
    { n: "04", t: "Run Agentic Analysis" },
    { n: "05", t: "Generate Test Cases / BDD" },
    { n: "06", t: "Review Validity & Automation" },
    { n: "07", t: "View Bugs, Regression, Coverage" },
    { n: "08", t: "Export BDD Scenarios" },
  ];

  journey.forEach((j, i) => {
    const col = i % 4;
    const row = Math.floor(i / 4);
    const x = 0.5 + col * 3.15;
    const y = 1.05 + row * 1.2;
    s.addShape(pptx.ShapeType.roundRect, {
      x,
      y,
      w: 3.0,
      h: 1.0,
      fill: { color: C.cardAlt },
      rectRadius: 0.1,
      line: { color: i < 4 ? C.violet : C.teal, width: 1 },
    });
    s.addText(j.n, {
      x: x + 0.15,
      y: y + 0.15,
      w: 0.55,
      h: 0.35,
      fontSize: 16,
      fontFace: "Arial",
      color: i < 4 ? C.violet : C.teal,
      bold: true,
    });
    s.addText(j.t, {
      x: x + 0.15,
      y: y + 0.5,
      w: 2.7,
      h: 0.4,
      fontSize: 13,
      fontFace: "Arial",
      color: C.text,
    });
  });

  s.addShape(pptx.ShapeType.roundRect, {
    x: 0.5,
    y: 3.55,
    w: 3.9,
    h: 3.2,
    fill: { color: C.card },
    rectRadius: 0.1,
  });
  s.addText("INPUT", {
    x: 0.75,
    y: 3.7,
    w: 3.4,
    h: 0.35,
    fontSize: 13,
    fontFace: "Arial",
    color: C.gold,
    bold: true,
    charSpacing: 3,
  });
  ["Feature flow", "Requirements", "Bugs", "Tickets", "Docs"].forEach(
    (item, i) => {
      s.addText("▸  " + item, {
        x: 0.85,
        y: 4.2 + i * 0.42,
        w: 3.3,
        h: 0.38,
        fontSize: 16,
        fontFace: "Arial",
        color: C.muted,
      });
    }
  );

  s.addShape(pptx.ShapeType.roundRect, {
    x: 4.6,
    y: 3.55,
    w: 3.9,
    h: 3.2,
    fill: { color: C.card },
    rectRadius: 0.1,
  });
  s.addText("OUTPUT", {
    x: 4.85,
    y: 3.7,
    w: 3.4,
    h: 0.35,
    fontSize: 13,
    fontFace: "Arial",
    color: C.green,
    bold: true,
    charSpacing: 3,
  });
  [
    "Test Cases",
    "BDD Scenarios",
    "Automation Review",
    "Bug Reports / Regression",
    "Coverage Gaps & Evidence",
  ].forEach((item, i) => {
    s.addText("▸  " + item, {
      x: 4.95,
      y: 4.2 + i * 0.42,
      w: 3.3,
      h: 0.38,
      fontSize: 16,
      fontFace: "Arial",
      color: C.muted,
    });
  });

  s.addImage({
    path: path.join(ASSETS, "slide4_demo_journey.png"),
    x: 8.7,
    y: 3.55,
    w: 4.25,
    h: 3.2,
  });

  addSlideNumber(s, 4);
}

/* ─────────────────────────────────────────────
   SLIDE 5 — Future Scope / Roadmap
   ───────────────────────────────────────────── */
function slide5(pptx) {
  const s = baseSlide(pptx);

  s.addText("Future Scope", {
    x: 0.55,
    y: 0.22,
    w: 6,
    h: 0.5,
    fontSize: 36,
    fontFace: "Arial",
    color: C.text,
    bold: true,
  });
  s.addText("From QA assistant to continuous AI QA platform", {
    x: 0.55,
    y: 0.75,
    w: 7.5,
    h: 0.35,
    fontSize: 15,
    fontFace: "Arial",
    color: C.muted,
    italic: true,
  });
  addAccentBar(s, 0.55, 1.15, 0.7);

  s.addShape(pptx.ShapeType.rect, {
    x: 0.7,
    y: 1.75,
    w: 11.9,
    h: 0.04,
    fill: { color: C.violet },
  });

  const milestones = [
    {
      title: "Deeper Jira +\nConfluence",
      body: "Auto-sync epics, stories, acceptance criteria, and product docs.",
      c: C.violet,
    },
    {
      title: "Test Execution\nIntegration",
      body: "Connect Playwright, Selenium, Cypress, Postman, and CI/CD.",
      c: C.teal,
    },
    {
      title: "Automated Script\nGeneration",
      body: "Convert approved BDD into runnable automation code.",
      c: C.gold,
    },
    {
      title: "Release Readiness\nDashboard",
      body: "Risk, coverage, automation readiness, and open QA gaps.",
      c: C.violet,
    },
    {
      title: "Continuous QA\nMonitoring",
      body: "Re-run analysis when requirements, tickets, or flows change.",
      c: C.teal,
    },
    {
      title: "Enterprise\nGovernance",
      body: "RBAC, audit logs, approval workflows, reusable QA templates.",
      c: C.green,
    },
  ];

  milestones.forEach((m, i) => {
    const x = 0.45 + i * 2.15;
    s.addShape(pptx.ShapeType.ellipse, {
      x: x + 0.75,
      y: 1.62,
      w: 0.3,
      h: 0.3,
      fill: { color: m.c },
      line: { color: C.bg, width: 2 },
    });
    s.addText(String(i + 1), {
      x: x + 0.75,
      y: 1.62,
      w: 0.3,
      h: 0.3,
      fontSize: 11,
      fontFace: "Arial",
      color: C.text,
      bold: true,
      align: "center",
      valign: "middle",
    });

    s.addShape(pptx.ShapeType.roundRect, {
      x,
      y: 2.15,
      w: 2.05,
      h: 3.35,
      fill: { color: C.cardAlt },
      rectRadius: 0.1,
      line: { color: m.c, width: 1 },
    });
    s.addText(m.title, {
      x: x + 0.1,
      y: 2.35,
      w: 1.85,
      h: 0.85,
      fontSize: 13,
      fontFace: "Arial",
      color: C.text,
      bold: true,
      align: "center",
    });
    s.addText(m.body, {
      x: x + 0.12,
      y: 3.35,
      w: 1.8,
      h: 1.9,
      fontSize: 12,
      fontFace: "Arial",
      color: C.muted,
      align: "center",
    });
  });

  s.addImage({
    path: path.join(ASSETS, "slide5_roadmap.png"),
    x: 0.45,
    y: 5.7,
    w: 12.4,
    h: 1.15,
  });

  addSlideNumber(s, 5);
}

async function build() {
  const pptx = new PptxGenJS();
  pptx.defineLayout({ name: "WIDE16x9", width: 13.333, height: 7.5 });
  pptx.layout = "WIDE16x9";
  pptx.author = "Agentic QA Copilot";
  pptx.title = "Agentic QA Copilot — Demo";
  pptx.subject =
    "Evidence-backed test generation powered by Graph RAG, Vector RAG, and AI agents";

  slide1(pptx);
  slide2(pptx);
  slide3(pptx);
  slide4(pptx);
  slide5(pptx);

  await pptx.writeFile({ fileName: OUT });
  console.log("Wrote:", OUT);
}

build().catch((err) => {
  console.error(err);
  process.exit(1);
});
