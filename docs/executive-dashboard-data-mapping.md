---
title: Executive Dashboard Structure — Data Point Mapping
applies_to: defaultProject.pbip (PBI_Sample)
status: draft
---

# Executive Dashboard Structure — Data Point Mapping

This document maps each item in the recommended **Executive Dashboard Structure**
(Investment → Adoption → Productivity → Quality → Business Value → Risk) to the
concrete data points available in this project's semantic model
(`defaultProject.SemanticModel`), so each section of the executive story can be
answered from existing tables/measures, or flagged as a gap.

Legend:
- ✅ Available now — measure/column already exists in the model
- ⚠️ Partially available — related data exists but needs a new measure or assumption
- ❌ Not available — no source data in this project; requires external data (e.g. GitHub API, Azure DevOps, Remedy)

## 1. Investment

| Item | Status | Data Point(s) | Notes |
|---|---|---|---|
| Licences | ✅ | `DimDeveloper` (1 row = 1 assigned seat) → measure `[Assigned Seats]`; `DimBusinessUnit[EligibleDevelopers]` → measure `[Eligible Developers]` | Eligible vs. assigned gives licence utilisation headroom |
| Cost | ✅ | Measures `[Licence Cost]`, `[AI Credit Cost]`, `[Enablement Cost]`, rolled up in `[Copilot Investment]`; rates sourced from `Assumptions` table (`LicenceCostPerSeatMonth`, `AICreditCostPerUnit`, `EnablementCostMonth`) | Cost is modelled from assumptions, not actual billing data — replace with real licence invoice data if/when available |

## 2. Adoption

| Item | Status | Data Point(s) | Notes |
|---|---|---|---|
| Active Users (%) | ✅ | Measure `[Adoption Rate]` = `[Active Users]` ÷ `[Assigned Seats]`; underlying `FactTeamDaily[ActiveUsers]` (peak by team) | Page: `pt-adoption-rate`, `pt-active-users` |
| Adoption Phases | ⚠️ | `ValueChain` table (`StepOrder`/`StepName`: Eligible Developers → Assigned Seats → Active Users → Engaged Users → Sustained Users) + measure `[Value Chain Count]` | This models a funnel, not GitHub's native "adoption phase" taxonomy (code completion → IDE agent → agent-first → multi-agent). To match GitHub's phases exactly, source `copilot/usage` or `copilot/metrics` API adoption-phase fields |
| Agent Adoption | ⚠️ | `FactTeamDaily[AgentSessions]` → measure `[Agent Sessions]`; `FactTeamDaily[CodingAgentPRsCreated]`/`[CodingAgentPRsMerged]` → measures `[Coding Agent PRs Created]`/`[Coding Agent PRs Merged]` | Covers agent usage volume, not yet a %-of-users-using-agents adoption metric |
| Training | ❌ | No training-completion table/column in this model | Needs an external training/LMS source (e.g. Learning Pathways completion data) joined on `DeveloperKey`/`TeamKey` |

## 3. Productivity

| Item | Status | Data Point(s) | Notes |
|---|---|---|---|
| PR Cycle Time | ✅ | `FactTeamDaily[PRCycleTimeHours]` → measure `[Median PR Cycle Time (hrs)]`; baseline delta via `[PR Cycle Time Δ vs Baseline]` | Page: `pt-median-pr-cycle-time-hrs` |
| Deployment Frequency | ✅ | `FactTeamDaily[Deployments]` → measure `[Deployments]`; `FactTeamDaily[FailedDeployments]` → `[Failed Deployments]` | Page: `pt-deployments` |
| Release Frequency | ⚠️ | Same underlying `FactTeamDaily[Deployments]` — treat deployments as proxy for releases unless a separate "release" event/tag exists | No distinct release-train data in model; equate to Deployments or source from pipeline/release manager if tracked separately |
| Hours Saved | ✅ | Measure `[Estimated Hours Saved]` = `[Suggestions Accepted]` × `Assumptions[MinutesSavedPerAcceptedSuggestion]` ÷ 60 | Page: `pt-estimated-hours-saved`; derived/estimated, not measured directly |

Supporting productivity measures also available: `[PRs Merged]`, `[Avg Time to First Review (hrs)]`, `[Avg Lead Time (hrs)]`, `[Throughput per Active Engineer]`, `[Suggestions Made]`, `[Suggestions Accepted]`, `[Code Acceptance Rate]`, `[Lines Accepted]`, `[Chat Sessions]`.

## 4. Quality

| Item | Status | Data Point(s) | Notes |
|---|---|---|---|
| Code Quality | ⚠️ | `FactMonthlyQuality[BuildSuccesses]`/`[BuildRuns]` → `[Build Success Rate]`; `[Flow State Score]`, `[Tooling Satisfaction]`, `[Copilot Satisfaction]` as proxy quality/experience indicators | No static-analysis/code-smell metric in model; add if a SAST/code-quality tool is integrated |
| Defects | ✅ | `FactMonthlyQuality[EscapedDefects]` → measure `[Escaped Defects]` | Page: `pt-escaped-defects` |
| Rework | ✅ | `FactTeamDaily[ReworkedPRs]` → measure `[Reworked PRs]`; rate via `[Rework Rate]` = Reworked PRs ÷ PRs Merged | Page: `pt-rework-rate` |
| MTTR | ✅ | `FactMonthlyQuality[MTTRHours]` → measure `[MTTR (hrs)]` | Page: `pt-mttr-hrs`. MTTR is sourced from Remedy — confirm this table is fed from the same Remedy methodology before treating it as authoritative |
| Compliance | ⚠️ | `FactMonthlyQuality[VulnerabilitiesIntroduced]` → `[Vulnerabilities Introduced]`; `[Change Failure Rate]` (`ChangeFailures`/`TotalChanges`) as a compliance/stability proxy | No explicit policy/licence-compliance flag table; Dependabot/security-scan and policy-compliance data would need to be imported separately |

Also available: `[Test Coverage %]`, `[Test Pass Rate]`, `[Tech Debt Items]`.

## 5. Business Value

| Item | Status | Data Point(s) | Notes |
|---|---|---|---|
| Capacity Released | ✅ | Measure `[Capacity Released (FTEs)]` = `[Estimated Hours Saved]` × `Assumptions[CapacityConversionPct]` ÷ (`HoursPerFTEMonth` × months) | Page: `pt-capacity-released-ftes` |
| Initiatives Accelerated | ❌ | No initiative/project-linkage table in this model | Per meeting notes, requires linking repos/PRs/pipelines to a business-initiative identifier — deferred phase. Would need a `DimInitiative` table + repo/application mapping |
| Rand Value Realised | ✅ | Measures `[Gross Capacity Value]`, `[Avoided Defect Cost]`, `[Net Value]`, `[ROI %]`, `[Benefit-Cost Ratio]` | Pages: `pt-net-value`, `pt-roi`, `pt-benefit-cost-ratio`, `pt-gross-capacity-value`, `pt-avoided-defect-cost`. All driven by `Assumptions` table rates — validate against real finance figures before presenting externally |

## 6. Risk

| Item | Status | Data Point(s) | Notes |
|---|---|---|---|
| Inactive Licences | ✅ | Measure `[Inactive Seats]` = `[Assigned Seats]` − `[Active Users]` | Page: `pt-inactive-seats` |
| Technical Debt Indicators | ✅ | `FactMonthlyQuality[TechDebtItems]` → measure `[Tech Debt Items]` | No trend/severity breakdown currently — consider adding a severity column if source data supports it |
| Security & Compliance Issues | ⚠️ | `FactMonthlyQuality[VulnerabilitiesIntroduced]` → `[Vulnerabilities Introduced]` | Covers vulnerabilities only; Dependabot alerts / secret-scanning findings / policy-compliance status are not yet modelled and would need to be imported from GitHub Advanced Security or Azure DevOps |

## Summary of gaps requiring new/external data

1. **Training completion** — needs an LMS/Learning Pathways data source.
2. **GitHub-native Adoption Phases** (code completion → IDE agent → agent-first → multi-agent) — needs direct ingestion from the GitHub Copilot metrics/usage API; current `ValueChain` funnel is a local approximation.
3. **Initiatives Accelerated** — needs a business-initiative dimension and repo/application-to-initiative mapping.
4. **Code quality (static analysis)** and **security/compliance findings** (Dependabot, secret scanning, policy compliance) — needs GitHub Advanced Security / CI-CD compliance data imported and joined by repository/application identifier.
5. **Cost and value-realisation figures** are currently driven by assumption-table rates (`Assumptions` table), not actual invoiced/finance data — treat as estimates until validated.
