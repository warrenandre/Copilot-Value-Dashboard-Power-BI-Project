# Copilot Value Dashboard — Power BI Project (GitHub-only edition)

Companion to [README.md](README.md). Same report, same semantic model, same DAX — **but every data source is on the GitHub platform**. Azure DevOps, Azure Boards, ServiceNow, PagerDuty and other non-GitHub systems are replaced with equivalent GitHub REST / GraphQL endpoints, GitHub Actions telemetry, Issues, and GHAS.

The report still answers the same six executive questions:

1. Are people using it?
2. Are they getting value from it?
3. Are engineers more productive?
4. Is quality improving?
5. What business value are we creating?
6. Are we governing it responsibly?

> **Looking for hands-on setup?** See the step-by-step [Data Ingestion Guide (GitHub-only)](docs/data-ingestion-guide.github.md) — Fabric dataflow, Power Query helpers (including GraphQL), per-endpoint M code for Copilot / Pulls / Deployments / Actions / Issues / GHAS, IssueOps conventions, incremental refresh and a validation checklist.

---

## 1. Repository layout

Identical to [README.md §1](README.md#1-repository-layout). Only the underlying data source per column changes.

---

## 2. Semantic model

Star schema, same tables and grains as [README.md §2](README.md#2-semantic-model). The **recommended source column changes only** — everything comes from GitHub or from Finance/HR reference data.

| Table | Grain | Real-world source (GitHub-only) |
|---|---|---|
| [DimDate](defaultProject.SemanticModel/definition/tables/DimDate.tmdl) | One row per calendar day | Generated in M. |
| [DimBusinessUnit](defaultProject.SemanticModel/definition/tables/DimBusinessUnit.tmdl) | One row per team | **HR / IdP** (manual). Map GitHub teams (`GET /orgs/{org}/teams`) → business unit / portfolio / cost centre / eligible-developer count via a lookup CSV or SharePoint list. |
| [DimDeveloper](defaultProject.SemanticModel/definition/tables/DimDeveloper.tmdl) | One row per developer with a Copilot seat | **GitHub Copilot APIs** — seats (`GET /orgs/{org}/copilot/billing/seats`), team membership (`GET /orgs/{org}/teams/{slug}/members`), user-level metrics for first-use / active weeks. |
| [DimFeature](defaultProject.SemanticModel/definition/tables/DimFeature.tmdl) | One row per Copilot feature | Static reference table. |
| [Assumptions](defaultProject.SemanticModel/definition/tables/Assumptions.tmdl) | Finance-owned scenario | Manual, Finance-signed. Recommended: hold as a JSON/CSV in a governance repo, load via `GET /repos/{o}/{r}/contents/{path}` so edits are auditable in Git. |
| [ValueChain](defaultProject.SemanticModel/definition/tables/ValueChain.tmdl) | 5 static rows | Reference. |
| [FactTeamDaily](defaultProject.SemanticModel/definition/tables/FactTeamDaily.tmdl) | (Date, Team) | GitHub Copilot Metrics API + Pulls / Deployments / Actions APIs. |
| [FactFeatureDaily](defaultProject.SemanticModel/definition/tables/FactFeatureDaily.tmdl) | (Date, Team, Feature) | GitHub Copilot Metrics API. |
| [FactMonthlyQuality](defaultProject.SemanticModel/definition/tables/FactMonthlyQuality.tmdl) | (Month, Team) | GitHub Actions + Issues + GHAS + survey. |
| [_Measures](defaultProject.SemanticModel/definition/tables/_Measures.tmdl) | Measure-only | DAX (see [README.md §5](README.md#5-measure-calculation-reference)). |

### Relationships

Unchanged — see [relationships.tmdl](defaultProject.SemanticModel/definition/relationships.tmdl).

---

## 3. Data source mapping (per column) — GitHub-only

Legend:

- 🟩 **GitHub API** — REST / GraphQL / Copilot Metrics / Actions / Deployments / Issues / GHAS
- 🟨 **Manual** — Finance / HR / programme reference
- 🟪 **Survey** — DX survey tool export (kept — no GitHub-native equivalent)
- ⚙️ **Derived** — computed in the model from other sourced values

### FactTeamDaily

| Column | Source | GitHub endpoint / origin |
|---|---|---|
| `Date` | ⚙️ Derived | Date key. |
| `TeamKey` | 🟨 Manual | Join key from `DimBusinessUnit`. |
| `ActiveUsers` | 🟩 GitHub | `GET /orgs/{org}/team/{team_slug}/copilot/metrics` → `total_active_users`. |
| `EngagedUsers` | 🟩 GitHub | Same endpoint → `total_engaged_users`. |
| `WeeklyActiveUsers` | 🟩 GitHub | Aggregate rolling-7-day window from `total_active_users`. |
| `SuggestionsMade` | 🟩 GitHub | `copilot_ide_code_completions.editors[].models[].languages[].total_code_suggestions`. |
| `SuggestionsAccepted` | 🟩 GitHub | `...total_code_acceptances`. |
| `LinesAccepted` | 🟩 GitHub | `...total_code_lines_accepted`. |
| `ChatSessions` | 🟩 GitHub | `copilot_ide_chat.editors[].models[].total_chats`. |
| `AgentSessions` | 🟩 GitHub | Copilot metrics → Agent Mode / `copilot_dotcom_chat` session counters. |
| `CodingAgentPRsCreated` | 🟩 GitHub | `GET /repos/{owner}/{repo}/pulls?state=all` filtered by `user:copilot-swe-agent`. |
| `CodingAgentPRsMerged` | 🟩 GitHub | Same filter, `merged_at IS NOT NULL`. |
| `AICreditsConsumed` | 🟩 GitHub | `GET /enterprises/{ent}/copilot/usage` — premium-request billing feed. |
| `PRsMerged` | 🟩 GitHub | `GET /repos/{o}/{r}/pulls?state=closed` (filter `merged_at IS NOT NULL`) — or GraphQL `search(type:ISSUE, query:"is:pr is:merged repo:...")`. |
| `PRCycleTimeHours` | 🟩 GitHub | Pulls API — `merged_at − created_at`. |
| `TimeToFirstReviewHours` | 🟩 GitHub | `GET /repos/{o}/{r}/pulls/{n}/reviews` — MIN(`submitted_at`) − PR `created_at`. |
| `LeadTimeHours` | 🟩 GitHub | Pulls API `commits[0].committer.date` (first commit) → GitHub Deployments API `deployments[?environment=production].created_at`. |
| `Deployments` | 🟩 GitHub | `GET /repos/{o}/{r}/deployments?environment=production` **or** `GET /repos/{o}/{r}/actions/workflows/{deploy.yml}/runs?status=success`. |
| `FailedDeployments` | 🟩 GitHub | `GET /repos/{o}/{r}/deployments/{id}/statuses` → any `state IN ('failure','error')`, or Actions run `conclusion=failure` on the deploy workflow. |
| `ReworkedPRs` | 🟩 GitHub | GraphQL — PRs whose merged files are re-touched by another PR within 21 days (`GET /repos/{o}/{r}/commits?path=...`). |

### FactFeatureDaily

| Column | Source | GitHub endpoint / origin |
|---|---|---|
| `Date`, `TeamKey`, `FeatureKey` | ⚙️ Derived | Foreign keys. |
| `ActiveUsers` | 🟩 GitHub | Copilot metrics — per-feature `total_active_users`. |
| `Interactions` | 🟩 GitHub | Sum of feature-specific volume (suggestions / chats / agent PRs / review comments). |
| `AcceptedInteractions` | 🟩 GitHub | Feature-specific acceptances (accepted suggestions / merged agent PRs / applied review suggestions). |

### FactMonthlyQuality

| Column | Source | GitHub endpoint / origin |
|---|---|---|
| `Date`, `TeamKey` | ⚙️ Derived | First-of-month key. |
| `EscapedDefects` | 🟩 GitHub | `GET /search/issues?q=repo:...+is:issue+label:prod-defect+created:YYYY-MM`. Use org-level `label:prod-defect` convention. |
| `ChangeFailures` | 🟩 GitHub | Deployments API — production deployments followed within N hours by a rollback deployment, **or** Issues with `label:incident` linked to a deployment via `X-GitHub-Delivery` / commit SHA in the body. |
| `TotalChanges` | 🟩 GitHub | Count of production deployments in the month (Deployments API or Actions workflow runs on the release pipeline). |
| `BuildRuns` | 🟩 GitHub | `GET /repos/{o}/{r}/actions/runs?created:YYYY-MM` (or filter by CI workflow file). |
| `BuildSuccesses` | 🟩 GitHub | Same, `conclusion=success`. |
| `TestsRun` | 🟩 GitHub | GitHub Actions check-runs on the CI workflow — sum `output.summary` test counts, **or** a JUnit results artifact uploaded by CI and read via `GET /repos/{o}/{r}/actions/artifacts`. |
| `TestsPassed` | 🟩 GitHub | Same source, filtered to `conclusion=success` at the check-run level or `passed` in the JUnit artifact. |
| `TestCoveragePct` | 🟩 GitHub | Coverage report artifact (Cobertura/LCOV) uploaded from CI to `actions/artifacts`, **or** a `coverage-summary.json` committed to a `metrics/` folder in each repo and read via `GET /repos/{o}/{r}/contents/metrics/coverage-summary.json`. |
| `VulnerabilitiesIntroduced` | 🟩 GitHub | GHAS — `GET /repos/{o}/{r}/code-scanning/alerts?state=open&created:YYYY-MM`. Also `dependabot/alerts` and `secret-scanning/alerts` for a fuller picture. |
| `MTTRHours` | 🟩 GitHub | Issues labelled `incident` — average of (`closed_at − created_at`) per month. Requires a lightweight IssueOps incident workflow (`/incident open`, `/incident resolve`). |
| `FlowStateScore` | 🟪 Survey | Monthly DX survey (no GitHub-native equivalent). Recommend Microsoft Forms / DX platform export → CSV → dataflow. |
| `ToolingSatisfaction` | 🟪 Survey | Same DX survey. |
| `CopilotSatisfaction` | 🟪 Survey | Same DX survey — or GitHub Copilot in-product feedback exports if enabled at the enterprise level. |
| `TechDebtItems` | 🟩 GitHub | `GET /search/issues?q=org:{org}+is:issue+is:open+label:tech-debt` snapshot at month end. |

### DimDeveloper

| Column | Source | GitHub endpoint / origin |
|---|---|---|
| `DeveloperKey`, `DeveloperName` | 🟩 GitHub | `assignee.id`, `assignee.login` from `GET /orgs/{org}/copilot/billing/seats`. |
| `TeamKey` | 🟨 Manual | GitHub `login` → team map, held in HR / IdP (SCIM export). Optionally derived from GitHub team membership if teams = business units 1:1. |
| `AssignedDate` | 🟩 GitHub | Seats API — `created_at`. |
| `FirstUseDate` | 🟩 GitHub | User-level Copilot metrics — first date the user appears with `active=true`. |
| `LastActiveDate` | 🟩 GitHub | Seats API — `last_activity_at`. |
| `DaysToFirstUse` | ⚙️ Derived | `FirstUseDate − AssignedDate`. |
| `CohortMonth` | ⚙️ Derived | `FORMAT(AssignedDate, "yyyy-MM")`. |
| `IsActivated` | ⚙️ Derived | `1` if `FirstUseDate IS NOT NULL`. |
| `IsSustained` | ⚙️ Derived | `1` if `TotalActiveWeeks ≥ 3`. |
| `TotalActiveWeeks` | 🟩 GitHub | Distinct weeks with any active day in the Copilot user-level metrics API. |

### DimBusinessUnit / DimFeature / ValueChain / Assumptions

- **DimBusinessUnit** — 🟨 Manual. Best kept as a CSV in a governance repo so team → portfolio → cost-centre mapping is versioned in Git and readable via `GET /repos/{o}/{r}/contents/orgmap.csv`.
- **DimFeature** — 🟨 Reference (static list of Copilot features).
- **ValueChain** — 🟨 Reference (5-step funnel).
- **Assumptions** — 🟨 Finance-signed. Same "commit to Git" pattern gives you a full audit trail on every change.

---

## 4. Dashboard pages

The page structure, visual list and visual types are **identical** to [README.md §4](README.md#4-dashboard-pages). Only the **Source** column changes: every 🟦 DevOps API row becomes 🟩 GitHub. Reproduced below in condensed form.

Compact DAX for every ⚙️ Derived measure lives in [README.md §5](README.md#5-measure-calculation-reference) — nothing DAX-related changes when the upstream data source moves.

### 4.1 `p00simple` — Simple View — 6 Questions

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-s0-title`, `v-s0-subtitle`, `v-s0-legend` | textbox | Static copy | 🟨 Manual |
| `v-s0-slicer-bu` / `v-s0-slicer-date` | slicer | `BusinessUnit`, `YearMonth` | 🟨 Manual / ⚙️ Derived |
| `v-s1-header … v-s6-header` | textbox | Question titles | 🟨 Manual |
| `v-s1-answer … v-s6-answer` | textbox | Narrative + "what good looks like" + "watch-outs" | 🟨 Manual |
| `v-s1-kpi1` | card | `[Adoption Rate]` | ⚙️ Derived from 🟩 GitHub |
| `v-s1-kpi2` | card | `[Active Users]` | 🟩 GitHub |
| `v-s1-kpi3` | card | `[Sustained Usage %]` | ⚙️ Derived from 🟩 GitHub |
| `v-s2-kpi1` | card | `[Code Acceptance Rate]` | ⚙️ Derived from 🟩 GitHub |
| `v-s2-kpi2` | card | `[Chat Sessions]` | 🟩 GitHub |
| `v-s2-kpi3` | card | `[Agent Sessions]` | 🟩 GitHub |
| `v-s3-kpi1` | card | `[Median PR Cycle Time (hrs)]` | 🟩 GitHub Pulls API |
| `v-s3-kpi2` | card | `[PRs Merged]` | 🟩 GitHub Pulls API |
| `v-s3-kpi3` | card | `[Estimated Hours Saved]` | ⚙️ Derived (`Suggestions Accepted` × Assumptions) |
| `v-s4-kpi1` | card | `[Change Failure Rate]` | ⚙️ Derived from 🟩 GitHub Deployments + Issues |
| `v-s4-kpi2` | card | `[Test Coverage %]` | 🟩 GitHub Actions artifact / repo file |
| `v-s4-kpi3` | card | `[MTTR (hrs)]` | 🟩 GitHub Issues (`label:incident`) |
| `v-s5-kpi1` | card | `[Net Value]` | ⚙️ Derived |
| `v-s5-kpi2` | card | `[Capacity Released (FTEs)]` | ⚙️ Derived |
| `v-s5-kpi3` | card | `[ROI %]` | ⚙️ Derived |
| `v-s6-kpi1` | card | `[Inactive Seats]` | ⚙️ Derived from 🟩 GitHub |
| `v-s6-kpi2` | card | `[Vulnerabilities Introduced]` | 🟩 GitHub GHAS |
| `v-s6-kpi3` | card | `[Copilot Investment]` | ⚙️ Derived from 🟨 Assumptions |

### 4.2 `p01execscore` — Executive Value Scorecard

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p1-title` / `v-p1-subtitle` / `v-p1-insight` | textbox | Static copy | 🟨 Manual |
| `v-p1-slicer-bu` / `-team` / `-date` | slicer | `BusinessUnit`, `Team`, `YearMonth` | 🟨 Manual / ⚙️ Derived |
| `v-p1-kpi-adoption` | card | `[Adoption Rate]` | ⚙️ Derived from 🟩 GitHub |
| `v-p1-kpi-sustained` | card | `[Sustained Usage %]` | ⚙️ Derived from 🟩 GitHub |
| `v-p1-kpi-cycle` | card | `[Median PR Cycle Time (hrs)]` | 🟩 GitHub Pulls API |
| `v-p1-kpi-quality` | card | `[Change Failure Rate]` | 🟩 GitHub Deployments + Issues |
| `v-p1-kpi-capacity` | card | `[Estimated Hours Saved]` | ⚙️ Derived |
| `v-p1-kpi-value` | card | `[Net Value]` | ⚙️ Derived |
| `v-p1-trend-adoption` | lineChart | `WeekStart` × (`[Active Users]`, `[Sustained Users]`) | 🟩 GitHub Copilot metrics |
| `v-p1-trend-delivery` | line-column combo | `YearMonth` × (`[Deployments]`, `[Median PR Cycle Time (hrs)]`) | 🟩 GitHub Deployments + Pulls |
| `v-p1-trend-quality` | lineChart | `YearMonth` × (`[Change Failure Rate]`, `[Test Coverage %]`) | 🟩 GitHub Deployments + Actions artifact |
| `v-p1-valuechain` | funnel | `ValueChain[StepName]` × `[Value Chain Count]` | 🟨 Reference + ⚙️ Derived |
| `v-p1-waterfall` | waterfall | `YearMonth` × `[Net Value]` | ⚙️ Derived |
| `v-p1-bu-perf` | table | `BusinessUnit`, `Team`, `[Adoption Rate]`, `[Sustained Usage %]`, `[Median PR Cycle Time (hrs)]`, `[Change Failure Rate]`, `[Net Value]` | 🟨 + 🟩 GitHub + ⚙️ Derived |

### 4.3 `p02adoption` — Adoption

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p2-title` | textbox | Page title | 🟨 Manual |
| `v-p2-slicer` | slicer | `BusinessUnit` | 🟨 Manual |
| `v-p2-kpi-assigned` | card | `[Assigned Seats]` | 🟩 GitHub Seats API |
| `v-p2-kpi-active` | card | `[Active Users]` | 🟩 GitHub Copilot metrics |
| `v-p2-kpi-adoprate` | card | `[Adoption Rate]` | ⚙️ Derived |
| `v-p2-kpi-sustained` | card | `[Sustained Users]` | 🟩 GitHub |
| `v-p2-kpi-inactive` | card | `[Inactive Seats]` | ⚙️ Derived |
| `v-p2-kpi-ttfu` | card | `[Avg Days to First Use]` | ⚙️ Derived from 🟩 GitHub |
| `v-p2-funnel` | funnel | `ValueChain[StepName]` × `[Value Chain Count]` | 🟨 + ⚙️ |
| `v-p2-wau-trend` | lineChart | `WeekStart` × `BusinessUnit` × (`[Active Users]`, `[Weekly Active Users]`, `[Sustained Users]`) | 🟩 GitHub |
| `v-p2-heatmap` | pivotTable | `BusinessUnit`, `Team` × `[Assigned Seats]`, `[Active Users]`, `[Adoption Rate]`, `[Sustained Usage %]`, `[Copilot Satisfaction]`, `[Cost per Active User]` | 🟨 + 🟩 + 🟪 + ⚙️ |

### 4.4 `p03usage` — Usage & Engagement

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p3-title` | textbox | Page title | 🟨 Manual |
| `v-p3-kpi-accepted` | card | `[Suggestions Accepted]` | 🟩 GitHub Copilot metrics |
| `v-p3-kpi-accrate` | card | `[Code Acceptance Rate]` | ⚙️ Derived |
| `v-p3-kpi-chat` | card | `[Chat Sessions]` | 🟩 GitHub |
| `v-p3-kpi-agent` | card | `[Agent Sessions]` | 🟩 GitHub |
| `v-p3-kpi-caprm` | card | `[Coding Agent PRs Merged]` | 🟩 GitHub Pulls (`copilot-swe-agent`) |
| `v-p3-kpi-credits` | card | `[AI Credits Consumed]` | 🟩 GitHub Copilot billing |
| `v-p3-feature-bar` | 100% stacked bar | `Team` × `FeatureName` × `[Suggestions Accepted]` | 🟩 GitHub + 🟨 Reference |
| `v-p3-scatter` | scatter | `Team` × (`[Active Users]`, `[Sustained Usage %]`, `[Median PR Cycle Time (hrs)]`) | 🟩 GitHub |
| `v-p3-costtable` | table | `BusinessUnit`, `Team`, `[AI Credits Consumed]`, `[AI Credit Cost]`, `[Licence Cost]`, `[Copilot Investment]`, `[Cost per Active User]` | 🟩 GitHub + 🟨 Assumptions + ⚙️ |

### 4.5 `p04productivity` — Productivity

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p4-title` | textbox | Page title | 🟨 Manual |
| `v-p4-kpi-cycle` | card | `[Median PR Cycle Time (hrs)]` | 🟩 GitHub Pulls API |
| `v-p4-kpi-tfr` | card | `[Avg Time to First Review (hrs)]` | 🟩 GitHub Reviews API |
| `v-p4-kpi-prs` | card | `[PRs Merged]` | 🟩 GitHub Pulls API |
| `v-p4-kpi-deploy` | card | `[Deployments]` | 🟩 GitHub Deployments / Actions |
| `v-p4-kpi-throughput` | card | `[Throughput per Active Engineer]` | ⚙️ Derived |
| `v-p4-kpi-rework` | card | `[Rework Rate]` | ⚙️ Derived from 🟩 GitHub Commits |
| `v-p4-baseline-bar` | clustered bar | `Team` × (`[Median PR Cycle Time (hrs)]`, `[Avg Time to First Review (hrs)]`, `[Avg Lead Time (hrs)]`) | 🟩 GitHub Pulls + Deployments |
| `v-p4-control` | lineChart | `WeekStart` × `BusinessUnit` × `[Median PR Cycle Time (hrs)]` | 🟩 GitHub Pulls |
| `v-p4-cohort-table` | table | `BusinessUnit`, `Team`, `[PRs Merged]`, `[Median PR Cycle Time (hrs)]`, `[Deployments]`, `[Rework Rate]`, `[Flow State Score]`, `[Copilot Satisfaction]` | 🟩 GitHub + 🟪 Survey |

### 4.6 `p05quality` — Quality

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p5-title` | textbox | Page title | 🟨 Manual |
| `v-p5-kpi-defects` | card | `[Escaped Defects]` | 🟩 GitHub Issues (`label:prod-defect`) |
| `v-p5-kpi-cfr` | card | `[Change Failure Rate]` | ⚙️ Derived from 🟩 GitHub Deployments + Issues |
| `v-p5-kpi-coverage` | card | `[Test Coverage %]` | 🟩 GitHub Actions artifact / repo file |
| `v-p5-kpi-vuln` | card | `[Vulnerabilities Introduced]` | 🟩 GitHub GHAS code-scanning |
| `v-p5-kpi-mttr` | card | `[MTTR (hrs)]` | 🟩 GitHub Issues (`label:incident`) |
| `v-p5-quadrant` | scatter | `Team` × (`[PRs Merged]`, `[Median PR Cycle Time (hrs)]`, `[Change Failure Rate]`) | 🟩 GitHub |
| `v-p5-trend` | lineChart | `YearMonth` × `BusinessUnit` × (`[Escaped Defects]`, `[Rework Rate]`) | 🟩 GitHub |
| `v-p5-scorecard` | table | `BusinessUnit`, `Team`, `[Escaped Defects]`, `[Change Failure Rate]`, `[Test Coverage %]`, `[Test Pass Rate]`, `[Build Success Rate]`, `[Vulnerabilities Introduced]`, `[MTTR (hrs)]`, `[Tech Debt Items]` | 🟩 GitHub (Issues + Actions + GHAS) |

### 4.7 `p06bizvalue` — Business Value

| Visual | Type | Data point | Source |
|---|---|---|---|
| `v-p6-title` / `v-p6-narrative` | textbox | Static copy | 🟨 Manual |
| `v-p6-kpi-invest` | card | `[Copilot Investment]` | ⚙️ Derived from 🟨 Assumptions + 🟩 GitHub |
| `v-p6-kpi-gross` | card | `[Gross Capacity Value]` | ⚙️ Derived |
| `v-p6-kpi-avoided` | card | `[Avoided Defect Cost]` | ⚙️ Derived from 🟩 GitHub + 🟨 Assumptions |
| `v-p6-kpi-net` | card | `[Net Value]` | ⚙️ Derived |
| `v-p6-kpi-roi` | card | `[ROI %]` | ⚙️ Derived |
| `v-p6-kpi-bcr` | card | `[Benefit-Cost Ratio]` | ⚙️ Derived |
| `v-p6-waterfall` | waterfall | `YearMonth` × `[Net Value]` | ⚙️ Derived |
| `v-p6-unit-costs` | table | `BusinessUnit`, `Team`, `[Copilot Investment]`, `[Estimated Hours Saved]`, `[Capacity Released (FTEs)]`, `[Gross Capacity Value]`, `[Net Value]`, `[ROI %]`, `[Cost per Active User]`, `[Cost per Sustained User]`, `[Cost per Merged PR]` | ⚙️ Derived |

### 4.8 Tooltip pages (`pt-*`)

Unchanged from [README.md §4.8](README.md#48-tooltip-pages-pt-). Content is 🟨 Manual and generated by [scripts/add_tooltip_pages.py](scripts/add_tooltip_pages.py).

---

## 5. Measure calculation reference

Identical to [README.md §5](README.md#5-measure-calculation-reference). DAX does not change when the upstream data source moves — it is bound to the fact-table columns, which retain their names.

---

## 6. Moving from synthetic data to live GitHub APIs

> The full implementation walkthrough — Fabric workspace setup, GitHub App registration and scopes, Power Query helpers (`fnGitHubToken`, `fnPagedGet`, `fnGraphQL`, `fnRepoFile`), per-endpoint M code for Copilot / Pulls (GraphQL) / Deployments / Actions runs / Issues / GHAS, IssueOps labels & workflows, test & coverage publishing patterns, incremental refresh windows and a validation checklist — lives in [docs/data-ingestion-guide.github.md](docs/data-ingestion-guide.github.md). The summary below is the quick-start.

The three fact tables and `DimDeveloper` currently define their data inline via Power Query `let ... in`. To make the report live using **only GitHub**:

1. **Register a GitHub App** (org- or enterprise-installed) with these scopes:
   - `copilot` (metrics + billing), `members:read`
   - `contents:read`, `pull_requests:read`, `actions:read`, `deployments:read`, `issues:read`
   - `security_events:read` (for GHAS code-scanning, dependabot, secret-scanning alerts)
2. **Create a Fabric dataflow** with one query per endpoint below. Land historic snapshots to a lakehouse — the Copilot metrics API only serves the last ~28 days.
   - `Copilot Metrics — Team Daily` → `FactTeamDaily` Copilot columns.
   - `Copilot Metrics — Feature Daily` → `FactFeatureDaily`.
   - `Copilot Seats` → `DimDeveloper`.
   - `GitHub Pulls (REST or GraphQL)` → `PRsMerged`, `PRCycleTimeHours`, `TimeToFirstReviewHours`, `ReworkedPRs`, `LeadTimeHours`.
   - `GitHub Deployments + Actions Runs` → `Deployments`, `FailedDeployments`, `BuildRuns`, `BuildSuccesses`, `TotalChanges`, `ChangeFailures`.
   - `GitHub Actions Artifacts / repo file` → `TestsRun`, `TestsPassed`, `TestCoveragePct`.
   - `GitHub Search / Issues` → `EscapedDefects`, `MTTRHours`, `TechDebtItems`.
   - `GHAS Alerts` → `VulnerabilitiesIntroduced`.
   - `DX Survey CSV` → `FlowStateScore`, `ToolingSatisfaction`, `CopilotSatisfaction`.
3. **Commit `DimBusinessUnit`, `DimFeature`, `ValueChain`, `Assumptions`** as CSV in a governance repo. Load each via `GET /repos/{o}/{r}/contents/{path}` so every change is versioned in Git.
4. **Replace each table's inline `source =`** in the `.tmdl` partitions with `Source = PowerPlatform.Dataflows(null){[workspaceId=...]}{...}` referencing the corresponding dataflow entity. Column names and types are already aligned — no measure changes required.
5. Optionally, gate the current synthetic partitions behind a `Parameter[UseSampleData]` switch so the report still opens for demos without credentials.

### Suggested GitHub Actions / IssueOps conventions

To keep everything on GitHub, adopt these organisation-wide labels & workflows:

| Signal | Convention |
|---|---|
| Production defect | Issue in the service repo with `label:prod-defect` and `label:severity/{sev}`. |
| Incident | Issue with `label:incident`; opened by an `/incident open` slash-command workflow, closed with `/incident resolve`. `closed_at − created_at` = MTTR. |
| Change failure | Deployment with `state=failure` **or** a rollback deployment referencing the same commit within 24 h. |
| Tech debt | Issue with `label:tech-debt`. Counted open at month end. |
| Test results / coverage | CI workflow publishes `junit.xml` and `coverage-summary.json` as `actions/artifacts`; a scheduled workflow uploads the monthly rollup to `metrics/` in a central `engineering-metrics` repo. |
| Assumptions & org map | Kept as `assumptions.csv` and `orgmap.csv` in the `engineering-metrics` repo. CODEOWNERS restricts edits to Finance / HR. |

---

## 7. Regenerating the tooltip pages

Unchanged — see [README.md §7](README.md#7-regenerating-the-tooltip-pages):

```powershell
python scripts/add_tooltip_pages.py
```
