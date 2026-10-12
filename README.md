# Copilot Value Dashboard — Power BI Project

A Power BI (`.pbip` / TMDL) project that measures the **adoption, usage, productivity, quality and business value** of a GitHub Copilot rollout across a multi-team engineering organisation (modelled here on 8 bank engineering teams).

The report answers six executive questions:

1. Are people using it?
2. Are they getting value from it?
3. Are engineers more productive?
4. Is quality improving?
5. What business value are we creating?
6. Are we governing it responsibly?

> **Looking for hands-on setup?** See the step-by-step [Data Ingestion Guide (GitHub + Azure DevOps)](docs/data-ingestion-guide.md) — Fabric dataflow, Power Query helpers, per-endpoint M code, incremental refresh, secrets, scheduling and a validation checklist.

> **Looking for metric definitions?** See the [Simple View and Executive Value Scorecard Guide](docs/simple-and-executive-pages-guide.md) for every displayed metric, source data point, calculation, interpretation and measurement caveat on the first two report pages.

---

## 1. Repository layout

| Path | Purpose |
|---|---|
| [defaultProject.pbip](defaultProject.pbip) | Fabric / Power BI project descriptor |
| [defaultProject.Report/](defaultProject.Report) | Report definition (pages + visuals in JSON) |
| [defaultProject.SemanticModel/](defaultProject.SemanticModel) | Semantic model (tables, measures, relationships in TMDL) |
| [scripts/add_tooltip_pages.py](scripts/add_tooltip_pages.py) | Generates the per-measure tooltip pages (`pt-*`) and wires visuals to them |

### Report pages

Seven visible pages + 39 hidden tooltip pages (`pt-*`) — one per measure — wired via `visualTooltip.section`.

| Page id | Display name |
|---|---|
| `p00simple` | 0. Simple View — 6 Questions |
| `p01execscore` | 1. Executive Value Scorecard |
| `p02adoption` | 2. Adoption |
| `p03usage` | 3. Usage & Engagement |
| `p04productivity` | 4. Productivity |
| `p05quality` | 5. Quality |
| `p06bizvalue` | 6. Business Value |
| `pt-*` (×39) | Hidden per-measure tooltip pages |

---

## 2. Semantic model

Star schema. All fact and dimension tables currently ship with **synthetic data generated inline in Power Query (M)** so the report opens without any external connections. Every table's `partition ... source = let ... in` block should be replaced with a live query against the systems listed under "Real-world source" below.

### Tables

| Table | Grain | Real-world source (recommended) |
|---|---|---|
| [DimDate](defaultProject.SemanticModel/definition/tables/DimDate.tmdl) | One row per calendar day | **Generated in M** (calendar table). No external source needed. |
| [DimBusinessUnit](defaultProject.SemanticModel/definition/tables/DimBusinessUnit.tmdl) | One row per team | **Manual / HR system** — team roster, portfolio, cost centre, eligible-developer head-count. Load from CSV, SharePoint list, or an HR/Workday API. |
| [DimDeveloper](defaultProject.SemanticModel/definition/tables/DimDeveloper.tmdl) | One row per developer with a Copilot seat | **GitHub API** — [`GET /orgs/{org}/copilot/billing/seats`](https://docs.github.com/en/rest/copilot/copilot-user-management) for `AssignedDate`, `LastActiveDate`. Compute `FirstUseDate`, `IsActivated`, `IsSustained`, `TotalActiveWeeks` from the [Copilot user-level metrics API](https://docs.github.com/en/rest/copilot/copilot-metrics). |
| [DimFeature](defaultProject.SemanticModel/definition/tables/DimFeature.tmdl) | One row per Copilot feature (Completion, Chat, Code Review, Agent Mode, Coding Agent, CLI, Copilot App) | **Static reference table** — maintained by the Copilot programme team. |
| [Assumptions](defaultProject.SemanticModel/definition/tables/Assumptions.tmdl) | One row per scenario (Expected / Low / High) | **Manually entered by user** — Finance-signed values for loaded hourly cost, licence cost, minutes saved per suggestion, etc. Recommended as a parameter table in a workspace dataflow so Finance can edit without touching the model. |
| [ValueChain](defaultProject.SemanticModel/definition/tables/ValueChain.tmdl) | 5 rows: Eligible → Assigned → Active → Engaged → Sustained | **Static reference table**. |
| [FactTeamDaily](defaultProject.SemanticModel/definition/tables/FactTeamDaily.tmdl) | 1 row per (Date, Team) | **Mixed — see column table below** (GitHub Copilot metrics API + Azure DevOps / GitHub PR & deployment APIs). |
| [FactFeatureDaily](defaultProject.SemanticModel/definition/tables/FactFeatureDaily.tmdl) | 1 row per (Date, Team, Feature) | **GitHub Copilot metrics API** — per-feature breakdown of active users, interactions, accepted interactions. |
| [FactMonthlyQuality](defaultProject.SemanticModel/definition/tables/FactMonthlyQuality.tmdl) | 1 row per (Month, Team) | **Mixed — see column table below** (Azure DevOps / GitHub Actions + GHAS + survey tool). |
| [_Measures](defaultProject.SemanticModel/definition/tables/_Measures.tmdl) | Measure-only table | Contains all 55 DAX measures used by the report. |
| `LocalDateTable_*`, `DateTableTemplate_*` | Auto date/time tables | Auto-generated by Power BI. |

### Relationships

Defined in [relationships.tmdl](defaultProject.SemanticModel/definition/relationships.tmdl):

- `DimDate[Date]` → `FactTeamDaily[Date]`, `FactFeatureDaily[Date]`, `FactMonthlyQuality[Date]`
- `DimBusinessUnit[TeamKey]` → `FactTeamDaily[TeamKey]`, `FactFeatureDaily[TeamKey]`, `FactMonthlyQuality[TeamKey]`, `DimDeveloper[TeamKey]`
- `DimFeature[FeatureKey]` → `FactFeatureDaily[FeatureKey]`

---

## 3. Data source mapping (per column)

Legend:

- 🟩 **GitHub API** — GitHub REST/GraphQL, including the Copilot metrics & billing APIs
- 🟦 **DevOps API** — Azure DevOps REST (Git, Pipelines) or GitHub REST (PRs, Actions, Deployments) depending on where the team's code lives
- 🟨 **Manual** — user-maintained (HR, Finance, reference)
- ⚙️ **Derived** — computed in the model from other sourced values
- 🟪 **Survey** — from a developer-experience survey tool (e.g., Microsoft Forms, DX, Culture Amp)

### FactTeamDaily

| Column | Source | Recommended endpoint / origin |
|---|---|---|
| `Date` | ⚙️ Derived | Date key |
| `TeamKey` | 🟨 Manual | Join key from `DimBusinessUnit` |
| `ActiveUsers` | 🟩 GitHub API | `GET /orgs/{org}/team/{team_slug}/copilot/metrics` → `total_active_users` |
| `EngagedUsers` | 🟩 GitHub API | Same endpoint → `total_engaged_users` |
| `WeeklyActiveUsers` | 🟩 GitHub API | Aggregate 7-day window from `total_active_users` |
| `SuggestionsMade` | 🟩 GitHub API | `copilot_ide_code_completions.editors[].models[].languages[].total_code_suggestions` |
| `SuggestionsAccepted` | 🟩 GitHub API | `...total_code_acceptances` |
| `LinesAccepted` | 🟩 GitHub API | `...total_code_lines_accepted` |
| `ChatSessions` | 🟩 GitHub API | `copilot_ide_chat.editors[].models[].total_chats` |
| `AgentSessions` | 🟩 GitHub API | `copilot_dotcom_chat` / Agent Mode session counters |
| `CodingAgentPRsCreated` | 🟩 GitHub API | `GET /repos/{owner}/{repo}/pulls` filtered by `user:copilot-swe-agent` |
| `CodingAgentPRsMerged` | 🟩 GitHub API | Same filter, `state=closed` & `merged_at IS NOT NULL` |
| `AICreditsConsumed` | 🟩 GitHub API | `GET /enterprises/{ent}/copilot/usage` premium request billing feed |
| `PRsMerged` | 🟦 DevOps API | GitHub: `GET /repos/{o}/{r}/pulls?state=closed`; Azure DevOps: `GET pullrequests?searchCriteria.status=completed` |
| `PRCycleTimeHours` | 🟦 DevOps API | `merged_at − created_at` from the PR API |
| `TimeToFirstReviewHours` | 🟦 DevOps API | GitHub `GET /repos/{o}/{r}/pulls/{n}/reviews`; ADO `GET pullrequests/{id}/threads` |
| `LeadTimeHours` | 🟦 DevOps API | GitHub Deployments API + first-commit timestamp; ADO Pipelines run history |
| `Deployments` | 🟦 DevOps API | GitHub `GET /repos/{o}/{r}/deployments?environment=production`; ADO `releases` / `runs` |
| `FailedDeployments` | 🟦 DevOps API | Deployment/release status = failed/rolled back |
| `ReworkedPRs` | 🟦 DevOps API | PRs whose files are re-touched within 21 days (computed from commit history) |

### FactFeatureDaily

| Column | Source | Recommended endpoint / origin |
|---|---|---|
| `Date`, `TeamKey`, `FeatureKey` | ⚙️ Derived | Foreign keys |
| `ActiveUsers` | 🟩 GitHub API | Copilot metrics API — per-feature `total_active_users` |
| `Interactions` | 🟩 GitHub API | Sum of suggestions / chats / PRs raised by that feature |
| `AcceptedInteractions` | 🟩 GitHub API | Acceptances / merged agent PRs / applied review suggestions |

### FactMonthlyQuality

| Column | Source | Recommended endpoint / origin |
|---|---|---|
| `Date`, `TeamKey` | ⚙️ Derived | First-of-month key |
| `EscapedDefects` | 🟦 DevOps API | Azure Boards / GitHub Issues filtered by `label:prod-defect` & `found_in:production` |
| `ChangeFailures` | 🟦 DevOps API | Deployments where a rollback / hotfix followed within N hours |
| `TotalChanges` | 🟦 DevOps API | Count of production deployments in the month |
| `BuildRuns` | 🟦 DevOps API | GitHub Actions `GET /repos/{o}/{r}/actions/runs`; ADO Pipelines `runs` |
| `BuildSuccesses` | 🟦 DevOps API | Same, filtered by `conclusion=success` |
| `TestsRun` | 🟦 DevOps API | Test result APIs — GitHub check-runs / ADO Test Results |
| `TestsPassed` | 🟦 DevOps API | Same, filtered by `outcome=Passed` |
| `TestCoveragePct` | 🟦 DevOps API | Coverage publisher output (Cobertura / JaCoCo) uploaded to the CI run |
| `VulnerabilitiesIntroduced` | 🟩 GitHub API | GHAS `GET /repos/{o}/{r}/code-scanning/alerts` created in month; or Defender for DevOps |
| `MTTRHours` | 🟦 DevOps API | Incident tool (PagerDuty / ServiceNow) — `resolved_at − created_at` |
| `FlowStateScore` | 🟪 Survey | Monthly developer-experience survey |
| `ToolingSatisfaction` | 🟪 Survey | Monthly DX survey |
| `CopilotSatisfaction` | 🟪 Survey | Monthly DX survey |
| `TechDebtItems` | 🟦 DevOps API | Azure Boards / GitHub Issues with `label:tech-debt` open at month end |

### DimDeveloper

| Column | Source |
|---|---|
| `DeveloperKey`, `DeveloperName` | 🟩 GitHub API — `login`, `id` from the seats endpoint |
| `TeamKey` | 🟨 Manual — mapping of GitHub login → team, held in HR / IdP |
| `AssignedDate` | 🟩 GitHub API — `created_at` on the seat |
| `FirstUseDate` | 🟩 GitHub API — first date the developer appears in the Copilot metrics API |
| `LastActiveDate` | 🟩 GitHub API — `last_activity_at` on the seat |
| `DaysToFirstUse` | ⚙️ Derived — `FirstUseDate − AssignedDate` |
| `CohortMonth` | ⚙️ Derived — `FORMAT(AssignedDate,"yyyy-MM")` |
| `IsActivated` | ⚙️ Derived — 1 if `FirstUseDate` is not null |
| `IsSustained` | ⚙️ Derived — 1 if `TotalActiveWeeks ≥ 3` |
| `TotalActiveWeeks` | 🟩 GitHub API — distinct weeks with `active=true` in the Copilot metrics API |

### DimBusinessUnit / DimFeature / ValueChain / Assumptions

All 🟨 **Manual / reference** — held either as CSV in a Fabric dataflow or as a SharePoint / Dataverse list edited by the Copilot programme owner (business units) and Finance (assumptions).

---

## 4. Dashboard pages

Each page below lists every visual, its type, the fields it binds, and the origin of each field. Compact DAX for every ⚙️ Derived measure is listed in [§5 Measure calculation reference](#5-measure-calculation-reference); the authoritative version lives in [_Measures.tmdl](defaultProject.SemanticModel/definition/tables/_Measures.tmdl).

### 4.1 `p00simple` — Simple View — 6 Questions

A one-screen executive summary. Six "question" tiles, each with three KPI cards + one narrative text.

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-s0-title`, `v-s0-subtitle`, `v-s0-legend` | textbox | Static copy | 🟨 Manual (report author) |
| `v-s0-slicer-bu` | slicer | `DimBusinessUnit[BusinessUnit]` | 🟨 Manual |
| `v-s0-slicer-date` | slicer | `DimDate[YearMonth]` | ⚙️ Derived |
| `v-s1-header` … `v-s6-header` | textbox | Question titles | 🟨 Manual |
| `v-s1-answer` … `v-s6-answer` | textbox | Plain-language answers, "what good looks like", "watch-outs" | 🟨 Manual (report author) |
| `v-s1-kpi1` | card | `[Adoption Rate]` | ⚙️ Derived from 🟩 GitHub API |
| `v-s1-kpi2` | card | `[Active Users]` | 🟩 GitHub API |
| `v-s1-kpi3` | card | `[Sustained Usage %]` | ⚙️ Derived from 🟩 GitHub API |
| `v-s2-kpi1` | card | `[Code Acceptance Rate]` | ⚙️ Derived from 🟩 GitHub API |
| `v-s2-kpi2` | card | `[Chat Sessions]` | 🟩 GitHub API |
| `v-s2-kpi3` | card | `[Agent Sessions]` | 🟩 GitHub API |
| `v-s3-kpi1` | card | `[Median PR Cycle Time (hrs)]` | 🟦 DevOps API |
| `v-s3-kpi2` | card | `[PRs Merged]` | 🟦 DevOps API |
| `v-s3-kpi3` | card | `[Estimated Hours Saved]` | ⚙️ Derived (`Suggestions Accepted` × Assumptions) |
| `v-s4-kpi1` | card | `[Change Failure Rate]` | ⚙️ Derived from 🟦 DevOps API |
| `v-s4-kpi2` | card | `[Test Coverage %]` | 🟦 DevOps API |
| `v-s4-kpi3` | card | `[MTTR (hrs)]` | 🟦 DevOps API |
| `v-s5-kpi1` | card | `[Net Value]` | ⚙️ Derived (Gross Value + Avoided Defect − Investment) |
| `v-s5-kpi2` | card | `[Capacity Released (FTEs)]` | ⚙️ Derived (Hours Saved × 🟨 Assumptions) |
| `v-s5-kpi3` | card | `[ROI %]` | ⚙️ Derived |
| `v-s6-kpi1` | card | `[Inactive Seats]` | ⚙️ Derived from 🟩 GitHub API |
| `v-s6-kpi2` | card | `[Vulnerabilities Introduced]` | 🟩 GitHub API (GHAS) |
| `v-s6-kpi3` | card | `[Copilot Investment]` | ⚙️ Derived from 🟨 Assumptions |

### 4.2 `p01execscore` — Executive Value Scorecard

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p1-title`, `v-p1-subtitle`, `v-p1-insight` | textbox | Static copy | 🟨 Manual |
| `v-p1-slicer-bu` | slicer | `DimBusinessUnit[BusinessUnit]` | 🟨 Manual |
| `v-p1-slicer-team` | slicer | `DimBusinessUnit[Team]` | 🟨 Manual |
| `v-p1-slicer-date` | slicer | `DimDate[YearMonth]` | ⚙️ Derived |
| `v-p1-kpi-adoption` | card | `[Adoption Rate]` | ⚙️ Derived from 🟩 GitHub API |
| `v-p1-kpi-sustained` | card | `[Sustained Usage %]` | ⚙️ Derived from 🟩 GitHub API |
| `v-p1-kpi-cycle` | card | `[Median PR Cycle Time (hrs)]` | 🟦 DevOps API |
| `v-p1-kpi-quality` | card | `[Change Failure Rate]` | 🟦 DevOps API |
| `v-p1-kpi-capacity` | card | `[Estimated Hours Saved]` | ⚙️ Derived |
| `v-p1-kpi-value` | card | `[Net Value]` | ⚙️ Derived |
| `v-p1-trend-adoption` | lineChart | `WeekStart` × (`[Active Users]`, `[Sustained Users]`) | 🟩 GitHub API |
| `v-p1-trend-delivery` | line-column combo | `YearMonth` × (`[Deployments]`, `[Median PR Cycle Time (hrs)]`) | 🟦 DevOps API |
| `v-p1-trend-quality` | lineChart | `YearMonth` × (`[Change Failure Rate]`, `[Test Coverage %]`) | 🟦 DevOps API |
| `v-p1-valuechain` | funnel | `ValueChain[StepName]` × `[Value Chain Count]` | 🟨 Reference + ⚙️ Derived |
| `v-p1-waterfall` | waterfall | `YearMonth` × `[Net Value]` | ⚙️ Derived |
| `v-p1-bu-perf` | table | `BusinessUnit`, `Team`, `[Adoption Rate]`, `[Sustained Usage %]`, `[Median PR Cycle Time (hrs)]`, `[Change Failure Rate]`, `[Net Value]` | Mixed — 🟨 Manual + 🟩 GitHub + 🟦 DevOps |

### 4.3 `p02adoption` — Adoption

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p2-title` | textbox | Page title | 🟨 Manual |
| `v-p2-slicer` | slicer | `DimBusinessUnit[BusinessUnit]` | 🟨 Manual |
| `v-p2-kpi-assigned` | card | `[Assigned Seats]` | 🟩 GitHub API (`/copilot/billing/seats`) |
| `v-p2-kpi-active` | card | `[Active Users]` | 🟩 GitHub API |
| `v-p2-kpi-adoprate` | card | `[Adoption Rate]` | ⚙️ Derived |
| `v-p2-kpi-sustained` | card | `[Sustained Users]` | 🟩 GitHub API |
| `v-p2-kpi-inactive` | card | `[Inactive Seats]` | ⚙️ Derived |
| `v-p2-kpi-ttfu` | card | `[Avg Days to First Use]` | ⚙️ Derived from 🟩 GitHub API |
| `v-p2-funnel` | funnel | `ValueChain[StepName]` × `[Value Chain Count]` | 🟨 Reference + ⚙️ Derived |
| `v-p2-wau-trend` | lineChart | `WeekStart` × `BusinessUnit` × (`[Active Users]`, `[Weekly Active Users]`, `[Sustained Users]`) | 🟩 GitHub API |
| `v-p2-heatmap` | pivotTable | `BusinessUnit`, `Team` × `[Assigned Seats]`, `[Active Users]`, `[Adoption Rate]`, `[Sustained Usage %]`, `[Copilot Satisfaction]`, `[Cost per Active User]` | 🟨 + 🟩 + 🟪 + ⚙️ |

### 4.4 `p03usage` — Usage & Engagement

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p3-title` | textbox | Page title | 🟨 Manual |
| `v-p3-kpi-accepted` | card | `[Suggestions Accepted]` | 🟩 GitHub API |
| `v-p3-kpi-accrate` | card | `[Code Acceptance Rate]` | ⚙️ Derived |
| `v-p3-kpi-chat` | card | `[Chat Sessions]` | 🟩 GitHub API |
| `v-p3-kpi-agent` | card | `[Agent Sessions]` | 🟩 GitHub API |
| `v-p3-kpi-caprm` | card | `[Coding Agent PRs Merged]` | 🟩 GitHub API (PRs by `copilot-swe-agent`) |
| `v-p3-kpi-credits` | card | `[AI Credits Consumed]` | 🟩 GitHub API (premium request billing) |
| `v-p3-feature-bar` | 100% stacked bar | `Team` × `FeatureName` × `[Suggestions Accepted]` | 🟩 GitHub API + 🟨 Reference |
| `v-p3-scatter` | scatter | `Team` × (`[Active Users]`, `[Sustained Usage %]`, `[Median PR Cycle Time (hrs)]`) | 🟩 GitHub + 🟦 DevOps |
| `v-p3-costtable` | table | `BusinessUnit`, `Team`, `[AI Credits Consumed]`, `[AI Credit Cost]`, `[Licence Cost]`, `[Copilot Investment]`, `[Cost per Active User]` | 🟩 GitHub + 🟨 Assumptions + ⚙️ Derived |

### 4.5 `p04productivity` — Productivity

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p4-title` | textbox | Page title | 🟨 Manual |
| `v-p4-kpi-cycle` | card | `[Median PR Cycle Time (hrs)]` | 🟦 DevOps API |
| `v-p4-kpi-tfr` | card | `[Avg Time to First Review (hrs)]` | 🟦 DevOps API |
| `v-p4-kpi-prs` | card | `[PRs Merged]` | 🟦 DevOps API |
| `v-p4-kpi-deploy` | card | `[Deployments]` | 🟦 DevOps API |
| `v-p4-kpi-throughput` | card | `[Throughput per Active Engineer]` | ⚙️ Derived (`PRs Merged` / `Active Users`) |
| `v-p4-kpi-rework` | card | `[Rework Rate]` | ⚙️ Derived from 🟦 DevOps API |
| `v-p4-baseline-bar` | clustered bar | `Team` × (`[Median PR Cycle Time (hrs)]`, `[Avg Time to First Review (hrs)]`, `[Avg Lead Time (hrs)]`) | 🟦 DevOps API |
| `v-p4-control` | lineChart | `WeekStart` × `BusinessUnit` × `[Median PR Cycle Time (hrs)]` | 🟦 DevOps API |
| `v-p4-cohort-table` | table | `BusinessUnit`, `Team`, `[PRs Merged]`, `[Median PR Cycle Time (hrs)]`, `[Deployments]`, `[Rework Rate]`, `[Flow State Score]`, `[Copilot Satisfaction]` | 🟦 DevOps + 🟪 Survey |

### 4.6 `p05quality` — Quality

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p5-title` | textbox | Page title | 🟨 Manual |
| `v-p5-kpi-defects` | card | `[Escaped Defects]` | 🟦 DevOps API (work-items) |
| `v-p5-kpi-cfr` | card | `[Change Failure Rate]` | ⚙️ Derived from 🟦 DevOps API |
| `v-p5-kpi-coverage` | card | `[Test Coverage %]` | 🟦 DevOps API (CI coverage) |
| `v-p5-kpi-vuln` | card | `[Vulnerabilities Introduced]` | 🟩 GitHub API (GHAS code-scanning) |
| `v-p5-kpi-mttr` | card | `[MTTR (hrs)]` | 🟦 DevOps API / incident tool |
| `v-p5-quadrant` | scatter | `Team` × (`[PRs Merged]`, `[Median PR Cycle Time (hrs)]`, `[Change Failure Rate]`) | 🟦 DevOps API |
| `v-p5-trend` | lineChart | `YearMonth` × `BusinessUnit` × (`[Escaped Defects]`, `[Rework Rate]`) | 🟦 DevOps API |
| `v-p5-scorecard` | table | `BusinessUnit`, `Team`, `[Escaped Defects]`, `[Change Failure Rate]`, `[Test Coverage %]`, `[Test Pass Rate]`, `[Build Success Rate]`, `[Vulnerabilities Introduced]`, `[MTTR (hrs)]`, `[Tech Debt Items]` | 🟦 DevOps + 🟩 GitHub (GHAS) |

### 4.7 `p06bizvalue` — Business Value

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p6-title`, `v-p6-narrative` | textbox | Static copy | 🟨 Manual |
| `v-p6-kpi-invest` | card | `[Copilot Investment]` | ⚙️ Derived from 🟨 Assumptions + 🟩 GitHub |
| `v-p6-kpi-gross` | card | `[Gross Capacity Value]` | ⚙️ Derived |
| `v-p6-kpi-avoided` | card | `[Avoided Defect Cost]` | ⚙️ Derived from 🟦 DevOps + 🟨 Assumptions |
| `v-p6-kpi-net` | card | `[Net Value]` | ⚙️ Derived |
| `v-p6-kpi-roi` | card | `[ROI %]` | ⚙️ Derived |
| `v-p6-kpi-bcr` | card | `[Benefit-Cost Ratio]` | ⚙️ Derived |
| `v-p6-waterfall` | waterfall | `YearMonth` × `[Net Value]` | ⚙️ Derived |
| `v-p6-unit-costs` | table | `BusinessUnit`, `Team`, `[Copilot Investment]`, `[Estimated Hours Saved]`, `[Capacity Released (FTEs)]`, `[Gross Capacity Value]`, `[Net Value]`, `[ROI %]`, `[Cost per Active User]`, `[Cost per Sustained User]`, `[Cost per Merged PR]` | ⚙️ Derived |

### 4.8 Tooltip pages (`pt-*`)

39 hidden pages generated by [scripts/add_tooltip_pages.py](scripts/add_tooltip_pages.py). Each one is a single textbox that shows the measure name, a compact DAX formula and a one-line description. They are wired as report-page tooltips (`visual.visualContainerObjects.visualTooltip.section`) on every visual that binds the matching measure. Content is 🟨 **Manual** (author-maintained in the Python script) and derived from the `_Measures` table's inline `///` documentation comments.

---

## 5. Measure calculation reference

Compact DAX for every measure in the `_Measures` table, grouped by theme. Full source lives in [_Measures.tmdl](defaultProject.SemanticModel/definition/tables/_Measures.tmdl).

### Adoption / usage

| Measure | DAX (compact) |
|---|---|
| `Eligible Developers` | `SUM(DimBusinessUnit[EligibleDevelopers])` |
| `Assigned Seats` | `COUNTROWS(DimDeveloper)` |
| `Activated Users` | `CALCULATE(COUNTROWS(DimDeveloper), DimDeveloper[IsActivated]=1)` |
| `Active Users` | `SUMX(VALUES(DimBusinessUnit[TeamKey]), CALCULATE(MAX(FactTeamDaily[ActiveUsers])))` |
| `Weekly Active Users` | `SUMX(VALUES(DimBusinessUnit[TeamKey]), CALCULATE(MAX(FactTeamDaily[WeeklyActiveUsers])))` |
| `Sustained Users` | `CALCULATE(COUNTROWS(DimDeveloper), DimDeveloper[IsSustained]=1)` |
| `Engaged Users` | `SUMX(VALUES(DimBusinessUnit[TeamKey]), CALCULATE(MAX(FactTeamDaily[EngagedUsers])))` |
| `Adoption Rate` | `DIVIDE([Active Users], [Assigned Seats])` |
| `Activation Rate` | `DIVIDE([Activated Users], [Assigned Seats])` |
| `Sustained Usage %` | `DIVIDE([Sustained Users], [Active Users])` |
| `Inactive Seats` | `[Assigned Seats] - [Active Users]` |
| `Avg Days to First Use` | `AVERAGEX(FILTER(DimDeveloper, DimDeveloper[IsActivated]=1), DimDeveloper[DaysToFirstUse])` |
| `Value Chain Count` | `SWITCH(SELECTEDVALUE(ValueChain[StepOrder]), 1,[Eligible Developers], 2,[Assigned Seats], 3,[Active Users], 4,[Engaged Users], 5,[Sustained Users])` |

### Copilot activity

| Measure | DAX (compact) |
|---|---|
| `Suggestions Made` | `SUM(FactTeamDaily[SuggestionsMade])` |
| `Suggestions Accepted` | `SUM(FactTeamDaily[SuggestionsAccepted])` |
| `Code Acceptance Rate` | `DIVIDE([Suggestions Accepted], [Suggestions Made])` |
| `Lines Accepted` | `SUM(FactTeamDaily[LinesAccepted])` |
| `Chat Sessions` | `SUM(FactTeamDaily[ChatSessions])` |
| `Agent Sessions` | `SUM(FactTeamDaily[AgentSessions])` |
| `Coding Agent PRs Created` | `SUM(FactTeamDaily[CodingAgentPRsCreated])` |
| `Coding Agent PRs Merged` | `SUM(FactTeamDaily[CodingAgentPRsMerged])` |
| `AI Credits Consumed` | `SUM(FactTeamDaily[AICreditsConsumed])` |

### Productivity / DORA

| Measure | DAX (compact) |
|---|---|
| `PRs Merged` | `SUM(FactTeamDaily[PRsMerged])` |
| `Median PR Cycle Time (hrs)` | `MEDIANX(FILTER(FactTeamDaily, FactTeamDaily[PRsMerged]>0), FactTeamDaily[PRCycleTimeHours])` |
| `Avg Time to First Review (hrs)` | `AVERAGEX(FILTER(FactTeamDaily, FactTeamDaily[PRsMerged]>0), FactTeamDaily[TimeToFirstReviewHours])` |
| `Avg Lead Time (hrs)` | `AVERAGEX(FILTER(FactTeamDaily, FactTeamDaily[PRsMerged]>0), FactTeamDaily[LeadTimeHours])` |
| `Deployments` | `SUM(FactTeamDaily[Deployments])` |
| `Failed Deployments` | `SUM(FactTeamDaily[FailedDeployments])` |
| `Reworked PRs` | `SUM(FactTeamDaily[ReworkedPRs])` |
| `Rework Rate` | `DIVIDE([Reworked PRs], [PRs Merged])` |
| `Throughput per Active Engineer` | `DIVIDE([PRs Merged], [Active Users])` |

### Quality

| Measure | DAX (compact) |
|---|---|
| `Escaped Defects` | `SUM(FactMonthlyQuality[EscapedDefects])` |
| `Change Failures` | `SUM(FactMonthlyQuality[ChangeFailures])` |
| `Total Changes` | `SUM(FactMonthlyQuality[TotalChanges])` |
| `Change Failure Rate` | `DIVIDE([Change Failures], [Total Changes])` |
| `Test Coverage %` | `AVERAGE(FactMonthlyQuality[TestCoveragePct])` |
| `Test Pass Rate` | `DIVIDE(SUM(FactMonthlyQuality[TestsPassed]), SUM(FactMonthlyQuality[TestsRun]))` |
| `Build Success Rate` | `DIVIDE(SUM(FactMonthlyQuality[BuildSuccesses]), SUM(FactMonthlyQuality[BuildRuns]))` |
| `Vulnerabilities Introduced` | `SUM(FactMonthlyQuality[VulnerabilitiesIntroduced])` |
| `MTTR (hrs)` | `AVERAGE(FactMonthlyQuality[MTTRHours])` |
| `Flow State Score` | `AVERAGE(FactMonthlyQuality[FlowStateScore])` |
| `Tooling Satisfaction` | `AVERAGE(FactMonthlyQuality[ToolingSatisfaction])` |
| `Copilot Satisfaction` | `AVERAGE(FactMonthlyQuality[CopilotSatisfaction])` |
| `Tech Debt Items` | `SUM(FactMonthlyQuality[TechDebtItems])` |

### Business value (all use Finance-owned inputs from `Assumptions`)

| Measure | DAX (compact) |
|---|---|
| `Licence Cost` | `[Assigned Seats] * DISTINCTCOUNT(DimDate[YearMonth]) * SELECTEDVALUE(Assumptions[LicenceCostPerSeatMonth], 350)` |
| `AI Credit Cost` | `[AI Credits Consumed] * SELECTEDVALUE(Assumptions[AICreditCostPerUnit], 0.15)` |
| `Enablement Cost` | `DISTINCTCOUNT(DimDate[YearMonth]) * SELECTEDVALUE(Assumptions[EnablementCostMonth], 45000)` |
| `Copilot Investment` | `[Licence Cost] + [AI Credit Cost] + [Enablement Cost]` |
| `Estimated Hours Saved` | `([Suggestions Accepted] * SELECTEDVALUE(Assumptions[MinutesSavedPerAcceptedSuggestion], 0.8)) / 60` |
| `Capacity Released (FTEs)` | `DIVIDE([Estimated Hours Saved] * SELECTEDVALUE(Assumptions[CapacityConversionPct], 0.6), SELECTEDVALUE(Assumptions[HoursPerFTEMonth], 160) * DISTINCTCOUNT(DimDate[YearMonth]))` |
| `Gross Capacity Value` | `[Estimated Hours Saved] * SELECTEDVALUE(Assumptions[CapacityConversionPct], 0.6) * SELECTEDVALUE(Assumptions[LoadedHourlyCost], 850)` |
| `Avoided Defect Cost` | `MAX(0, 8 * DISTINCTCOUNT(DimBusinessUnit[TeamKey]) * DISTINCTCOUNT(FactMonthlyQuality[Date]) - [Escaped Defects]) * SELECTEDVALUE(Assumptions[DefectRemediationCost], 12500)` |
| `Net Value` | `[Gross Capacity Value] + [Avoided Defect Cost] - [Copilot Investment]` |
| `ROI %` | `DIVIDE([Net Value], [Copilot Investment])` |
| `Benefit-Cost Ratio` | `DIVIDE([Gross Capacity Value] + [Avoided Defect Cost], [Copilot Investment])` |
| `Cost per Active User` | `DIVIDE([Copilot Investment], [Active Users])` |
| `Cost per Sustained User` | `DIVIDE([Copilot Investment], [Sustained Users])` |
| `Cost per Merged PR` | `DIVIDE([Copilot Investment], [PRs Merged])` |

### Baseline deltas

| Measure | DAX (compact) | Baseline |
|---|---|---|
| `Adoption Rate Δ vs Baseline` | `[Adoption Rate] - 0.55` | 55% adoption |
| `PR Cycle Time Δ vs Baseline` | `DIVIDE([Median PR Cycle Time (hrs)] - 42, 42)` | 42 hrs |
| `Change Failure Rate Δ vs Baseline` | `[Change Failure Rate] - 0.12` | 12% CFR |

### Derived model columns (computed at load time, not DAX)

| Column | Table | Calculation |
|---|---|---|
| `DaysToFirstUse` | `DimDeveloper` | `FirstUseDate − AssignedDate` (0 if not activated) |
| `CohortMonth` | `DimDeveloper` | `FORMAT(AssignedDate, "yyyy-MM")` |
| `IsActivated` | `DimDeveloper` | `1` if the developer has any usage day (`FirstUseDate` present), else `0` |
| `IsSustained` | `DimDeveloper` | `1` if `TotalActiveWeeks ≥ 3`, else `0` |
| `TotalActiveWeeks` | `DimDeveloper` | Distinct weeks with at least one active day from the Copilot metrics API |
| `WeekStart` | `DimDate` | `Date - WEEKDAY(Date, 2) + 1` (Monday of the ISO week) |
| `YearMonth` | `DimDate` | `FORMAT(Date, "yyyy-MM")` |

---

## 6. Moving from synthetic data to live APIs

> The full implementation walkthrough — Fabric workspace setup, GitHub App registration, Azure DevOps PAT scopes, Power Query helpers (`fnGitHubToken`, `fnPagedGet`, `fnAdoGet`, `fnSecrets`), per-endpoint M code for every bronze table, silver SQL views, incremental refresh windows, DirectLake vs Import, Key Vault wiring, scheduling, RLS and a validation checklist — lives in [docs/data-ingestion-guide.md](docs/data-ingestion-guide.md). The summary below is the quick-start.

The three fact tables and `DimDeveloper` currently define their data inline using Power Query `let ... in` blocks (see the `partition ... source` sections in each `.tmdl`). To make the report live:

1. **Register a service principal / GitHub App** with `Copilot`, `Metrics` and `Contents` read scopes for the org / enterprise.
2. **Create a Fabric dataflow** with one query per real endpoint:
   - `Copilot Metrics — Team Daily` → drives `FactTeamDaily` (7-day retention, so land historic snapshots into a lakehouse).
   - `Copilot Metrics — Feature Daily` → drives `FactFeatureDaily`.
   - `Copilot Seats` → drives `DimDeveloper`.
   - `Azure DevOps / GitHub PRs, Deployments, Actions` → drives the DORA columns on `FactTeamDaily` and `FactMonthlyQuality`.
   - `GHAS Code-Scanning Alerts` → drives `VulnerabilitiesIntroduced`.
   - `Survey export` → drives `FlowStateScore`, `ToolingSatisfaction`, `CopilotSatisfaction`.
3. **Publish `DimBusinessUnit`, `DimFeature`, `ValueChain`, `Assumptions`** as reference tables in the same dataflow (CSV / SharePoint list backed).
4. **Replace each table's inline `source =`** with `Source = PowerPlatform.Dataflows(null){[workspaceId=...]}...` referencing the corresponding dataflow entity. Column names and types are already aligned with the source APIs, so no measure changes are required.
5. Optionally, keep the current synthetic partitions behind a `Parameter[UseSampleData]` switch so the report still opens without credentials for demos.

---

## 7. Regenerating the tooltip pages

If you add or rename a measure:

```powershell
python scripts/add_tooltip_pages.py
```

The script:

- rewrites every `pt-<slug>/page.json` + textbox visual,
- deduplicates and re-orders `pages.json`,
- rewires each visual's `visualTooltip.section` to the matching `pt-*` page.

Update the `MEASURES` dictionary at the top of the script before running it so the tooltip content stays in sync with `_Measures.tmdl`.
