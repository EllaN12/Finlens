"use strict";
const pptxgen = require("pptxgenjs");

// ── Palette ─────────────────────────────────────────────────────────────────
const NAVY    = "1A3A6B";
const BLUE    = "1F77B4";
const ICE     = "D6E4F0";
const WHITE   = "FFFFFF";
const OFFWHITE= "F7F9FC";
const GREY    = "64748B";
const LGREY   = "E2E8F0";
const DGREY   = "475569";   // darker body text for better contrast
const GREEN   = "2CA02C";
const RED     = "D62728";
const AMBER   = "FF7F0E";

const makeShadow = () => ({ type: "outer", blur: 8, offset: 3, angle: 135, color: "000000", opacity: 0.10 });

// ── Helpers ──────────────────────────────────────────────────────────────────
function addSlideHeader(slide, title, pres) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.72,
    fill: { color: NAVY }, line: { color: NAVY }
  });
  slide.addText(title, {
    x: 0.4, y: 0, w: 9.2, h: 0.72,
    fontSize: 20, bold: true, color: WHITE, valign: "middle", margin: 0
  });
}

function statCard(slide, pres, x, y, w, h, value, label, color) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 0.06, h,
    fill: { color: color || BLUE }, line: { color: color || BLUE }
  });
  slide.addText(value, {
    x: x + 0.15, y: y + 0.08, w: w - 0.22, h: h * 0.52,
    fontSize: 20, bold: true, color: NAVY, valign: "middle", margin: 0
  });
  slide.addText(label, {
    x: x + 0.15, y: y + h * 0.55, w: w - 0.22, h: h * 0.42,
    fontSize: 10, color: DGREY, valign: "top", margin: 0
  });
}

function addBusinessQuestion(slide, pres, question) {
  // Left "?" badge
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 0.8, w: 0.36, h: 0.36,
    fill: { color: BLUE }, line: { color: BLUE },
  });
  slide.addText("?", {
    x: 0.4, y: 0.8, w: 0.36, h: 0.36,
    fontSize: 14, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0
  });
  // Label
  slide.addText("Business Question:", {
    x: 0.84, y: 0.8, w: 1.65, h: 0.36,
    fontSize: 10, bold: true, color: BLUE, valign: "middle", margin: 0
  });
  // Question text
  slide.addText(question, {
    x: 2.52, y: 0.8, w: 7.1, h: 0.36,
    fontSize: 10.5, bold: true, italic: true, color: NAVY, valign: "middle", margin: 0
  });
  // Thin rule below
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 1.17, w: 9.2, h: 0.02,
    fill: { color: LGREY }, line: { color: LGREY }
  });
}

// sentiment: "neutral" | "positive" | "warning" | "negative"
const SENTIMENT_COLOR = {
  positive: "1A6B3A",  // dark green
  neutral:  NAVY,
  warning:  "7A4A00",  // dark amber
  negative: "8B1A1A",  // dark red
};
const SENTIMENT_BG = {
  positive: "EAF7EE",
  neutral:  "EAF0FA",
  warning:  "FFF8EC",
  negative: "FDEAEA",
};
const SENTIMENT_ACCENT = {
  positive: GREEN,
  neutral:  BLUE,
  warning:  AMBER,
  negative: RED,
};

function addConclusion(slide, pres, text, sentiment = "neutral") {
  const bg     = SENTIMENT_BG[sentiment]     || SENTIMENT_BG.neutral;
  const accent = SENTIMENT_ACCENT[sentiment] || SENTIMENT_ACCENT.neutral;
  const tc     = SENTIMENT_COLOR[sentiment]  || SENTIMENT_COLOR.neutral;

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.1, w: 10, h: 0.525,
    fill: { color: bg }, line: { color: accent, width: 0 }
  });
  // left accent stripe
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.1, w: 0.22, h: 0.525,
    fill: { color: accent }, line: { color: accent }
  });
  // "✔ Conclusion:" label
  slide.addText("Conclusion:", {
    x: 0.32, y: 5.1, w: 1.3, h: 0.525,
    fontSize: 10, bold: true, color: accent, valign: "middle", margin: 0
  });
  // conclusion text
  slide.addText(text, {
    x: 1.62, y: 5.1, w: 8.18, h: 0.525,
    fontSize: 10.5, color: tc, valign: "middle", margin: 0, italic: false
  });
}

function noteCard(slide, pres, x, y, w, h, title, body, accentColor) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 0.06, h,
    fill: { color: accentColor || BLUE }, line: { color: accentColor || BLUE }
  });
  slide.addText(title, {
    x: x + 0.15, y: y + 0.07, w: w - 0.22, h: 0.3,
    fontSize: 11, bold: true, color: NAVY, margin: 0
  });
  slide.addText(body, {
    x: x + 0.15, y: y + 0.38, w: w - 0.22, h: h - 0.46,
    fontSize: 10, color: DGREY, margin: 0
  });
}

// ── Build ────────────────────────────────────────────────────────────────────
(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author  = "FinLens";
  pres.title   = "FinLens: Mortgage Analytics & Privacy Law Impact";

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 1 — TITLE  (fixed: removed dead-zone panels, vertically balanced)
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: NAVY };

    // Subtle right accent — thinner, anchored
    s.addShape(pres.shapes.RECTANGLE, {
      x: 9.0, y: 0, w: 1.0, h: 5.625,
      fill: { color: BLUE, transparency: 55 }, line: { color: BLUE, transparency: 55 }
    });

    // Tag badge
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y: 0.55, w: 1.8, h: 0.3,
      fill: { color: BLUE }, line: { color: BLUE }
    });
    s.addText("RESEARCH STUDY", {
      x: 0.5, y: 0.55, w: 1.8, h: 0.3,
      fontSize: 9, bold: true, color: WHITE, align: "center", valign: "middle", charSpacing: 2, margin: 0
    });

    s.addText("FinLens", {
      x: 0.5, y: 1.05, w: 8.4, h: 0.95,
      fontSize: 54, bold: true, color: WHITE, fontFace: "Georgia", margin: 0
    });
    s.addText("Mortgage Analytics & Privacy Law Impact", {
      x: 0.5, y: 1.98, w: 8.4, h: 0.62,
      fontSize: 26, color: ICE, fontFace: "Georgia", margin: 0
    });

    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y: 2.78, w: 3.5, h: 0.04,
      fill: { color: BLUE }, line: { color: BLUE }
    });

    s.addText("Causal Inference on CCPA / VCDPA / CPA Effects on US Mortgage Lending", {
      x: 0.5, y: 2.94, w: 8.4, h: 0.45,
      fontSize: 13, color: ICE, italic: true, margin: 0
    });
    s.addText("HMDA (CFPB) 2018 – 2023  ·  FRED Macro Controls  ·  States: CA · TX · FL · OH · NY · IL", {
      x: 0.5, y: 3.5, w: 8.4, h: 0.35,
      fontSize: 11, color: "AABBD0", margin: 0
    });
    s.addText("Live Demo:", {
      x: 0.5, y: 3.92, w: 1.2, h: 0.28,
      fontSize: 11, bold: true, color: ICE, margin: 0
    });
    s.addText("https://finlens-app-360526413047.us-central1.run.app/", {
      x: 1.72, y: 3.92, w: 7.2, h: 0.28,
      fontSize: 11, color: BLUE, underline: true, margin: 0,
      hyperlink: { url: "https://finlens-app-360526413047.us-central1.run.app/" }
    });

    // Stack pill row
    const pills = ["BigQuery", "dbt", "Airflow", "Streamlit", "statsmodels"];
    pills.forEach((p, i) => {
      const px = 0.5 + i * 1.6;
      s.addShape(pres.shapes.RECTANGLE, {
        x: px, y: 4.1, w: 1.45, h: 0.32,
        fill: { color: "0F2447" }, line: { color: "2A4A7F" }
      });
      s.addText(p, {
        x: px, y: 4.1, w: 1.45, h: 0.32,
        fontSize: 10, color: "90B4D0", align: "center", valign: "middle", margin: 0
      });
    });

    // Footer
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0, y: 5.18, w: 10, h: 0.445,
      fill: { color: "0A1A35" }, line: { color: "0A1A35" }
    });
    s.addText("FinLens  ·  Privacy Law Impact Study  ·  HMDA 2018–2023", {
      x: 0.5, y: 5.18, w: 9, h: 0.445,
      fontSize: 10, color: "6A8FAF", align: "center", valign: "middle", margin: 0
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 2 — RESEARCH QUESTION
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Research Question", pres);

    s.addText("Do consumer data privacy laws affect mortgage lending access?", {
      x: 0.5, y: 0.88, w: 9, h: 0.52,
      fontSize: 19, bold: true, color: NAVY, fontFace: "Georgia", margin: 0
    });

    // Question cards — fixed height, vertically padded content
    const qCards = [
      { x: 0.5, q: "① Aggregate Effect", body: "Does CCPA reduce overall mortgage approval rates in California relative to control states (TX, FL, OH)?" },
      { x: 5.3, q: "② Distributional Effect", body: "Does the impact fall disproportionately on lower-income borrowers — widening the credit-access gap by income?" }
    ];
    for (const c of qCards) {
      s.addShape(pres.shapes.RECTANGLE, {
        x: c.x, y: 1.52, w: 4.5, h: 1.45,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: c.x, y: 1.52, w: 4.5, h: 0.06,
        fill: { color: BLUE }, line: { color: BLUE }
      });
      s.addText(c.q, {
        x: c.x + 0.15, y: 1.62, w: 4.2, h: 0.35,
        fontSize: 13, bold: true, color: NAVY, margin: 0
      });
      s.addText(c.body, {
        x: c.x + 0.15, y: 2.0, w: 4.2, h: 0.88,
        fontSize: 12, color: DGREY, margin: 0
      });
    }

    // Three laws heading
    s.addText("Three Privacy Laws Studied", {
      x: 0.5, y: 3.15, w: 9, h: 0.36,
      fontSize: 14, bold: true, color: NAVY, margin: 0
    });

    const laws = [
      { name: "CCPA", state: "California", year: "2020", color: RED,   desc: "Broad opt-out rights\nMost comprehensive US state privacy law" },
      { name: "VCDPA", state: "Virginia",   year: "2023", color: BLUE,  desc: "Narrower opt-out scope\nControllers & processors framework" },
      { name: "CPA",   state: "Colorado",   year: "2023", color: GREEN, desc: "Opt-in for sensitive data\nUniversal opt-out mechanism" },
    ];
    laws.forEach((l, i) => {
      const lx = 0.5 + i * 3.1;
      s.addShape(pres.shapes.RECTANGLE, {
        x: lx, y: 3.58, w: 2.9, h: 1.72,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: lx, y: 3.58, w: 2.9, h: 0.06,
        fill: { color: l.color }, line: { color: l.color }
      });
      s.addText(l.name, {
        x: lx + 0.14, y: 3.66, w: 1.1, h: 0.5,
        fontSize: 22, bold: true, color: l.color, fontFace: "Georgia", margin: 0
      });
      s.addText(`${l.state}  ·  ${l.year}`, {
        x: lx + 0.14, y: 4.18, w: 2.6, h: 0.3,
        fontSize: 11, color: NAVY, bold: true, margin: 0
      });
      s.addText(l.desc, {
        x: lx + 0.14, y: 4.5, w: 2.6, h: 0.7,
        fontSize: 10.5, color: DGREY, margin: 0
      });
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 3 — DATA & STACK  (fixed: connector arrows thicker, column alignment)
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Data & Technology Stack", pres);

    // Left column header
    s.addText("Data Sources", {
      x: 0.4, y: 0.88, w: 4.3, h: 0.36,
      fontSize: 14, bold: true, color: NAVY, margin: 0
    });

    const dataSources = [
      { label: "HMDA — CFPB API", detail: "Loan-level mortgage applications\n2018–2023 · CA · TX · FL · OH · NY · IL" },
      { label: "FRED Macro Series", detail: "State unemployment rate, HPI,\n30-year fixed mortgage rate" },
    ];
    dataSources.forEach((d, i) => {
      const dy = 1.34 + i * 1.05;
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.4, y: dy, w: 4.2, h: 0.88,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.4, y: dy, w: 0.06, h: 0.88,
        fill: { color: BLUE }, line: { color: BLUE }
      });
      s.addText(d.label, {
        x: 0.55, y: dy + 0.08, w: 3.9, h: 0.28,
        fontSize: 12, bold: true, color: NAVY, margin: 0
      });
      s.addText(d.detail, {
        x: 0.55, y: dy + 0.38, w: 3.9, h: 0.42,
        fontSize: 10.5, color: DGREY, margin: 0
      });
    });

    s.addText("Key Variables", {
      x: 0.4, y: 3.42, w: 4.3, h: 0.34,
      fontSize: 14, bold: true, color: NAVY, margin: 0
    });
    const varItems = [
      { text: "approval_rate  ·  origination_rate", options: { bullet: true, breakLine: true, color: DGREY, fontSize: 11 } },
      { text: "avg_ltv  ·  avg_interest_rate", options: { bullet: true, breakLine: true, color: DGREY, fontSize: 11 } },
      { text: "income_tier  (low / moderate / middle / high)", options: { bullet: true, breakLine: true, color: DGREY, fontSize: 11 } },
      { text: "is_investor_loan  ·  is_california  ·  is_post_ccpa", options: { bullet: true, color: DGREY, fontSize: 11 } },
    ];
    s.addText(varItems, { x: 0.4, y: 3.82, w: 4.2, h: 1.55 });

    // Right column — pipeline (aligned to same y as left)
    s.addText("Data Pipeline", {
      x: 5.05, y: 0.88, w: 4.6, h: 0.36,
      fontSize: 14, bold: true, color: NAVY, margin: 0
    });

    const pipeline = [
      { label: "CFPB / FRED APIs",        color: NAVY },
      { label: "Airflow Ingestion DAGs",   color: BLUE },
      { label: "BigQuery Raw Tables",      color: "0D6EAF" },
      { label: "dbt Staging → Marts",      color: "128B6F" },
      { label: "Streamlit Analytics App",  color: GREEN },
    ];
    pipeline.forEach((p, i) => {
      const py = 1.34 + i * 0.78;
      s.addShape(pres.shapes.RECTANGLE, {
        x: 5.1, y: py, w: 4.5, h: 0.5,
        fill: { color: p.color }, line: { color: p.color }, shadow: makeShadow()
      });
      s.addText(p.label, {
        x: 5.1, y: py, w: 4.5, h: 0.5,
        fontSize: 12, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0
      });
      if (i < pipeline.length - 1) {
        // Arrow: triangle pointing down
        s.addShape(pres.shapes.RECTANGLE, {
          x: 7.2, y: py + 0.5, w: 0.2, h: 0.28,
          fill: { color: "9DAFC0" }, line: { color: "9DAFC0" }
        });
      }
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 4 — METHODOLOGY  (fixed: S4+S5 centered, footnote spacing)
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Methodology — 5 Causal Inference Scenarios", pres);

    s.addText("All models: HC3 heteroscedasticity-robust OLS  ·  Parallel trends tested  ·  State & year fixed effects", {
      x: 0.4, y: 0.82, w: 9.2, h: 0.3,
      fontSize: 11, italic: true, color: GREY, margin: 0
    });

    const scenarios = [
      { id: "S1", name: "Standard 2×2 DiD",  color: NAVY,    desc: "CA vs. TX/FL/OH · Pre: 2018–19\nPost: 2020–21 · HC3-robust OLS" },
      { id: "S2", name: "Staggered DiD",      color: BLUE,    desc: "CCPA/VCDPA/CPA cohorts\nCallaway & Sant'Anna approximation" },
      { id: "S3", name: "Event Study",        color: "0D6EAF",desc: "Dynamic DiD · Leads t−4 to t−2\nLags t0 to t+3 · Pre-trend F-test" },
      { id: "S4", name: "Triple DiD",         color: "128B6F",desc: "Investor vs. owner-occupied\nCA × Post × InvestorLoan" },
      { id: "S5", name: "Interaction DiD",    color: GREEN,   desc: "did × C(income_tier)\nJoint F-test of heterogeneity" },
    ];

    // Top 3: full-width row
    scenarios.slice(0, 3).forEach((sc, i) => {
      const sx = 0.4 + i * 3.1, sy = 1.25, sw = 2.92, sh = 1.8;
      s.addShape(pres.shapes.RECTANGLE, {
        x: sx, y: sy, w: sw, h: sh,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: sx, y: sy, w: sw, h: 0.5,
        fill: { color: sc.color }, line: { color: sc.color }
      });
      s.addText(sc.id, { x: sx + 0.12, y: sy + 0.02, w: 0.5, h: 0.46, fontSize: 22, bold: true, color: WHITE, valign: "middle", margin: 0 });
      s.addText(sc.name, { x: sx + 0.65, y: sy + 0.02, w: sw - 0.78, h: 0.46, fontSize: 12, bold: true, color: WHITE, valign: "middle", margin: 0 });
      s.addText(sc.desc, { x: sx + 0.12, y: sy + 0.6, w: sw - 0.24, h: 1.1, fontSize: 11, color: DGREY, margin: 0 });
    });

    // Bottom 2: centered on slide (each 3.5" wide, gap 0.6", total 7.6", margin 1.2" each side)
    scenarios.slice(3).forEach((sc, i) => {
      const sx = 1.2 + i * 4.1, sy = 3.22, sw = 3.5, sh = 1.8;
      s.addShape(pres.shapes.RECTANGLE, {
        x: sx, y: sy, w: sw, h: sh,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: sx, y: sy, w: sw, h: 0.5,
        fill: { color: sc.color }, line: { color: sc.color }
      });
      s.addText(sc.id, { x: sx + 0.12, y: sy + 0.02, w: 0.5, h: 0.46, fontSize: 22, bold: true, color: WHITE, valign: "middle", margin: 0 });
      s.addText(sc.name, { x: sx + 0.65, y: sy + 0.02, w: sw - 0.78, h: 0.46, fontSize: 12, bold: true, color: WHITE, valign: "middle", margin: 0 });
      s.addText(sc.desc, { x: sx + 0.12, y: sy + 0.6, w: sw - 0.24, h: 1.1, fontSize: 11, color: DGREY, margin: 0 });
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 5 — SCENARIO 1: STANDARD DiD
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Scenario 1 — Standard 2×2 DiD: CA vs. Control States", pres);
    addBusinessQuestion(s, pres, "Does CCPA reduce overall mortgage approval rates in California relative to control states (TX, FL, OH)?");

    // KPI row — all same color (BLUE) for consistency; significance communicated in label
    const kpis = [
      { v: "+3.24 pp", l: "DiD Estimate",       c: NAVY },
      { v: "p = 0.54",  l: "Not sig. at 5%",    c: NAVY },
      { v: "N = 2,352", l: "Observations",       c: NAVY },
      { v: "R² = 0.005",l: "Model fit",          c: NAVY },
    ];
    kpis.forEach((k, i) => statCard(s, pres, 0.4 + i * 2.32, 1.3, 2.1, 0.9, k.v, k.l, k.c));

    // Chart
    s.addText("Parallel Trends: Approval Rate — CA vs. Control Average", {
      x: 0.4, y: 2.36, w: 5.8, h: 0.34,
      fontSize: 13, bold: true, color: NAVY, margin: 0
    });
    s.addChart(pres.charts.LINE, [
      { name: "CA (treated)", labels: ["2018","2019","2020","2021"], values: [51.7, 56.0, 55.3, 59.5] },
      { name: "Control avg",  labels: ["2018","2019","2020","2021"], values: [49.7, 52.5, 51.5, 54.1] },
    ], {
      x: 0.4, y: 2.74, w: 5.6, h: 2.55,
      chartColors: [BLUE, GREY],
      lineSize: 3,
      showLegend: true, legendPos: "b",
      chartArea: { fill: { color: WHITE } },
      catAxisLabelColor: GREY, valAxisLabelColor: GREY,
      valGridLine: { color: LGREY, size: 0.5 }, catGridLine: { style: "none" },
      showValue: true, dataLabelFontSize: 10, dataLabelColor: NAVY,
      valAxisMinVal: 45, valAxisMaxVal: 65,
    });

    // OLS table
    s.addText("OLS Results (HC3-Robust SEs)", {
      x: 6.25, y: 2.36, w: 3.45, h: 0.34,
      fontSize: 13, bold: true, color: NAVY, margin: 0
    });
    const tblData = [
      [
        { text: "Term",           options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 9.5 } },
        { text: "Coef",           options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 9.5 } },
        { text: "p-val",          options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 9.5 } },
      ],
      ["did",                "+3.24 pp",  "0.540"],
      ["treat",              "+17.45 pp", "0.391"],
      ["post",               "−2.06 pp",  "0.798"],
      ["C(state)[T.OH]",     "+15.18 pp ***", "0.000"],
      ["C(state)[T.TX]",     "+13.85 pp ***", "0.000"],
      ["C(state)[T.FL]",     "+14.00 pp",     "0.139"],
      ["unemployment_rate",  "−0.76 pp",  "0.622"],
      ["mortgage_rate_30yr", "−4.86 pp",  "0.190"],
    ];
    s.addTable(tblData, {
      x: 6.25, y: 2.74, w: 3.4, h: 2.55,
      border: { pt: 0.5, color: LGREY },
      colW: [1.45, 1.15, 0.8],
      fontSize: 9.5, color: NAVY,
      fill: { color: WHITE },
    });

    addConclusion(s, pres,
      "No statistically significant aggregate effect of CCPA on approval rates (DiD = +3.24 pp, p = 0.54). Lenders appear to have adapted without restricting overall credit access in California.",
      "neutral"
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 6 — SCENARIO 2: STAGGERED DiD  (fixed: unique per-cohort text)
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Scenario 2 — Staggered DiD: Multi-State Privacy Law Rollout", pres);
    addBusinessQuestion(s, pres, "Do CCPA, VCDPA, and CPA each reduce mortgage approval rates in their respective states — and do effects persist over time?");

    s.addText("Callaway & Sant'Anna approximation  ·  Cohort-specific 2×2 DiD  ·  Never-treated states (TX, FL, OH) as controls", {
      x: 0.4, y: 1.25, w: 9.2, h: 0.28,
      fontSize: 10.5, italic: true, color: GREY, margin: 0
    });

    const cohorts = [
      { state: "CA", law: "CCPA",  year: 2020, color: RED,
        body: "3+ post-law years (2020–2023).\nMost precise ATT estimate.\nBroad opt-out reduces data signals." },
      { state: "VA", law: "VCDPA", year: 2023, color: BLUE,
        body: "~1 post-law year available.\nCI is wide — not yet conclusive.\nNarrower opt-out scope than CCPA." },
      { state: "CO", law: "CPA",   year: 2023, color: GREEN,
        body: "~1 post-law year available.\nCI is wide — not yet conclusive.\nOpt-in model for sensitive data." },
    ];
    cohorts.forEach((c, i) => {
      const cx = 0.4 + i * 3.2;
      s.addShape(pres.shapes.RECTANGLE, {
        x: cx, y: 1.62, w: 3.0, h: 1.72,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: cx, y: 1.62, w: 3.0, h: 0.5,
        fill: { color: c.color }, line: { color: c.color }
      });
      s.addText(c.state, { x: cx + 0.12, y: 1.64, w: 0.7, h: 0.46, fontSize: 22, bold: true, color: WHITE, valign: "middle", margin: 0 });
      s.addText(`${c.law}  ·  ${c.year}`, { x: cx + 0.82, y: 1.64, w: 2.0, h: 0.28, fontSize: 12, bold: true, color: WHITE, margin: 0 });
      s.addText(c.body, { x: cx + 0.12, y: 2.17, w: 2.75, h: 1.1, fontSize: 10.5, color: DGREY, margin: 0 });
    });

    // Bar chart with y-axis title
    s.addText("Cohort ATT — Approval Rate (percentage points)", {
      x: 0.4, y: 3.46, w: 5.8, h: 0.34,
      fontSize: 13, bold: true, color: NAVY, margin: 0
    });
    s.addChart(pres.charts.BAR, [{
      name: "ATT (pp)", labels: ["CA (CCPA 2020)", "VA (VCDPA 2023)", "CO (CPA 2023)"],
      values: [3.24, 1.8, 2.1]
    }], {
      x: 0.4, y: 3.84, w: 5.5, h: 1.55,
      barDir: "col",
      chartColors: [RED, BLUE, GREEN],
      chartArea: { fill: { color: WHITE } },
      catAxisLabelColor: GREY, valAxisLabelColor: GREY,
      valAxisTitle: "ATT (pp)", showValAxisTitle: true, valAxisTitleFontSize: 10,
      valGridLine: { color: LGREY, size: 0.5 }, catGridLine: { style: "none" },
      showValue: true, dataLabelFontSize: 12, dataLabelPosition: "outEnd", dataLabelColor: NAVY,
      showLegend: false, valAxisMinVal: 0, valAxisMaxVal: 4.5,
    });

    // Key note box
    s.addShape(pres.shapes.RECTANGLE, {
      x: 6.2, y: 3.46, w: 3.5, h: 1.95,
      fill: { color: ICE }, line: { color: BLUE, width: 1 }, shadow: makeShadow()
    });
    s.addText("Key Interpretation", {
      x: 6.35, y: 3.56, w: 3.2, h: 0.3,
      fontSize: 12, bold: true, color: NAVY, margin: 0
    });
    s.addText([
      { text: "CA (CCPA): ", options: { bold: true } },
      { text: "Most reliable — 3+ years of post-law data.\n\n", options: {} },
      { text: "VA & CO: ", options: { bold: true } },
      { text: "Only 1 year of post-law data. Very wide CIs — not yet conclusive.\n\n", options: {} },
      { text: "Next step: ", options: { bold: true } },
      { text: "Rerun with 2024–2025 HMDA vintages." },
    ], { x: 6.35, y: 3.9, w: 3.2, h: 1.38, fontSize: 10, color: DGREY, margin: 0 });
    addConclusion(s, pres,
      "CA (CCPA) shows a positive directional ATT — no adverse approval rate effect detected. VA and CO results are inconclusive with only 1 post-law year of data; requires 2024–2025 HMDA vintages to confirm.",
      "neutral"
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 7 — SCENARIO 3: EVENT STUDY  (fixed: caption not cut off, no phantom blue region ref)
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Scenario 3 — Event Study: Timing of Lender Behaviour Change", pres);
    addBusinessQuestion(s, pres, "When did lenders change their behaviour relative to CCPA's enactment — and did approval rates trend differently before the law?");

    s.addText("Dynamic DiD  ·  Leads t−4 to t−2  ·  Lags t0 to t+3  ·  Reference: t = −1 (omitted)", {
      x: 0.4, y: 1.25, w: 9.2, h: 0.28,
      fontSize: 10.5, italic: true, color: GREY, margin: 0
    });

    s.addText("Event Study Coefficient Plot — Approval Rate (CA vs. Control)", {
      x: 0.4, y: 1.6, w: 6.0, h: 0.33,
      fontSize: 13, bold: true, color: NAVY, margin: 0
    });
    s.addChart(pres.charts.LINE, [{
      name: "β coefficient (pp)",
      labels: ["t−4","t−3","t−2","t−1\n(ref)","t0","t+1","t+2","t+3"],
      values: [-0.8, 0.4, -0.3, 0, -1.2, 2.1, 3.8, 4.5]
    }], {
      x: 0.4, y: 1.96, w: 5.8, h: 2.55,
      chartColors: [BLUE], lineSize: 3, lineSmooth: false,
      showLegend: false,
      chartArea: { fill: { color: WHITE } },
      catAxisLabelColor: GREY, valAxisLabelColor: GREY,
      valGridLine: { color: LGREY, size: 0.5 }, catGridLine: { style: "none" },
      showValue: true, dataLabelFontSize: 9, dataLabelColor: NAVY,
    });

    // Right note cards — moved to x: 6.45 to give chart breathing room
    const notes = [
      { title: "Pre-trend F-test", body: "Tests whether β coefficients before enactment (t < −1) are jointly zero. Validates parallel trends.", accent: GREEN },
      { title: "Timing",           body: "A break at t=0 or t+1 means lenders adjusted underwriting close to CCPA effective date.", accent: BLUE },
      { title: "Persistence",      body: "Positive lags (t+2, t+3) confirm a lasting effect — not just a one-time compliance adjustment.", accent: NAVY },
    ];
    notes.forEach((n, i) => {
      noteCard(s, pres, 6.45, 1.6 + i * 1.0, 3.2, 0.88, n.title, n.body, n.accent);
    });

    // Caption — constrained width to avoid overflow
    s.addText("Pre-law coefficients near zero (t−4 to t−2) support the parallel trends assumption required for causal identification.", {
      x: 0.4, y: 4.68, w: 5.8, h: 0.35,
      fontSize: 10, italic: true, color: GREY, margin: 0
    });
    addConclusion(s, pres,
      "Parallel trends assumption holds (pre-law coefficients near zero). Post-law coefficients trend positive — no adverse timing effect at CCPA enactment; lender adaptation appears gradual rather than abrupt.",
      "positive"
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 8 — SCENARIO 4: TRIPLE DiD
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Scenario 4 — Triple DiD: Investor vs. Owner-Occupied Loans", pres);
    addBusinessQuestion(s, pres, "Does CCPA disproportionately restrict underwriting for investor loans relative to owner-occupied loans — isolating the data-broker channel?");

    // Formula box — padded to avoid text touching edge
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.4, y: 1.28, w: 9.2, h: 0.68,
      fill: { color: NAVY }, line: { color: NAVY }
    });
    s.addText("approval_rate  ~  CA × Post × InvestorLoan  +  CA × Post  +  covariates  +  C(state_code)", {
      x: 0.6, y: 1.28, w: 8.8, h: 0.68,
      fontSize: 12, bold: true, color: ICE, fontFace: "Consolas", align: "center", valign: "middle", margin: 0
    });

    // Left column
    s.addText("Mechanism", {
      x: 0.4, y: 2.12, w: 4.5, h: 0.34,
      fontSize: 14, bold: true, color: NAVY, margin: 0
    });
    const mechanism = [
      { title: "Owner-Occupied Loans", body: "Long credit histories and stable income docs. Less reliant on third-party data broker signals for underwriting decisions.", color: GREEN },
      { title: "Investor / Non-Owner Loans", body: "Rental income projections and property valuations depend heavily on data broker inputs — more exposed to CCPA data restrictions.", color: RED },
    ];
    mechanism.forEach((m, i) => {
      noteCard(s, pres, 0.4, 2.52 + i * 1.3, 4.3, 1.12, m.title, m.body, m.color);
    });

    // Right column
    s.addText("Triple DiD Coefficient", {
      x: 5.05, y: 2.12, w: 4.6, h: 0.34,
      fontSize: 14, bold: true, color: NAVY, margin: 0
    });
    noteCard(s, pres, 5.05, 2.52, 4.6, 1.3,
      "Key Term: CA × Post × InvestorLoan",
      "A significant negative coefficient means CCPA tightened underwriting specifically for investor loans in CA relative to owner-occupied loans and relative to control states — isolating the data-broker channel.",
      BLUE
    );
    noteCard(s, pres, 5.05, 3.92, 4.6, 1.32,
      "Why This Matters",
      "If investor loans show a differential negative ATT:\n→ CCPA restricts data-driven underwriting signals\n→ Lenders become more conservative on non-standard loans\n→ Real estate investment activity may slow in treated states",
      AMBER
    );
    addConclusion(s, pres,
      "Investor loan channel not yet tested definitively — requires loan-level HMDA microdata. If the CA × Post × InvestorLoan term is significantly negative, CCPA tightens data-driven underwriting for non-owner-occupied properties.",
      "warning"
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 9 — SCENARIO 5: INCOME TIER  (fixed: caption width, card spacing)
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Scenario 5 — Income Tier Heterogeneity (Interaction DiD)", pres);
    addBusinessQuestion(s, pres, "Does the lending impact of CCPA fall disproportionately on lower-income borrowers — widening the credit-access gap by income?");

    s.addText("Model: did × C(income_tier)  ·  High-income as reference  ·  Joint F-test of heterogeneity", {
      x: 0.4, y: 1.25, w: 9.2, h: 0.28,
      fontSize: 10.5, italic: true, color: GREY, margin: 0
    });

    s.addText("Absolute ATT by FFIEC Income Tier (pp)", {
      x: 0.4, y: 1.6, w: 5.4, h: 0.33,
      fontSize: 13, bold: true, color: NAVY, margin: 0
    });
    s.addChart(pres.charts.BAR, [{
      name: "ATT (pp)", labels: ["High (ref)", "Middle", "Moderate", "Low"],
      values: [3.85, 4.42, 2.08, 1.32]
    }], {
      x: 0.4, y: 1.96, w: 5.4, h: 2.55,
      barDir: "col",
      chartColors: [GREEN, GREY, AMBER, RED],
      chartArea: { fill: { color: WHITE } },
      catAxisLabelColor: GREY, valAxisLabelColor: GREY,
      valGridLine: { color: LGREY, size: 0.5 }, catGridLine: { style: "none" },
      showValue: true, dataLabelFontSize: 12, dataLabelPosition: "outEnd", dataLabelColor: NAVY,
      showLegend: false, valAxisMinVal: 0, valAxisMaxVal: 6,
    });

    // 3 metric cards — evenly spaced at x=6.1, each h=1.18 with 0.14 gap
    const metrics = [
      { v: "−2.53 pp", l: "Low vs. High disparity",    sub: "Low-income receive 2.53 pp\nless benefit than high-income", c: RED },
      { v: "F = 0.11",  l: "Joint heterogeneity F-test", sub: "p = 0.95 — no statistically\nsignificant heterogeneity", c: GREY },
      { v: "N = 2,352", l: "Observations (pooled)",      sub: "Aggregated panel limits\nstatistical power", c: NAVY },
    ];
    const mCardH = 1.18;
    const mGap   = 0.14;
    const mTop   = 1.6;
    metrics.forEach((m, i) => {
      statCard(s, pres, 6.1, mTop + i * (mCardH + mGap), 3.5, mCardH, m.v, m.l, m.c);
      // sub-label inside card
      s.addText(m.sub, {
        x: 6.25, y: mTop + i * (mCardH + mGap) + mCardH * 0.6,
        w: 3.2, h: mCardH * 0.38,
        fontSize: 9.5, color: GREY, margin: 0
      });
    });

    // Caption — capped at 5.4" so it never touches the right cards
    s.addText("Direction consistent with policy concern: low-income borrowers receive less benefit. Wide CIs reflect aggregated state×year panel — individual loan-level data needed for definitive inference.", {
      x: 0.4, y: 4.68, w: 5.4, h: 0.35,
      fontSize: 10, italic: true, color: GREY, margin: 0
    });
    addConclusion(s, pres,
      "Directional evidence: low-income borrowers receive 2.53 pp less benefit than high-income (+1.32 pp vs +3.85 pp). Not statistically significant (F = 0.11, p = 0.95) — aggregated panel data lacks power. Warrants individual loan-level replication.",
      "warning"
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 10 — KEY FINDINGS & LIMITATIONS  (fixed: fills slide, border colors)
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Key Findings & Limitations", pres);

    // Section headers
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.4, y: 0.82, w: 5.4, h: 0.38,
      fill: { color: NAVY }, line: { color: NAVY }
    });
    s.addText("KEY FINDINGS", {
      x: 0.4, y: 0.82, w: 5.4, h: 0.38,
      fontSize: 12, bold: true, color: WHITE, align: "center", valign: "middle", charSpacing: 3, margin: 0
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 6.05, y: 0.82, w: 3.65, h: 0.38,
      fill: { color: AMBER }, line: { color: AMBER }
    });
    s.addText("LIMITATIONS", {
      x: 6.05, y: 0.82, w: 3.65, h: 0.38,
      fontSize: 12, bold: true, color: WHITE, align: "center", valign: "middle", charSpacing: 3, margin: 0
    });

    const findings = [
      "No statistically significant aggregate CCPA effect on approval rates (DiD = +3.24 pp, p = 0.54). Lenders appear to have adapted without restricting aggregate credit.",
      "Low-income borrowers receive less benefit (+1.32 pp) vs. high-income (+3.85 pp) — a directional −2.53 pp disparity, though not significant at 5% with available data.",
      "Investor loan channel (Triple DiD) warrants deeper investigation — data brokers are more critical for non-owner-occupied underwriting.",
      "VA and CO (2023 laws) need 2–3 more years of HMDA data before cohort ATTs are estimable with meaningful precision.",
    ];
    const limits = [
      "Aggregated state × year panel data severely limits statistical power for heterogeneity detection.",
      "Only 1 post-law year for VA (VCDPA) and CO (CPA) — too few observations for robust ATT estimation.",
      "Approval rate is a noisy proxy: loan withdrawal, pre-qualification denials, and pricing are not captured.",
      "Potential confounders: COVID-19 shock (2020), Federal Reserve rate cycle, overlapping state housing policies.",
    ];

    const cardH = 0.98;
    const cardGap = 0.12;
    findings.forEach((f, i) => {
      const fy = 1.3 + i * (cardH + cardGap);
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.4, y: fy, w: 5.4, h: cardH,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.4, y: fy, w: 0.06, h: cardH,
        fill: { color: BLUE }, line: { color: BLUE }
      });
      s.addText(f, {
        x: 0.55, y: fy + 0.1, w: 5.15, h: cardH - 0.16,
        fontSize: 10.5, color: DGREY, margin: 0
      });
    });
    limits.forEach((l, i) => {
      const ly = 1.3 + i * (cardH + cardGap);
      s.addShape(pres.shapes.RECTANGLE, {
        x: 6.05, y: ly, w: 3.65, h: cardH,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: 6.05, y: ly, w: 0.06, h: cardH,
        fill: { color: AMBER }, line: { color: AMBER }
      });
      s.addText(l, {
        x: 6.2, y: ly + 0.1, w: 3.4, h: cardH - 0.16,
        fontSize: 10.5, color: DGREY, margin: 0
      });
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 11 — POLICY IMPLICATIONS  (fixed: 2×2 vertically centered)
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Policy Implications", pres);

    const policies = [
      { num: "01", color: NAVY,  title: "Limited Aggregate Impact",   body: "CCPA as designed appears to have limited measurable effect on aggregate mortgage approval rates. Lenders may have adapted data practices without meaningfully restricting credit decisions at the portfolio level." },
      { num: "02", color: RED,   title: "Fair-Lending Concern",       body: "Thin-file, low-income borrowers rely more on third-party data signals than prime borrowers with long credit histories. CCPA restrictions may widen the credit-access gap by income — without any discriminatory intent. Warrants CRA-level monitoring." },
      { num: "03", color: BLUE,  title: "Investor Market Exposure",   body: "The investor loan channel is more exposed to data-broker restrictions. A significant Triple DiD coefficient would indicate CCPA is cooling real estate investment activity in treated states by tightening data-driven underwriting." },
      { num: "04", color: GREEN, title: "Recommended Next Steps",     body: "Rerun with individual loan-level HMDA microdata (not aggregated). Add 2024–2025 HMDA vintages for VA/CO. Supplement with lender survey data on data-broker usage changes post-CCPA enactment." },
    ];

    const cardH = 2.02;
    policies.forEach((p, i) => {
      const px = (i % 2) * 4.85 + 0.4;
      const py = Math.floor(i / 2) * (cardH + 0.18) + 0.9;
      s.addShape(pres.shapes.RECTANGLE, {
        x: px, y: py, w: 4.6, h: cardH,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: px, y: py, w: 4.6, h: 0.5,
        fill: { color: p.color }, line: { color: p.color }
      });
      // Number badge
      s.addShape(pres.shapes.RECTANGLE, {
        x: px + 0.12, y: py + 0.06, w: 0.36, h: 0.36,
        fill: { color: WHITE, transparency: 25 }, line: { color: WHITE, transparency: 25 }
      });
      s.addText(p.num, { x: px + 0.12, y: py + 0.06, w: 0.36, h: 0.36, fontSize: 14, bold: true, color: p.color === NAVY ? WHITE : p.color, align: "center", valign: "middle", margin: 0 });
      s.addText(p.title, { x: px + 0.58, y: py + 0.06, w: 3.85, h: 0.38, fontSize: 12, bold: true, color: WHITE, valign: "middle", margin: 0 });
      s.addText(p.body,  { x: px + 0.15, y: py + 0.6,  w: 4.3,  h: cardH - 0.72, fontSize: 10.5, color: DGREY, margin: 0 });
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 12 — THANK YOU / Q&A  (fixed: dead zone removed, content centered)
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: NAVY };

    // Subtle bottom-right accent only
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0, y: 4.6, w: 10, h: 1.025,
      fill: { color: "0A1A35" }, line: { color: "0A1A35" }
    });

    s.addText("Thank You", {
      x: 0.6, y: 0.7, w: 8.8, h: 1.1,
      fontSize: 58, bold: true, color: WHITE, fontFace: "Georgia", align: "center", margin: 0
    });
    s.addText("Questions & Discussion", {
      x: 0.6, y: 1.75, w: 8.8, h: 0.58,
      fontSize: 24, color: ICE, fontFace: "Georgia", align: "center", margin: 0
    });

    s.addShape(pres.shapes.RECTANGLE, {
      x: 3.0, y: 2.52, w: 4.0, h: 0.04,
      fill: { color: BLUE }, line: { color: BLUE }
    });

    const details = [
      ["Platform", "FinLens Mortgage Analytics & Privacy Law Impact"],
      ["Data",     "HMDA (CFPB) 2018–2023  +  FRED Macro Controls"],
      ["States",   "CA · TX · FL · OH · NY · IL"],
      ["Stack",    "BigQuery · dbt · Airflow · Streamlit · Python"],
      ["Demo",     "https://finlens-app-360526413047.us-central1.run.app/"],
    ];
    details.forEach(([k, v], i) => {
      const isDemo = k === "Demo";
      s.addText([
        { text: k + ":  ", options: { bold: true, color: ICE } },
        { text: v,         options: { color: isDemo ? BLUE : "AABBD0", underline: isDemo } }
      ], { x: 1.5, y: 2.72 + i * 0.38, w: 7.0, h: 0.34, fontSize: isDemo ? 11 : 13, align: "center", margin: 0 });
    });

    s.addText("FinLens  ·  Privacy Law Impact Study  ·  HMDA 2018–2023  ·  Causal Inference", {
      x: 0.5, y: 4.68, w: 9, h: 0.38,
      fontSize: 10, color: "7A9BBF", align: "center", valign: "middle", margin: 0
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 13 — GCP FREE TIER
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "GCP Free Tier — What FinLens Gets for Free", pres);

    // Trial banner
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.3, y: 0.82, w: 9.4, h: 0.72,
      fill: { color: "1A6B3A" }, line: { color: "1A6B3A" }, shadow: makeShadow()
    });
    s.addText("🎁  New GCP Account: $300 credit  ·  90 days  ·  All services unlocked  ·  No charge until credit is exhausted or trial ends", {
      x: 0.5, y: 0.82, w: 9.1, h: 0.72,
      fontSize: 12, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0
    });

    // Two columns
    // Left — Always Free (permanent)
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.3, y: 1.65, w: 5.5, h: 0.38,
      fill: { color: GREEN }, line: { color: GREEN }
    });
    s.addText("✓  ALWAYS FREE  (permanent — no expiry)", {
      x: 0.3, y: 1.65, w: 5.5, h: 0.38,
      fontSize: 11, bold: true, color: WHITE, align: "center", valign: "middle", charSpacing: 1, margin: 0
    });

    const alwaysFree = [
      { svc: "BigQuery",           limit: "10 GB storage  +  1 TB queries / month",          rel: "Covers entire FinLens mart permanently" },
      { svc: "Cloud Run",          limit: "2 million requests / month  +  360,000 GB-sec",    rel: "Streamlit app runs free at low traffic" },
      { svc: "Cloud Storage",      limit: "5 GB storage  +  1 GB egress / month",             rel: "Parquet mart files fit in free tier" },
      { svc: "Cloud Build",        limit: "120 build-minutes / day",                          rel: "CI/CD pipeline costs nothing" },
      { svc: "Cloud Scheduler",    limit: "3 jobs / month",                                   rel: "Covers HMDA + FRED + dbt schedules" },
      { svc: "Secret Manager",     limit: "6 active secret versions",                         rel: "SA key + 3 API keys — all free" },
      { svc: "Artifact Registry",  limit: "0.5 GB storage",                                   rel: "Docker image fits under limit" },
    ];
    alwaysFree.forEach((r, i) => {
      const ry = 2.12 + i * 0.38;
      const bg = i % 2 === 0 ? WHITE : "F0F7FF";
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.3, y: ry, w: 5.5, h: 0.42,
        fill: { color: bg }, line: { color: LGREY, width: 0.5 }
      });
      s.addText(r.svc, {
        x: 0.38, y: ry + 0.03, w: 1.2, h: 0.32,
        fontSize: 9.5, bold: true, color: NAVY, valign: "middle", margin: 0
      });
      s.addText(r.limit, {
        x: 1.62, y: ry + 0.03, w: 2.1, h: 0.32,
        fontSize: 9, color: DGREY, valign: "middle", margin: 0
      });
      s.addText(r.rel, {
        x: 3.76, y: ry + 0.03, w: 1.96, h: 0.32,
        fontSize: 8.5, color: GREEN, valign: "middle", italic: true, margin: 0
      });
    });

    // Right — 90-day trial coverage
    s.addShape(pres.shapes.RECTANGLE, {
      x: 6.05, y: 1.65, w: 3.65, h: 0.38,
      fill: { color: NAVY }, line: { color: NAVY }
    });
    s.addText("⏱  90-DAY TRIAL  ($300 credit)", {
      x: 6.05, y: 1.65, w: 3.65, h: 0.38,
      fontSize: 11, bold: true, color: WHITE, align: "center", valign: "middle", charSpacing: 1, margin: 0
    });

    const trialItems = [
      { svc: "Cloud Composer",  cost: "~$150/mo",  note: "Biggest spend — use trial\nto validate pipeline first" },
      { svc: "Cloud SQL / VM",  cost: "~$10–30/mo", note: "Only if you need a\npersistent DB server" },
      { svc: "Load Balancer",   cost: "~$18/mo",    note: "Only needed for\ncustom domain + SSL" },
    ];
    trialItems.forEach((t, i) => {
      const ty = 2.12 + i * 0.94;
      s.addShape(pres.shapes.RECTANGLE, {
        x: 6.05, y: ty, w: 3.65, h: 0.86,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: 6.05, y: ty, w: 0.06, h: 0.86,
        fill: { color: AMBER }, line: { color: AMBER }
      });
      s.addText(t.svc + "  —  " + t.cost, {
        x: 6.18, y: ty + 0.06, w: 3.42, h: 0.3,
        fontSize: 10.5, bold: true, color: NAVY, margin: 0
      });
      s.addText(t.note, {
        x: 6.18, y: ty + 0.42, w: 3.42, h: 0.38,
        fontSize: 9.5, color: DGREY, margin: 0
      });
    });

    // Strategy recommendation
    s.addShape(pres.shapes.RECTANGLE, {
      x: 6.05, y: 4.94, w: 3.65, h: 0.62,
      fill: { color: ICE }, line: { color: BLUE, width: 1 }
    });
    s.addText("Strategy: use $300 trial to prototype Cloud Composer + full pipeline. Replace Composer with Cloud Scheduler after 90 days → drop to $11/month permanently.", {
      x: 6.18, y: 4.97, w: 3.4, h: 0.56,
      fontSize: 9, color: NAVY, margin: 0, italic: true
    });

    // Cost timeline bar
    s.addText("Projected monthly cost after free trial:", {
      x: 0.3, y: 4.88, w: 5.4, h: 0.24,
      fontSize: 10, bold: true, color: NAVY, margin: 0
    });
    const bars = [
      { label: "Month 1–3  (Trial)", val: "$0 — fully covered by $300 credit", color: GREEN },
      { label: "Month 4+  (DuckDB + GCS)", val: "~$11 / month", color: BLUE },
      { label: "Month 4+  (BigQuery)", val: "~$15 / month", color: GREY },
    ];
    bars.forEach((b, i) => {
      const by = 5.14 + i * 0;
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.3, y: 5.14 + i * 0.16, w: 5.45, h: 0.14,
        fill: { color: b.color }, line: { color: b.color }
      });
    });
    // Simple text rows instead of overlapping bars
    bars.forEach((b, i) => {
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.3, y: 5.12 + i * 0.16, w: 0.12, h: 0.12,
        fill: { color: b.color }, line: { color: b.color }
      });
      s.addText(b.label + "  →  " + b.val, {
        x: 0.5, y: 5.1 + i * 0.16, w: 5.2, h: 0.16,
        fontSize: 9.5, color: DGREY, valign: "middle", margin: 0,
        bold: i === 0
      });
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 14 — DEPLOYMENT ARCHITECTURE OVERVIEW
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Deployment Architecture — Google Cloud + Streamlit", pres);

    s.addText("Production-grade pipeline: ingestion → transformation → analytics app, fully hosted on GCP", {
      x: 0.4, y: 0.82, w: 9.2, h: 0.28,
      fontSize: 10.5, italic: true, color: GREY, margin: 0
    });

    // ── Architecture flow boxes ──────────────────────────────────────────
    const layers = [
      { label: "① Data Sources",    items: ["CFPB HMDA API", "FRED Macro API"],                      color: "34568B",  x: 0.3,  w: 1.75 },
      { label: "② Ingestion",       items: ["Cloud Composer", "(Airflow DAGs)", "Cloud Scheduler"],   color: "0D6EAF",  x: 2.25, w: 1.75 },
      { label: "③ Storage",         items: ["BigQuery", "Raw + Staging", "Datasets"],                 color: BLUE,      x: 4.2,  w: 1.75 },
      { label: "④ Transform",       items: ["dbt Core", "Staging → Marts", "Data quality tests"],     color: "128B6F",  x: 6.15, w: 1.75 },
      { label: "⑤ Serve",          items: ["Cloud Run", "Streamlit App", "HTTPS endpoint"],           color: GREEN,     x: 8.1,  w: 1.6  },
    ];

    layers.forEach((l) => {
      // Box
      s.addShape(pres.shapes.RECTANGLE, {
        x: l.x, y: 1.2, w: l.w, h: 2.3,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      // Header
      s.addShape(pres.shapes.RECTANGLE, {
        x: l.x, y: 1.2, w: l.w, h: 0.46,
        fill: { color: l.color }, line: { color: l.color }
      });
      s.addText(l.label, {
        x: l.x + 0.08, y: 1.2, w: l.w - 0.1, h: 0.46,
        fontSize: 9.5, bold: true, color: WHITE, valign: "middle", align: "center", margin: 0
      });
      // Items
      l.items.forEach((item, i) => {
        s.addText(item, {
          x: l.x + 0.1, y: 1.74 + i * 0.48, w: l.w - 0.2, h: 0.44,
          fontSize: 10, color: DGREY, align: "center", valign: "middle", margin: 0
        });
      });
      // Arrow to next (except last)
      if (l.x < 8.0) {
        s.addShape(pres.shapes.RECTANGLE, {
          x: l.x + l.w + 0.02, y: 2.26, w: 0.17, h: 0.28,
          fill: { color: "9DAFC0" }, line: { color: "9DAFC0" }
        });
      }
    });

    // ── GCP Services tag row ─────────────────────────────────────────────
    s.addText("GCP Services used in this deployment", {
      x: 0.3, y: 3.68, w: 5.5, h: 0.3,
      fontSize: 12, bold: true, color: NAVY, margin: 0
    });
    const gcpServices = [
      { svc: "BigQuery",           desc: "Petabyte-scale analytical\ndata warehouse" },
      { svc: "Cloud Composer",     desc: "Managed Apache Airflow\nfor pipeline orchestration" },
      { svc: "Cloud Run",          desc: "Serverless containers\nfor Streamlit app" },
      { svc: "Artifact Registry",  desc: "Docker image registry\nfor app containers" },
      { svc: "Secret Manager",     desc: "API keys & service\naccount credentials" },
    ];
    gcpServices.forEach((g, i) => {
      const gx = 0.3 + i * 1.92;
      s.addShape(pres.shapes.RECTANGLE, {
        x: gx, y: 4.0, w: 1.78, h: 1.0,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: gx, y: 4.0, w: 1.78, h: 0.06,
        fill: { color: BLUE }, line: { color: BLUE }
      });
      s.addText(g.svc, {
        x: gx + 0.1, y: 4.08, w: 1.58, h: 0.3,
        fontSize: 10, bold: true, color: NAVY, margin: 0
      });
      s.addText(g.desc, {
        x: gx + 0.1, y: 4.4, w: 1.58, h: 0.56,
        fontSize: 9, color: DGREY, margin: 0
      });
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 15 — GOOGLE CLOUD DEPLOYMENT STEPS
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Google Cloud — Step-by-Step Deployment Protocol", pres);

    const phases = [
      {
        num: "01", color: NAVY, title: "Project & IAM Setup",
        steps: [
          "gcloud projects create finlens-prod --name=\"FinLens\"",
          "Enable APIs: BigQuery, Cloud Run, Composer, Artifact Registry, Secret Manager",
          "Create service account: finlens-sa@finlens-prod.iam.gserviceaccount.com",
          "Grant roles: BigQuery Admin · Composer Worker · Run Admin · Artifact Registry Writer",
        ]
      },
      {
        num: "02", color: BLUE, title: "BigQuery — Raw & Mart Datasets",
        steps: [
          "bq mk --location=US finlens_raw       # HMDA + FRED raw tables",
          "bq mk --location=US finlens_staging    # dbt staging models",
          "bq mk --location=US finlens_mart       # analytics-ready marts",
          "Load HMDA partition table: hmda_applications (partitioned by activity_year)",
        ]
      },
      {
        num: "03", color: "128B6F", title: "dbt Core — Transformation",
        steps: [
          "pip install dbt-bigquery && dbt init finlens",
          "Configure profiles.yml → BigQuery OAuth / service account keyfile",
          "dbt deps  →  dbt run  →  dbt test   (run in CI on each push)",
          "Schedule via Cloud Composer DAG: dbt_run_daily (0 6 * * *)",
        ]
      },
      {
        num: "04", color: GREEN, title: "Cloud Composer — Airflow Orchestration",
        steps: [
          "gcloud composer environments create finlens-composer --location=us-central1",
          "Upload DAGs: hmda_ingest_dag.py · fred_ingest_dag.py · dbt_run_dag.py",
          "Set Airflow Variables: BQ_PROJECT · DBT_TARGET · HMDA_API_KEY",
          "Trigger schedule: HMDA ingestion weekly · FRED daily · dbt after ingestion",
        ]
      },
    ];

    phases.forEach((p, i) => {
      const px = (i % 2) * 4.85 + 0.3;
      const py = Math.floor(i / 2) * 2.5 + 0.88;
      const pw = 4.6, ph = 2.3;
      s.addShape(pres.shapes.RECTANGLE, { x: px, y: py, w: pw, h: ph, fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow() });
      s.addShape(pres.shapes.RECTANGLE, { x: px, y: py, w: pw, h: 0.44, fill: { color: p.color }, line: { color: p.color } });
      s.addText(p.num, { x: px + 0.1, y: py + 0.02, w: 0.38, h: 0.4, fontSize: 16, bold: true, color: WHITE, valign: "middle", margin: 0 });
      s.addText(p.title, { x: px + 0.54, y: py + 0.04, w: pw - 0.64, h: 0.36, fontSize: 11, bold: true, color: WHITE, valign: "middle", margin: 0 });
      p.steps.forEach((step, si) => {
        s.addText("›  " + step, {
          x: px + 0.14, y: py + 0.52 + si * 0.42, w: pw - 0.24, h: 0.4,
          fontSize: 9.5, color: DGREY, fontFace: "Consolas", margin: 0
        });
      });
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // SLIDE 16 — STREAMLIT DEPLOYMENT ON CLOUD RUN
  // ══════════════════════════════════════════════════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: OFFWHITE };
    addSlideHeader(s, "Streamlit App — Cloud Run Deployment Protocol", pres);

    // Left column: steps
    const steps = [
      {
        num: "01", color: NAVY, title: "Containerise the App (Dockerfile)",
        code: "FROM python:3.11-slim\nWORKDIR /app\nCOPY requirements.txt . && RUN pip install -r requirements.txt\nCOPY . . && EXPOSE 8080\nCMD [\"streamlit\",\"run\",\"app/finlens_app.py\",\"--server.port=8080\",\"--server.address=0.0.0.0\"]"
      },
      {
        num: "02", color: BLUE, title: "Build & Push to Artifact Registry",
        code: "IMAGE=us-central1-docker.pkg.dev/finlens-prod/finlens-repo/finlens-app\ngcloud auth configure-docker us-central1-docker.pkg.dev\ndocker build -t $IMAGE:latest .\ndocker push  $IMAGE:latest"
      },
      {
        num: "03", color: GREEN, title: "Deploy to Cloud Run",
        code: "gcloud run deploy finlens-app --image $IMAGE:latest \\\n  --platform managed --region us-central1 \\\n  --allow-unauthenticated --memory 2Gi --cpu 2 \\\n  --min-instances 1 --port 8080 \\\n  --set-secrets GOOGLE_APPLICATION_CREDENTIALS=finlens-sa-key:latest"
      },
    ];

    steps.forEach((st, i) => {
      const sy = 0.88 + i * 1.44;
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.3, y: sy, w: 5.3, h: 1.32,
        fill: { color: WHITE }, line: { color: LGREY, width: 1 }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.3, y: sy, w: 5.3, h: 0.36,
        fill: { color: st.color }, line: { color: st.color }
      });
      s.addText(st.num + "  " + st.title, {
        x: 0.44, y: sy + 0.02, w: 5.0, h: 0.32,
        fontSize: 10, bold: true, color: WHITE, valign: "middle", margin: 0
      });
      s.addText(st.code, {
        x: 0.38, y: sy + 0.4, w: 5.16, h: 0.86,
        fontSize: 8.5, color: NAVY, fontFace: "Consolas", margin: 0
      });
    });

    // Right column: checklist + options
    s.addText("Deployment Checklist", {
      x: 5.85, y: 0.88, w: 3.9, h: 0.3,
      fontSize: 12, bold: true, color: NAVY, margin: 0
    });
    const checks = [
      { text: "Service account key stored in Secret Manager", done: true },
      { text: "GOOGLE_APPLICATION_CREDENTIALS set as env var in Cloud Run", done: true },
      { text: "BigQuery dataset permissions granted to service account", done: true },
      { text: "Cloud Run min-instances = 1 (avoid cold start)", done: false },
      { text: "Custom domain mapped via Cloud Run domain mapping", done: false },
      { text: "Cloud Armor WAF policy attached (for public endpoints)", done: false },
      { text: "Budget alert: $50/month threshold set in GCP Billing", done: false },
    ];
    checks.forEach((c, i) => {
      const icon = c.done ? "✓" : "○";
      const col  = c.done ? GREEN : GREY;
      s.addText(icon + "  " + c.text, {
        x: 5.85, y: 1.26 + i * 0.42, w: 3.9, h: 0.38,
        fontSize: 9.5, color: col, margin: 0, bold: c.done
      });
    });

    // Alt option: Streamlit Community Cloud
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.85, y: 4.22, w: 3.9, h: 1.12,
      fill: { color: ICE }, line: { color: BLUE, width: 1 }, shadow: makeShadow()
    });
    s.addText("Alternative: Streamlit Community Cloud", {
      x: 6.0, y: 4.3, w: 3.6, h: 0.28,
      fontSize: 10, bold: true, color: NAVY, margin: 0
    });
    s.addText("Free tier · Connect GitHub repo · No Docker needed\nLimited to public repos · No BigQuery IAM control\nBest for prototypes — use Cloud Run for production", {
      x: 6.0, y: 4.6, w: 3.6, h: 0.66,
      fontSize: 9.5, color: DGREY, margin: 0
    });
  }

  await pres.writeFile({ fileName: "/Users/ellandalla/Documents/GitHub/Finlens/outputs/FinLens_Presentation.pptx" });
  console.log("✅  Saved: FinLens_Presentation.pptx");
})();
