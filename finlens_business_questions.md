# FinLens — Business Questions by Analytical Case

> **Context:** All five cases use HMDA Loan Application Register (LAR) data merged with FRED
> macroeconomic series to isolate the causal effect of state-level consumer data-privacy laws
> (CCPA, VCDPA, CPA) on mortgage market outcomes — origination rates, loan amounts, denial
> reasons, and lender behavior.

---

## Case 1 — Standard 2×2 Difference-in-Differences
**Method:** Hw, California (treated) vs. Texas / Florida / Ohio (control), pre/post CCPA (Jan 1 2020)

### Business Question
> **Did the California Consumer Privacy Act measurably change mortgage lending outcomes in
> California relative to comparable non-adopting states, and if so, by how much?**

**What "change" means operationally:**
- Did origination approval rates rise or fall after CCPA took effect in CA vs. TX/FL/OH?
- Did average loan amounts shift, suggesting lenders re-priced credit-risk differently once
  consumer data access was restricted?
- Did denial rates on grounds of *credit history* or *insufficient collateral* increase,
  consistent with lenders having less behavioural signal to underwrite?

**Who cares:** Compliance officers estimating the business cost of a new state privacy law;
regulators assessing whether CCPA created unintended credit-access barriers.

**Identifying assumption:** In the absence of CCPA, California lending outcomes would have
trended in parallel with TX/FL/OH. HC3 standard errors correct for heteroskedasticity common
in loan-level panel data.

---

## Case 2 — Staggered Difference-in-Differences
**Method:** Callaway & Sant'Anna ATT(g,t) estimator, CCPA (CA, 2020) + VCDPA (VA, 2023) + CPA (CO, 2023)

### Business Question
> **Across the wave of state privacy laws enacted between 2020 and 2023, is there a
> consistent, replicable causal effect on mortgage lending — or does the impact vary
> by state, law design, and time since enactment?**

**What this adds over Case 1:**
- Aggregates treatment effects from three separate policy "cohorts" (groups treated at
  different times) without the forbidden comparison of early-treated to late-treated units
  that contaminates classic TWFE estimators.
- Produces a clean ATT(g,t) — the Average Treatment effect on the Treated for cohort *g*
  at time *t* — for each adopting state and each year post-enactment.
- Tests whether VCDPA (narrower opt-out scope) and CPA (opt-in for sensitive data) produce
  different lending effects than the broader CCPA.

**Who cares:** Policy analysts benchmarking draft federal privacy legislation; lenders with
multi-state footprints deciding whether to build one national compliance model or
state-specific ones.

---

## Case 3 — Event Study
**Method:** Dynamic DiD coefficients (leads & lags around enactment date) + pre-trend F-test + coefficient plot

### Business Question
> **When exactly did lender behaviour change relative to the privacy law enactment date —
> and does the timing rule out the possibility that something else caused the shift?**

**What this adds over Cases 1–2:**
- The **pre-trend F-test** formally tests whether treated and control states were already
  diverging *before* the law took effect. A non-significant F-statistic validates the
  parallel-trends assumption underlying Cases 1 and 2.
- **Lead coefficients** (β₋₃, β₋₂, β₋₁) show whether lenders began adjusting underwriting
  ahead of the law — e.g., if CCPA was signed in June 2018 but effective Jan 2020,
  did originations shift in 2019?
- **Lag coefficients** (β₊₁ … β₊ₙ) reveal whether the effect is immediate, delayed
  (lenders need time to rebuild data pipelines), or temporary (lenders adapt and recover).

**Who cares:** General counsels timing compliance investments; economists studying regulatory
anticipation effects; auditors validating that a causal story is not a coincidence.

---

## Case 4 — Triple Difference-in-Differences (DiDiD)
**Method:** Investor loans vs. owner-occupied within CA vs. TX/FL/OH, before vs. after CCPA

### Business Question
> **Did CCPA's restrictions on consumer data specifically harm owner-occupied mortgage
> applicants — who are natural persons with data-privacy rights — more than investor
> borrowers, who are typically LLCs or entities outside the law's personal-data scope?**

**The logic of the third difference:**
- CCPA protects *natural persons'* personal data. An LLC purchasing a rental property is
  not a CCPA-covered consumer; a family buying a primary residence is.
- If CCPA drives the lending effect, it should be concentrated in **owner-occupied** loans.
- Investor loans inside CA vs. control states act as a within-treated-state placebo:
  if investor loans also shift, the driver is something other than CCPA's data restrictions
  (e.g. a California-wide macro shock).
- The DiDiD coefficient isolates: **(CA − control) × (owner-occupied − investor) × (post − pre)**

**Who cares:** CFPB and FHFA analysts distinguishing regulatory impact from market cycles;
lenders deciding whether to apply different data-governance policies to retail vs.
commercial mortgage divisions; fair-lending auditors checking whether privacy compliance
creates disparate impact on homebuyers vs. investors.

---

## Case 5 — Heterogeneous Treatment Effects
**Method:** OLS by income tier (low / moderate / middle / high FFIEC) + EconML CausalForest CATE estimation

### Business Question
> **Does the lending impact of consumer privacy regulation fall disproportionately on
> lower-income borrowers — and if so, which borrower characteristics drive the
> heterogeneity in treatment effects?**

**Two complementary lenses:**

| Lens | Method | What it reveals |
|---|---|---|
| Stratified OLS | Separate DiD regressions per FFIEC income tier | Simple, auditable tier-by-tier ATT comparison |
| CausalForest CATE | EconML non-parametric forest on individual loans | Continuous heterogeneity across income, DTI, LTV, race, geography simultaneously |

**Why this matters most:**
- If CCPA reduces lenders' data access uniformly, standard credit-scoring models become
  noisier for *thin-file* borrowers (often low-income, first-time buyers) more than for
  prime borrowers with long credit histories. Privacy law could therefore widen the credit
  access gap by income even without any discriminatory intent.
- The CausalForest CATE map can flag specific sub-populations (e.g. low-income,
  high-LTV applicants in rural CA counties) where the negative effect is concentrated —
  actionable intelligence for CRA compliance and fair-lending strategy.
- Positive CATE for high-income borrowers combined with negative CATE for low-income
  borrowers would be the most legally and politically significant finding of the entire
  FinLens analysis.

**Who cares:** Fair-lending attorneys; CRA officers; impact investors screening lenders on
equitable access; state AGs evaluating whether CCPA had unintended distributional
consequences that warrant a legislative fix.

---

## Summary Table

| # | Method | Core Causal Question | Primary Audience |
|---|---|---|---|
| 1 | 2×2 DiD (HC3 OLS) | Did CCPA change lending in CA vs. TX/FL/OH? | Compliance, Regulators |
| 2 | Staggered DiD (CS) | Is the effect consistent across all adopting states? | Policy Analysts, Multi-state Lenders |
| 3 | Event Study | When did the effect start — and was it anticipated? | General Counsel, Economists |
| 4 | Triple DiD (DiDiD) | Did CCPA hurt owner-occupants specifically, not investors? | CFPB, Fair-Lending Auditors |
| 5 | Heterogeneous TE (CausalForest) | Who bears the burden — do low-income borrowers lose most? | CRA Officers, Fair-Lending Attorneys |

> Each case builds on the previous: Case 1 establishes the fact, Case 2 generalises it,
> Case 3 validates causality timing, Case 4 identifies the mechanism, Case 5 maps who is
> most affected.
