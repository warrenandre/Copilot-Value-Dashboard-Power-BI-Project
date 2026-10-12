# Data Ingestion Guide — GitHub-only edition

Companion to [../README.github.md](../README.github.md). Shows **step-by-step how to replace the inline synthetic Power Query partitions with live data from the GitHub platform only** — no Azure DevOps — and how to capture that data in Power BI / Microsoft Fabric.

> **Scope**: PRs, builds, deployments, test results, defects, incidents and tech-debt all come from GitHub (Pulls, Reviews, Actions, Deployments, Issues, GHAS). For the hybrid variant that uses Azure DevOps for SDLC data, see [data-ingestion-guide.md](data-ingestion-guide.md).

---

## 0. Target architecture

```
┌─────────────────────────────────────────────────┐
│ GitHub (REST / GraphQL / Actions / GHAS)         │
│  • Copilot Metrics + Billing + Seats             │
│  • Pulls + Reviews + Commits (DORA signals)      │
│  • Deployments + Actions Runs + Artifacts        │
│  • Issues (prod-defect / incident / tech-debt)   │
│  • GHAS code-scanning / dependabot / secret-scan │
│  • Governance repo (orgmap.csv, assumptions.csv) │
└───────────────────────┬─────────────────────────┘
                        │
                        ▼
      ┌────────────────────────────────────────┐
      │ Fabric Dataflow Gen2                   │
      │  one query per endpoint → bronze tables│
      └───────────────────┬────────────────────┘
                          │
                          ▼
      ┌────────────────────────────────────────┐
      │ Fabric Lakehouse (bronze → silver)     │
      │  silver_fact_team_daily, _feature,     │
      │  silver_fact_monthly_quality,          │
      │  silver_dim_developer                  │
      └───────────────────┬────────────────────┘
                          │
                          ▼
      ┌────────────────────────────────────────┐
      │ Semantic model (DirectLake on silver)  │
      └────────────────────────────────────────┘
```

The Copilot Metrics API only returns the **last ~28 days** and GHAS alert history is only accurate at the current snapshot. Everything must land to the Lakehouse daily so you can rebuild historic months.

---

## 1. Prerequisites

### 1.1 GitHub App — the only credential you need

Register a **GitHub App** at the organisation (or enterprise) level with the following permissions:

| Resource | Access | Needed for |
|---|---|---|
| Organization › GitHub Copilot Business | Read | Copilot metrics, billing, seats |
| Organization › Members | Read | Team membership → `DimDeveloper[TeamKey]` |
| Organization › Administration | Read | Enterprise usage endpoint (AI credits) |
| Repository › Metadata | Read | Repo list enumeration |
| Repository › Contents | Read | Governance repo CSVs, coverage artifacts |
| Repository › Pull requests | Read | Pulls, reviews, commits (DORA signals) |
| Repository › Actions | Read | Workflow runs + artifacts |
| Repository › Deployments | Read | Deployment events + statuses |
| Repository › Issues | Read | Defects, incidents, tech-debt |
| Repository › Code scanning alerts | Read | Vulnerabilities |
| Repository › Dependabot alerts | Read | Dependency vulnerabilities |
| Repository › Secret scanning alerts | Read | Leaked-secret alerts |

Install the App on the org. Capture:

- **App ID** → Key Vault secret `github-app-client-id`
- **Private key (`.pem`)** → Key Vault secret `github-app-private-key`
- **Installation ID** (`GET /orgs/{org}/installation`) → Key Vault secret `github-app-installation-id`

Nothing else is required. No PATs, no ADO, no incident tool — all signals land on GitHub.

### 1.2 Fabric workspace

1. Create workspace `copilot-value-prod`.
2. Add Lakehouse `copilot_value_lh`.
3. Add Dataflow Gen2 `copilot_value_ingest`.
4. Attach a **Key Vault connection** (`Settings → Manage connections → + New → Azure Key Vault`).

### 1.3 Semantic model parameters

| Parameter | Example | Purpose |
|---|---|---|
| `GitHubOrg` | `"contoso-eng"` | Target organisation (or `enterprise` for enterprise APIs) |
| `GovernanceRepo` | `"contoso-eng/governance"` | Repo holding `orgmap.csv`, `assumptions.csv` |
| `MetricsRepo` | `"contoso-eng/engineering-metrics"` | Repo holding monthly CI coverage rollups |
| `LakehousePath` | `"abfss://..."` | Lakehouse ABFSS URL |
| `UseSampleData` | `false` | Keep inline synthetic partitions when `true` |

---

## 2. Shared Power Query helpers

Add these as blank queries in the dataflow.

### 2.1 `fnGitHubToken` — mint an installation token

Identical to the hybrid guide. See [data-ingestion-guide.md §2.1](data-ingestion-guide.md#21-fngithubtoken--exchange-app-credentials-for-an-installation-token). The JWT must be signed with the App's private key — use the included Azure Function template at `scripts/sign-jwt/`.

### 2.2 `fnPagedGet` — follow `Link: rel="next"`

Identical to the hybrid guide. See [data-ingestion-guide.md §2.2](data-ingestion-guide.md#22-fnpagedget--follow-github-link-relnext-pagination).

### 2.3 `fnGraphQL` — call the GitHub GraphQL API

GraphQL is far cheaper than REST for PR-heavy pulls because you can request only the fields you need.

```powerquery
(token as text, query as text, variables as record) as record =>
let
    body = Json.FromValue([query = query, variables = variables]),
    resp = Web.Contents("https://api.github.com", [
        RelativePath = "/graphql",
        Headers = [
            Authorization = "Bearer " & token,
            Accept = "application/vnd.github+json",
            #"X-GitHub-Api-Version" = "2022-11-28",
            #"Content-Type" = "application/json"
        ],
        Content = body
    ]),
    data = Json.Document(resp)
in
    data
```

### 2.4 `fnRepoFile` — read a file from any repo

Used for the governance CSVs and the monthly coverage rollup.

```powerquery
(token as text, repoFullName as text, path as text) as binary =>
let
    resp = Web.Contents("https://api.github.com", [
        RelativePath = "/repos/" & repoFullName & "/contents/" & path,
        Headers = [
            Authorization = "Bearer " & token,
            Accept = "application/vnd.github.raw"
        ]
    ])
in
    resp
```

### 2.5 `fnSecrets` — Key Vault secrets

```powerquery
() as record =>
let
    kv = "https://kv-copilot-value.vault.azure.net/",
    get = (name) => AzureKeyVault.Contents(kv){[Name=name]}[Content]
in
    [
        GitHubAppId          = Text.FromBinary(get("github-app-client-id")),
        GitHubPrivateKey     = Text.FromBinary(get("github-app-private-key")),
        GitHubInstallationId = Text.FromBinary(get("github-app-installation-id"))
    ]
```

---

## 3. Copilot ingestion

### 3.1 Copilot Metrics — team daily → `bronze_github_copilot_team`

Identical to the hybrid guide [§3.1](data-ingestion-guide.md#31-copilot-metrics--team-daily--bronze_github_copilot_team). Drives `ActiveUsers`, `EngagedUsers`, `WeeklyActiveUsers`, `SuggestionsMade`, `SuggestionsAccepted`, `LinesAccepted`, `ChatSessions`, `AgentSessions`.

### 3.2 Copilot Metrics — feature daily → `bronze_github_copilot_feature`

Identical to the hybrid guide [§3.2](data-ingestion-guide.md#32-copilot-metrics--feature-daily--bronze_github_copilot_feature).

### 3.3 Copilot Seats → `DimDeveloper`

Identical to the hybrid guide [§3.3](data-ingestion-guide.md#33-copilot-seats--bronze_github_seats--drives-dimdeveloper). The user-level metrics endpoint produces `FirstUseDate`, `TotalActiveWeeks`, `IsActivated`, `IsSustained`.

### 3.4 Enterprise usage → `AICreditsConsumed`

Identical to the hybrid guide [§3.4](data-ingestion-guide.md#34-copilot-billing-ai-credits--aicreditsconsumed).

### 3.5 GHAS code-scanning alerts → `VulnerabilitiesIntroduced`

Identical to the hybrid guide [§3.5](data-ingestion-guide.md#35-ghas-code-scanning-alerts--vulnerabilitiesintroduced). Also pull dependabot and secret-scanning alerts if you want a fuller security view:

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    deps  = List.Combine(fnPagedGet("https://api.github.com", "/orgs/" & #"GitHubOrg" & "/dependabot/alerts", token, [state="open", per_page="100"])),
    secs  = List.Combine(fnPagedGet("https://api.github.com", "/orgs/" & #"GitHubOrg" & "/secret-scanning/alerts", token, [state="open", per_page="100"]))
in
    [Dependabot = deps, SecretScanning = secs]
```

Merge all three alert families into `silver_fact_monthly_quality.VulnerabilitiesIntroduced` grouping by (`YearMonth`, `TeamKey`).

---

## 4. SDLC ingestion (GitHub-only)

### 4.1 Pull requests → `bronze_github_pulls`

Drives `PRsMerged`, `PRCycleTimeHours`, `TimeToFirstReviewHours`, `LeadTimeHours`, `ReworkedPRs`.

Use **GraphQL** — one request returns PR + first-review + first-commit timestamps, so you avoid the N+1 REST problem.

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    repos = DimBusinessUnit[GitHubRepos],
    gql = "
      query($owner:String!, $repo:String!, $since:DateTime!, $cursor:String) {
        repository(owner:$owner, name:$repo) {
          pullRequests(states:MERGED, first:100, after:$cursor, orderBy:{field:UPDATED_AT, direction:DESC}) {
            pageInfo { endCursor hasNextPage }
            nodes {
              number
              createdAt
              mergedAt
              author { login }
              commits(first:1) { nodes { commit { committedDate } } }
              reviews(first:1, states:[APPROVED, CHANGES_REQUESTED, COMMENTED]) {
                nodes { submittedAt }
              }
              deployments(first:1, environments:[\"production\"], orderBy:{field:CREATED_AT, direction:ASC}) {
                nodes { createdAt }
              }
              files(first:50) { nodes { path } }
            }
          }
        }
      }",
    pagePR = (owner, repo, cursor) =>
        let
            r = fnGraphQL(token, gql, [owner=owner, repo=repo, cursor=cursor, since=Date.ToText(Date.AddDays(Date.From(DateTime.FixedUtcNow()), -400), "yyyy-MM-ddTHH:mm:ssZ")]),
            pi = r[data][repository][pullRequests][pageInfo]
        in
            [nodes = r[data][repository][pullRequests][nodes], next = if pi[hasNextPage] then pi[endCursor] else null],
    perRepo = List.Transform(repos, (fullname) =>
        let
            parts = Text.Split(fullname, "/"),
            owner = parts{0}, repo = parts{1},
            pages = List.Generate(
                () => [state = pagePR(owner, repo, null)],
                each [state][nodes] <> null,
                each [state = if [state][next] = null then [nodes=null, next=null] else pagePR(owner, repo, [state][next])],
                each [state][nodes]
            ),
            flat = List.Combine(pages),
            rows = List.Transform(flat, (pr) =>
                let
                    firstCommit = try DateTimeZone.FromText(pr[commits][nodes]{0}[commit][committedDate]) otherwise null,
                    firstReview = try DateTimeZone.FromText(pr[reviews][nodes]{0}[submittedAt]) otherwise null,
                    firstDeploy = try DateTimeZone.FromText(pr[deployments][nodes]{0}[createdAt]) otherwise null,
                    created = DateTimeZone.FromText(pr[createdAt]),
                    merged  = DateTimeZone.FromText(pr[mergedAt])
                in [
                    RepoFullName = fullname,
                    PRNumber = pr[number],
                    AuthorLogin = pr[author][login],
                    CreatedAt = created,
                    MergedAt = merged,
                    FirstCommitAt = firstCommit,
                    FirstReviewAt = firstReview,
                    FirstDeployAt = firstDeploy,
                    PRCycleTimeHours = Duration.TotalHours(merged - created),
                    TimeToFirstReviewHours = if firstReview = null then null else Duration.TotalHours(firstReview - created),
                    LeadTimeHours = if firstDeploy = null or firstCommit = null then null else Duration.TotalHours(firstDeploy - firstCommit),
                    TouchedFiles = Text.Combine(List.Transform(pr[files][nodes], each _[path]), "|"),
                    Date = Date.From(merged)
                ])
        in rows),
    tbl = Table.FromRecords(List.Combine(perRepo))
in
    tbl
```

**`ReworkedPRs`** — compute in a silver SQL view: a merged PR is "reworked" if **any** of its `TouchedFiles` appears in another merged PR within 21 days.

```sql
CREATE OR REPLACE VIEW silver_pulls_reworked AS
WITH files AS (
  SELECT PRNumber, RepoFullName, MergedAt,
         explode(split(TouchedFiles, '\\|')) AS Path
  FROM bronze_github_pulls
)
SELECT a.PRNumber, a.RepoFullName, a.MergedAt
FROM files a
JOIN files b
  ON a.RepoFullName = b.RepoFullName
 AND a.Path = b.Path
 AND b.MergedAt > a.MergedAt
 AND b.MergedAt <= a.MergedAt + INTERVAL 21 DAYS
GROUP BY a.PRNumber, a.RepoFullName, a.MergedAt;
```

### 4.2 Deployments → `bronze_github_deployments`

Drives `Deployments`, `FailedDeployments`, `TotalChanges`, plus the `ChangeFailures` join.

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    repos = DimBusinessUnit[GitHubRepos],
    perRepo = List.Transform(repos, (fullname) =>
        let
            deps = List.Combine(fnPagedGet("https://api.github.com", "/repos/" & fullname & "/deployments",
                token, [environment="production", per_page="100"])),
            rows = List.Transform(deps, (d) =>
                let
                    statuses = Json.Document(Web.Contents("https://api.github.com", [
                        RelativePath = "/repos/" & fullname & "/deployments/" & Text.From(d[id]) & "/statuses",
                        Headers = [Authorization = "Bearer " & token, Accept="application/vnd.github+json"]
                    ])),
                    terminal = try List.First(List.Select(statuses, each List.Contains({"success","failure","error","inactive"}, _[state]))) otherwise null
                in [
                    RepoFullName = fullname,
                    DeploymentId = d[id],
                    Sha = d[sha],
                    Environment = d[environment],
                    CreatedAt = DateTimeZone.FromText(d[created_at]),
                    State = if terminal = null then "unknown" else terminal[state],
                    Date = Date.From(DateTimeZone.FromText(d[created_at]))
                ])
        in rows),
    tbl = Table.FromRecords(List.Combine(perRepo))
in
    tbl
```

Silver rollup for team-daily counts:

```sql
CREATE OR REPLACE VIEW silver_fact_team_daily_deploy AS
SELECT
  d.Date,
  m.TeamKey,
  COUNT_IF(d.State = 'success')                  AS Deployments,
  COUNT_IF(d.State IN ('failure','error'))       AS FailedDeployments,
  COUNT(*)                                       AS TotalChanges
FROM bronze_github_deployments d
JOIN ref_repo_to_team m ON m.RepoFullName = d.RepoFullName
GROUP BY d.Date, m.TeamKey;
```

### 4.3 Actions workflow runs → `BuildRuns`, `BuildSuccesses`

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    repos = DimBusinessUnit[GitHubRepos],
    perRepo = List.Transform(repos, (fullname) =>
        let
            runs = List.Combine(fnPagedGet("https://api.github.com", "/repos/" & fullname & "/actions/runs",
                token, [per_page="100", created=">=" & Date.ToText(Date.AddDays(Date.From(DateTime.FixedUtcNow()), -40), "yyyy-MM-dd")])),
            flat = List.Combine(List.Transform(runs, each _[workflow_runs])),
            rows = List.Transform(flat, (r) => [
                RepoFullName = fullname,
                RunId        = r[id],
                WorkflowId   = r[workflow_id],
                WorkflowName = r[name],
                Event        = r[event],
                Conclusion   = r[conclusion],
                CreatedAt    = DateTimeZone.FromText(r[created_at]),
                Date         = Date.From(DateTimeZone.FromText(r[created_at])),
                IsCI         = Text.Contains(Text.Lower(r[name]), "ci") or Text.Contains(Text.Lower(r[name]), "build") or Text.Contains(Text.Lower(r[name]), "test")
            ])
        in rows),
    tbl = Table.FromRecords(List.Combine(perRepo))
in
    tbl
```

Silver:

```sql
CREATE OR REPLACE VIEW silver_fact_team_daily_build AS
SELECT
  r.Date,
  m.TeamKey,
  COUNT_IF(r.IsCI)                              AS BuildRuns,
  COUNT_IF(r.IsCI AND r.Conclusion='success')   AS BuildSuccesses
FROM bronze_github_actions_runs r
JOIN ref_repo_to_team m ON m.RepoFullName = r.RepoFullName
GROUP BY r.Date, m.TeamKey;
```

### 4.4 Test results & coverage → `TestsRun`, `TestsPassed`, `TestCoveragePct`

Three options, pick what your CI emits:

**(a) check-runs** — if your test framework publishes a GitHub check-run with a `summary` containing counts:

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    repos = DimBusinessUnit[GitHubRepos],
    // for each run from §4.3 fetch check-runs on the head SHA
    checks = Table.AddColumn(bronze_github_actions_runs, "Checks", (r) =>
        Json.Document(Web.Contents("https://api.github.com", [
            RelativePath = "/repos/" & r[RepoFullName] & "/commits/" & r[HeadSha] & "/check-runs",
            Headers = [Authorization = "Bearer " & token, Accept = "application/vnd.github+json"]
        ]))[check_runs])
in
    checks
```

**(b) JUnit artifact** — if CI uploads `junit.xml` as an artifact:

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    arts = List.Combine(fnPagedGet("https://api.github.com", "/repos/" & #"RepoFullName" & "/actions/artifacts", token, [name="junit", per_page="100"])),
    rows = List.Transform(arts, (a) =>
        let
            bin = Web.Contents(a[archive_download_url], [Headers=[Authorization="Bearer " & token]]),
            // artifact zip ↔ unzip ↔ parse — do this in a Fabric Notebook, not Power Query
            runId = a[workflow_run][id]
        in
            [RunId = runId, ArtifactUrl = a[archive_download_url], ExpiresAt = DateTimeZone.FromText(a[expires_at])])
in
    Table.FromRecords(rows)
```

Download + unzip + XML parse happens in a Fabric Notebook that writes `silver_fact_test_runs` (RunId, TestsRun, TestsPassed).

**(c) committed JSON summary** — simplest and recommended. Have each CI pipeline run end with:

```yaml
- name: Publish test & coverage summary
  run: |
    jq -n --arg date "$(date -u +%Y-%m-%d)" \
          --arg sha  "$GITHUB_SHA" \
          --argjson tests_run    $TESTS_RUN \
          --argjson tests_passed $TESTS_PASSED \
          --argjson coverage_pct $COVERAGE_PCT \
          '{date:$date, sha:$sha, tests_run:$tests_run, tests_passed:$tests_passed, coverage_pct:$coverage_pct}' \
      > metrics/${{ github.event.repository.name }}-$(date -u +%Y-%m).json
  env:
    TESTS_RUN:    ${{ steps.test.outputs.total }}
    TESTS_PASSED: ${{ steps.test.outputs.passed }}
    COVERAGE_PCT: ${{ steps.coverage.outputs.pct }}

- name: Commit
  uses: stefanzweifel/git-auto-commit-action@v5
  with:
    file_pattern: metrics/*.json
    repository: contoso-eng/engineering-metrics
```

Then Power Query reads the committed JSON directly:

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    listing = Json.Document(Web.Contents("https://api.github.com", [
        RelativePath = "/repos/" & #"MetricsRepo" & "/contents/metrics",
        Headers = [Authorization = "Bearer " & token, Accept = "application/vnd.github+json"]
    ])),
    rows = List.Transform(listing, (f) =>
        let
            raw = Json.Document(fnRepoFile(token, #"MetricsRepo", "metrics/" & f[name])),
            parts = Text.Split(Text.Replace(f[name], ".json", ""), "-"),
            repo = Text.Combine(List.FirstN(parts, List.Count(parts)-1), "-"),
            ym   = List.Last(parts)
        in [
            RepoName = repo,
            YearMonth = ym,
            Date = Date.FromText(ym & "-01"),
            TestsRun = raw[tests_run],
            TestsPassed = raw[tests_passed],
            TestCoveragePct = raw[coverage_pct]
        ])
in
    Table.FromRecords(rows)
```

### 4.5 Issues — defects, incidents, tech debt

**One query per label**, driven by the search API — far faster than listing issues per repo.

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    search = (label) =>
        List.Combine(fnPagedGet("https://api.github.com", "/search/issues", token, [
            q = "org:" & #"GitHubOrg" & " is:issue label:" & label & " created:>=" & Date.ToText(Date.AddDays(Date.From(DateTime.FixedUtcNow()), -400), "yyyy-MM-dd"),
            per_page = "100"
        ])),
    toRows = (items, kind) => List.Transform(items, (i) => [
        Kind       = kind,
        IssueId    = i[id],
        Number     = i[number],
        RepoUrl    = i[repository_url],
        State      = i[state],
        CreatedAt  = DateTimeZone.FromText(i[created_at]),
        ClosedAt   = if i[closed_at] = null then null else DateTimeZone.FromText(i[closed_at]),
        ResolutionHours = if i[closed_at] = null then null else Duration.TotalHours(DateTimeZone.FromText(i[closed_at]) - DateTimeZone.FromText(i[created_at])),
        Labels     = Text.Combine(List.Transform(i[items], each _[name]), "|"),
        YearMonth  = Date.ToText(Date.From(DateTimeZone.FromText(i[created_at])), "yyyy-MM")
    ]),
    defects   = toRows(List.Combine(List.Transform(search("prod-defect"), each _[items])), "defect"),
    incidents = toRows(List.Combine(List.Transform(search("incident"),    each _[items])), "incident"),
    debt      = toRows(List.Combine(List.Transform(search("tech-debt"),   each _[items])), "techdebt")
in
    Table.FromRecords(defects & incidents & debt)
```

Silver rollups per team-month:

```sql
CREATE OR REPLACE VIEW silver_fact_monthly_quality_issues AS
SELECT
  i.YearMonth,
  m.TeamKey,
  COUNT_IF(i.Kind = 'defect')               AS EscapedDefects,
  AVG(CASE WHEN i.Kind = 'incident' THEN i.ResolutionHours END) AS MTTRHours,
  COUNT_IF(i.Kind = 'techdebt' AND i.State='open') AS TechDebtItems
FROM bronze_github_issues i
JOIN ref_repo_to_team m ON m.RepoFullName = replace(i.RepoUrl, 'https://api.github.com/repos/', '')
GROUP BY i.YearMonth, m.TeamKey;
```

### 4.6 Change-failure rate — joining deployments to incidents

A deployment is a **change failure** if an incident issue (with `label:incident`) is created in the same repo within 24 h of the deployment.

```sql
CREATE OR REPLACE VIEW silver_change_failures AS
SELECT d.Date, d.RepoFullName, d.DeploymentId
FROM bronze_github_deployments d
JOIN bronze_github_issues i
  ON i.Kind = 'incident'
 AND replace(i.RepoUrl, 'https://api.github.com/repos/', '') = d.RepoFullName
 AND i.CreatedAt BETWEEN d.CreatedAt AND d.CreatedAt + INTERVAL 24 HOURS
WHERE d.State = 'success';   -- the deploy appeared to succeed but caused an incident
```

Combined with `TotalChanges` from §4.2 gives `ChangeFailureRate`.

---

## 5. Reference / manual data (from a Git-versioned repo)

### 5.1 `DimBusinessUnit` — load `orgmap.csv` from the governance repo

| Column | Notes |
|---|---|
| `TeamKey` | Stable integer key |
| `BusinessUnit`, `Portfolio`, `Team`, `CostCentre` | HR / Finance |
| `EligibleDevelopers` | HR head-count |
| `GitHubTeamSlug` | Join key for Copilot team-level metrics |
| `GitHubRepos` | `|`-separated list of `owner/repo` strings owned by the team |

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    raw = Csv.Document(fnRepoFile(token, #"GovernanceRepo", "orgmap.csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    promoted = Table.PromoteHeaders(raw, [PromoteAllScalars=true])
in
    promoted
```

### 5.2 `Assumptions` — `assumptions.csv` in the same repo

CODEOWNERS the file to `@contoso-eng/finance` so only Finance can merge changes:

```
assumptions.csv  @contoso-eng/finance
```

Load the same way as `orgmap.csv`.

### 5.3 `ref_repo_to_team` — derived from `DimBusinessUnit`

Expand the `|`-separated `GitHubRepos` column:

```sql
CREATE OR REPLACE VIEW ref_repo_to_team AS
SELECT TeamKey, trim(repo) AS RepoFullName
FROM DimBusinessUnit
LATERAL VIEW explode(split(GitHubRepos, '\\|')) AS repo;
```

### 5.4 `DimFeature`, `ValueChain` — keep as inline `#table` partitions.

---

## 6. IssueOps conventions (required for the SDLC signals to work)

For the GitHub-only edition to measure defects, incidents, change failures and tech debt accurately, the organisation must adopt the following labels and workflows. Publish them once in `.github/ISSUE_TEMPLATE/*.yml` of a `.github` repo so they are inherited by every repo.

| Signal | Label | Workflow |
|---|---|---|
| Production defect | `prod-defect` + `severity/{sev1\|sev2\|sev3}` | Issue template `prod-defect.yml`. Opened by Support when a defect reaches production. |
| Incident | `incident` + `severity/{sev1\|sev2}` | Issue template `incident.yml`. `/incident open` slash-command bot opens from Teams/Slack. `/incident resolve` sets `state=closed` → `MTTRHours = closed_at − created_at`. |
| Tech debt | `tech-debt` + `area/{backend\|frontend\|infra}` | Issue template `tech-debt.yml`. |
| Change failure | — | Implicit — any `incident` created within 24 h of a production deployment on the same repo. See §4.6. |
| Required reviewers | — | Branch-protection rule — PRs cannot merge without 1 CODEOWNERS review (ensures `TimeToFirstReviewHours` is populated). |
| CI test & coverage summary | — | Reusable workflow in `.github/workflows/metrics-publish.yml` — commits `metrics/{repo}-{yyyy-MM}.json` to the `engineering-metrics` repo. See §4.4(c). |

A single reusable workflow in your `.github` repo bootstraps every service repo with the required labels on first push:

```yaml
# .github/workflows/bootstrap-labels.yml
on: [workflow_dispatch, repository_dispatch]
jobs:
  labels:
    runs-on: ubuntu-latest
    steps:
      - uses: EndBug/label-sync@v2
        with:
          config-file: https://raw.githubusercontent.com/contoso-eng/.github/main/.github/labels.yml
```

Where `labels.yml` lists `prod-defect`, `incident`, `tech-debt`, `severity/sev1..sev3`, `area/*` with fixed colours.

---

## 7. Loading into the semantic model

Identical to the hybrid guide [§6](data-ingestion-guide.md#6-loading-into-the-semantic-model). Replace each table's inline `partition ... source = let ... in ...` with a Lakehouse-backed source:

```tmdl
partition FactTeamDaily = m
    mode: directLake
    source =
        let
            Source = Lakehouse.Contents([]){[workspaceId=#"WorkspaceId"]}[Data]
                      {[lakehouseId=#"LakehouseId"]}[Data]
                      {[Id="silver_fact_team_daily",ItemKind="Table"]}[Data]
        in
            Source
```

Column names in `silver_fact_team_daily` must match the synthetic schema exactly so no DAX changes are needed.

### 7.1 Mode recommendation

| Table | Mode |
|---|---|
| `DimDate`, `DimBusinessUnit`, `DimFeature`, `Assumptions`, `ValueChain` | Import |
| `DimDeveloper` | DirectLake |
| `FactTeamDaily`, `FactFeatureDaily`, `FactMonthlyQuality` | DirectLake |

---

## 8. Incremental refresh

| Table | Range | History | Refresh |
|---|---|---|---|
| `bronze_github_copilot_team` | 28 days | 2 years | Daily |
| `bronze_github_copilot_feature` | 28 days | 2 years | Daily |
| `bronze_github_seats` | Full | — | Daily snapshot |
| `bronze_github_copilot_user` | 28 days | 2 years | Daily |
| `bronze_github_copilot_usage` | 60 days | 2 years | Daily |
| `bronze_github_pulls` | 7 days | 400 days | 4× daily |
| `bronze_github_deployments` | 7 days | 400 days | Hourly |
| `bronze_github_actions_runs` | 7 days | 400 days | Hourly |
| `bronze_github_issues` | 7 days | 400 days | Daily |
| `bronze_github_code_scanning` | Full snapshot | 2 years | Daily |
| `bronze_github_dependabot` | Full snapshot | 2 years | Daily |
| `bronze_github_secret_scanning` | Full snapshot | 2 years | Daily |
| Metrics-repo coverage files | Full | — | Daily |

Each query uses `RangeStart` / `RangeEnd` parameters inside its `Query` record for the Web.Contents call.

---

## 9. Secrets and rotation

- All secrets in **Azure Key Vault**. The dataflow reads them with `AzureKeyVault.Contents`.
- The dataflow runs under a **Fabric service principal** granted **Key Vault Secrets User**.
- The **GitHub App private key** is the only long-lived credential. Rotate yearly:
  1. Generate a new private key on the App settings page.
  2. Add a **new version** to Key Vault (`github-app-private-key`).
  3. Remove the old key from GitHub after one successful dataflow run.
- Installation tokens are minted at refresh time (10-minute lifetime). Nothing persists.
- No PATs. No per-user credentials. No ADO.

---

## 10. Scheduling

| Job | Schedule |
|---|---|
| Dataflow `copilot_value_ingest` (bronze) | 03:00 SAST daily, plus hourly delta for `pulls`, `deployments`, `actions_runs` |
| Fabric Notebook — JUnit artifact parse (if §4.4(b)) | After every bronze refresh |
| Silver SQL views refresh | After every bronze refresh |
| Semantic model refresh (Import-mode tables) | 04:00 SAST daily |

Fabric Monitor Hub + Teams webhook on >2 consecutive failures.

---

## 11. Row-level security

```dax
[Role: Portfolio Lead]
Filter: DimBusinessUnit[Portfolio] = USERPRINCIPALNAME_LOOKUP()
```

Hold the `userprincipal → portfolio` map in a committed `role-map.csv` in the governance repo and load alongside `orgmap.csv`.

---

## 12. Troubleshooting cheat-sheet

| Symptom | Cause | Fix |
|---|---|---|
| `401 Unauthorized` on `/copilot/metrics` | App not re-authorised after permission change | Re-install the GitHub App on the org |
| `422` with `Metrics for this organization are not available` | Fewer than 5 Copilot users on a team | Fall back to org-level metrics endpoint |
| GraphQL `MAX_NODE_LIMIT_EXCEEDED` | PR query asks for too many nested fields at once | Reduce `first:100` to `first:50`; split into two queries |
| `403 Resource not accessible by integration` on `/code-scanning/alerts` | GHAS not enabled on repo | Enable GHAS, or exclude that repo from the loop |
| `MTTRHours` is BLANK | No issues labelled `incident` yet | Roll out the IssueOps template (§6) org-wide |
| `TestCoveragePct` is BLANK | CI not yet publishing the summary JSON | Add the reusable workflow from §4.4(c) |
| `ChangeFailureRate` is 0 for all teams | `incident` issues not labelled with the service repo as the owner | Keep incidents in the service repo, not a central ops repo |
| Dataflow takes > 2 h | Full history re-pulled every run | Add `RangeStart` / `RangeEnd` to incremental tables |
| `429 rate limit` from GitHub | Pulling PRs via REST | Switch to GraphQL (§4.1) — one call returns PR + review + commit + deploy |
| Mismatch between report and GitHub Copilot admin UI | 28-day window ended before you first ran the dataflow | Backfill is not possible — accept today-forward and build a reconciliation note |

---

## 13. Validation checklist

Before cutting over from the synthetic partitions:

- [ ] `COUNT(*)` on `bronze_github_seats` matches the number of licences on your GitHub bill
- [ ] `MAX(Date)` on every bronze table = yesterday (or current hour for the hourly tables)
- [ ] A sample team's `Suggestions Accepted` for the last 7 days matches the Copilot admin UI (± 1 % rounding)
- [ ] A sample repo's `Deployments` count for the last month matches the GitHub Deployments page
- [ ] A sample repo's `BuildSuccesses / BuildRuns` matches the Actions UI
- [ ] At least one `incident` issue has resolved so `MTTRHours` is non-null
- [ ] At least one `prod-defect` issue exists so `EscapedDefects > 0`
- [ ] `TestCoveragePct` populates for the three biggest repos
- [ ] `Net Value` on `p06bizvalue` is within 2 % of a Finance-produced spreadsheet using the same `assumptions.csv` from the governance repo
- [ ] A full rebuild from a fresh Lakehouse completes in under one night (so disaster-recovery is realistic)
