# Data Ingestion Guide — Hybrid (GitHub + Azure DevOps)

Companion to [../README.md](../README.md). This guide shows **step-by-step how to replace the inline synthetic Power Query partitions with live data** from the GitHub platform and Azure DevOps, and how to capture that data in Power BI / Microsoft Fabric.

> **Scope**: this guide covers the "hybrid" edition where PRs, builds, deployments and work-items live in Azure DevOps and only Copilot + GHAS come from GitHub. For a GitHub-only edition see [data-ingestion-guide.github.md](data-ingestion-guide.github.md).

---

## 0. Target architecture

```
┌───────────────────────────────┐    ┌──────────────────────────┐
│ GitHub (REST / GraphQL)       │    │ Azure DevOps (REST)      │
│  • Copilot Metrics            │    │  • Pulls / Reviews       │
│  • Copilot Billing (seats)    │    │  • Pipelines / Runs      │
│  • GHAS alerts                │    │  • Test Results          │
└──────────────┬────────────────┘    │  • Work Items (WIQL)     │
               │                     └──────────────┬───────────┘
               │                                    │
               ▼                                    ▼
      ┌─────────────────────────────────────────────────────┐
      │   Fabric Dataflow Gen2  (one query per source)       │
      │   → lands rows into the Lakehouse delta tables       │
      └──────────────────────────┬───────────────────────────┘
                                 │
                                 ▼
      ┌─────────────────────────────────────────────────────┐
      │   Fabric Lakehouse  (historic snapshots)             │
      │   bronze_github_*, bronze_ado_*, silver_fact_*       │
      └──────────────────────────┬───────────────────────────┘
                                 │
                                 ▼
      ┌─────────────────────────────────────────────────────┐
      │   Semantic model (defaultProject.SemanticModel)      │
      │   DimDate, DimBusinessUnit, DimDeveloper, DimFeature │
      │   FactTeamDaily, FactFeatureDaily, FactMonthlyQuality│
      └─────────────────────────────────────────────────────┘
```

Why land raw rows in a Lakehouse first? The GitHub Copilot Metrics API only serves the **last ~28 days**. If you query it directly from the semantic model, you lose history on every refresh. The dataflow appends daily snapshots into bronze delta tables; the semantic model reads the full history from the Lakehouse.

---

## 1. Prerequisites

### 1.1 GitHub App

Create an organisation-installed GitHub App (or enterprise-installed if you have an enterprise). Required permissions:

| Resource | Access |
|---|---|
| Organization › GitHub Copilot Business | Read |
| Organization › Members | Read |
| Repository › Code scanning alerts | Read |
| Repository › Dependabot alerts | Read |
| Repository › Secret scanning alerts | Read |
| Repository › Metadata | Read |

Generate and store **client ID + private key (`.pem`)** in Azure Key Vault:

- Secret `github-app-client-id`
- Secret `github-app-private-key` (full PEM, newlines preserved)
- Secret `github-app-installation-id` (from `GET /orgs/{org}/installation`)

The dataflow will exchange these for a short-lived installation access token on every refresh.

### 1.2 Azure DevOps PAT (or Entra service principal)

Create a service account PAT scoped to:

- `Code (read)` — PR history
- `Build (read)` — pipeline runs
- `Release (read)` — classic releases if used
- `Test Management (read)` — test results
- `Work Items (read)` — defects / incidents / tech-debt

Store as `ado-pat` in Key Vault. Prefer an Entra-ID managed identity federated to ADO where available.

### 1.3 Fabric workspace

1. Create a Fabric workspace, e.g. `copilot-value-prod`.
2. Add a **Lakehouse** `copilot_value_lh`.
3. Add a **Dataflow Gen2** `copilot_value_ingest`.
4. Attach a **Key Vault linked connection** (`Settings → Manage connections → + New → Azure Key Vault`) so Power Query can read secrets at refresh time via `AzureKeyVault.Contents`.

### 1.4 Semantic model parameters

Add these parameters to `defaultProject.SemanticModel` (edit via Tabular Editor or add to each `.tmdl`):

| Parameter | Example value | Purpose |
|---|---|---|
| `GitHubOrg` | `"contoso-eng"` | Target GitHub organisation |
| `AdoOrg` | `"contoso"` | Azure DevOps organisation |
| `AdoProject` | `"Platform"` | Azure DevOps project (comma-separated for multi-project) |
| `LakehousePath` | `"abfss://..."` | Fabric Lakehouse ABFSS URL |
| `UseSampleData` | `false` | When `true`, keeps the inline synthetic partitions (demo mode) |

---

## 2. Shared Power Query helpers

Add these functions to the dataflow as **blank queries** (right-click → New query → Blank query → Advanced editor). They are reused by every ingestion query.

### 2.1 `fnGitHubToken` — exchange App credentials for an installation token

```powerquery
(appId as text, privateKeyPem as text, installationId as text) as text =>
let
    // JWT header + payload (10 min expiry)
    now = Number.From(DateTime.ToText(DateTime.FixedUtcNow(), "yyyy-MM-ddTHH:mm:ssZ")),
    iat = Duration.TotalSeconds(DateTime.FixedUtcNow() - #datetime(1970,1,1,0,0,0)),
    header = Json.FromValue([alg="RS256", typ="JWT"]),
    payload = Json.FromValue([iat=iat, exp=iat+540, iss=appId]),
    b64 = (b as binary) => Text.Replace(Text.Replace(Text.Replace(Binary.ToText(b, BinaryEncoding.Base64), "=", ""), "+", "-"), "/", "_"),
    unsigned = b64(header) & "." & b64(payload),
    // Fabric Dataflow Gen2 ships RSA signing via Web.Contents to a tiny Azure Function.
    // Deploy functions/sign-jwt.ps1 (template included in /scripts) and expose it at the URL below.
    signUrl = "https://copilot-value-fn.azurewebsites.net/api/sign-jwt",
    signResp = Json.Document(Web.Contents(signUrl, [
        Headers = [#"Content-Type"="application/json"],
        Content = Json.FromValue([unsigned=unsigned, keyPem=privateKeyPem])
    ])),
    jwt = unsigned & "." & signResp[signature],
    // Exchange JWT for installation token
    tokResp = Json.Document(Web.Contents("https://api.github.com", [
        RelativePath = "/app/installations/" & installationId & "/access_tokens",
        Headers = [
            Authorization = "Bearer " & jwt,
            Accept = "application/vnd.github+json",
            #"X-GitHub-Api-Version" = "2022-11-28"
        ],
        Content = Text.ToBinary("{}")
    ]))
in
    tokResp[token]
```

> **Note on JWT signing** — Power Query cannot sign RS256 natively. The small helper Azure Function template at `scripts/sign-jwt/` performs the signing with the private key passed in the body. Alternatively, generate installation tokens with a GitHub Actions workflow and push them to Key Vault every 50 minutes.

### 2.2 `fnPagedGet` — follow GitHub `Link: rel="next"` pagination

```powerquery
(baseUrl as text, path as text, token as text, optional query as record) as list =>
let
    initial = Web.Contents(baseUrl, [
        RelativePath = path,
        Query = query ?? [],
        Headers = [
            Authorization = "Bearer " & token,
            Accept = "application/vnd.github+json",
            #"X-GitHub-Api-Version" = "2022-11-28"
        ],
        ManualStatusHandling = {404}
    ]),
    getPage = (resp) =>
        let
            body = try Json.Document(resp) otherwise null,
            linkHeader = try Value.Metadata(resp)[Headers][#"Link"] otherwise null,
            nextMatch = if linkHeader = null then null else Text.BetweenDelimiters(linkHeader, "<", ">; rel=""next"""),
            nextUrl = if (nextMatch ?? "") = "" then null else nextMatch
        in
            [body = body, next = nextUrl],
    pages = List.Generate(
        () => [resp = initial, state = getPage(initial)],
        each [state][body] <> null,
        each [
            resp = if [state][next] = null then null else Web.Contents([state][next], [
                Headers = [
                    Authorization = "Bearer " & token,
                    Accept = "application/vnd.github+json",
                    #"X-GitHub-Api-Version" = "2022-11-28"
                ]
            ]),
            state = if [state][next] = null then [body=null, next=null] else getPage(resp)
        ],
        each [state][body]
    )
in
    pages
```

### 2.3 `fnAdoGet` — Azure DevOps REST with PAT auth + continuation tokens

```powerquery
(org as text, path as text, pat as text, optional query as record) as list =>
let
    baseUrl = "https://dev.azure.com/" & org,
    auth = "Basic " & Binary.ToText(Text.ToBinary(":" & pat), BinaryEncoding.Base64),
    getPage = (continuation) =>
        let
            q = Record.Combine({query ?? [], if continuation = null then [] else [continuationToken = continuation], [#"api-version"="7.1"]}),
            resp = Web.Contents(baseUrl, [
                RelativePath = path,
                Query = q,
                Headers = [Authorization = auth, Accept="application/json"]
            ]),
            body = Json.Document(resp),
            next = try Value.Metadata(resp)[Headers][#"x-ms-continuationtoken"] otherwise null
        in
            [body = body, next = next],
    pages = List.Generate(
        () => [state = getPage(null)],
        each [state][body] <> null,
        each [state = if [state][next] = null then [body=null, next=null] else getPage([state][next])],
        each [state][body]
    )
in
    pages
```

### 2.4 `fnSecrets` — pull credentials from Key Vault at refresh time

```powerquery
() as record =>
let
    kv = "https://kv-copilot-value.vault.azure.net/",
    get = (name) => AzureKeyVault.Contents(kv){[Name=name]}[Content]
in
    [
        GitHubAppId         = Text.FromBinary(get("github-app-client-id")),
        GitHubPrivateKey    = Text.FromBinary(get("github-app-private-key")),
        GitHubInstallationId= Text.FromBinary(get("github-app-installation-id")),
        AdoPat              = Text.FromBinary(get("ado-pat"))
    ]
```

---

## 3. GitHub ingestion

Each subsection below produces one bronze table in the Lakehouse. The semantic model's silver fact tables are then produced by SQL views or further Power Query transformations.

### 3.1 Copilot Metrics — team daily → `bronze_github_copilot_team`

Drives `FactTeamDaily` columns: `ActiveUsers`, `EngagedUsers`, `WeeklyActiveUsers`, `SuggestionsMade`, `SuggestionsAccepted`, `LinesAccepted`, `ChatSessions`, `AgentSessions`.

**Endpoint**: `GET /orgs/{org}/team/{team_slug}/copilot/metrics`
**Retention**: 28 days — **must land to Lakehouse on every refresh**.

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    // Pull all teams from DimBusinessUnit reference (team_slug column must exist)
    teams = DimBusinessUnit[GitHubTeamSlug],
    perTeam = List.Transform(teams, (slug) =>
        let
            pages = fnPagedGet("https://api.github.com", "/orgs/" & #"GitHubOrg" & "/team/" & slug & "/copilot/metrics", token),
            flat  = List.Combine(pages),
            rows  = List.Transform(flat, (d) => [
                Date = Date.FromText(d[date]),
                TeamSlug = slug,
                ActiveUsers = d[total_active_users],
                EngagedUsers = d[total_engaged_users],
                WeeklyActiveUsers = null,  // computed in SQL rollup
                SuggestionsMade = List.Sum(List.Transform(d[copilot_ide_code_completions][editors] ?? {}, each List.Sum(List.Transform(_[models], each List.Sum(List.Transform(_[languages], each _[total_code_suggestions] ?? 0)))))),
                SuggestionsAccepted = List.Sum(List.Transform(d[copilot_ide_code_completions][editors] ?? {}, each List.Sum(List.Transform(_[models], each List.Sum(List.Transform(_[languages], each _[total_code_acceptances] ?? 0)))))),
                LinesAccepted = List.Sum(List.Transform(d[copilot_ide_code_completions][editors] ?? {}, each List.Sum(List.Transform(_[models], each List.Sum(List.Transform(_[languages], each _[total_code_lines_accepted] ?? 0)))))),
                ChatSessions = List.Sum(List.Transform(d[copilot_ide_chat][editors] ?? {}, each List.Sum(List.Transform(_[models], each _[total_chats] ?? 0)))),
                AgentSessions = d[copilot_dotcom_chat][total_engaged_users] ?? 0,
                IngestedAt = DateTime.FixedUtcNow()
            ])
        in rows),
    combined = Table.FromRecords(List.Combine(perTeam))
in
    combined
```

**Destination**: Dataflow destination → Lakehouse table `bronze_github_copilot_team`, update method **Append**.

### 3.2 Copilot Metrics — feature daily → `bronze_github_copilot_feature`

Drives `FactFeatureDaily`. Same endpoint — the response contains a per-feature breakdown.

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    teams = DimBusinessUnit[GitHubTeamSlug],
    featureKeyMap = #table({"FeatureName","FeatureKey"}, {{"Completion",1},{"Chat",2},{"Code Review",3},{"Agent Mode",4},{"Coding Agent",5},{"CLI",6},{"Copilot App",7}}),
    perTeam = List.Transform(teams, (slug) =>
        let
            pages = fnPagedGet("https://api.github.com", "/orgs/" & #"GitHubOrg" & "/team/" & slug & "/copilot/metrics", token),
            flat = List.Combine(pages),
            rows = List.Combine(List.Transform(flat, (d) =>
                let date = Date.FromText(d[date]) in {
                    [Date=date, TeamSlug=slug, FeatureName="Completion",   Interactions = d[copilot_ide_code_completions][total_engaged_users] ?? 0, AcceptedInteractions = null, ActiveUsers = d[copilot_ide_code_completions][total_engaged_users] ?? 0],
                    [Date=date, TeamSlug=slug, FeatureName="Chat",         Interactions = d[copilot_ide_chat][total_engaged_users] ?? 0, AcceptedInteractions = null, ActiveUsers = d[copilot_ide_chat][total_engaged_users] ?? 0],
                    [Date=date, TeamSlug=slug, FeatureName="Agent Mode",   Interactions = d[copilot_dotcom_chat][total_engaged_users] ?? 0, AcceptedInteractions = null, ActiveUsers = d[copilot_dotcom_chat][total_engaged_users] ?? 0]
                    // add Code Review, Coding Agent, CLI, Copilot App when their counters appear in the API
                }))
        in rows),
    tbl = Table.FromRecords(List.Combine(perTeam)),
    joined = Table.Join(tbl, "FeatureName", featureKeyMap, "FeatureName")
in
    joined
```

### 3.3 Copilot Seats → `bronze_github_seats` → drives `DimDeveloper`

**Endpoint**: `GET /orgs/{org}/copilot/billing/seats` (paginated).

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    pages = fnPagedGet("https://api.github.com", "/orgs/" & #"GitHubOrg" & "/copilot/billing/seats", token, [per_page="100"]),
    seats = List.Combine(List.Transform(pages, each _[seats])),
    rows = List.Transform(seats, (st) => [
        DeveloperLogin   = st[assignee][login],
        DeveloperKey     = st[assignee][id],
        DeveloperName    = st[assignee][name] ?? st[assignee][login],
        AssignedDate     = Date.FromText(Text.Start(st[created_at], 10)),
        LastActiveDate   = if st[last_activity_at] = null then null else Date.FromText(Text.Start(st[last_activity_at], 10)),
        PendingCancellation = st[pending_cancellation_date] <> null,
        IngestedAt       = DateTime.FixedUtcNow()
    ])
in
    Table.FromRecords(rows)
```

To get `FirstUseDate`, `TotalActiveWeeks`, `IsActivated`, `IsSustained` you need the **user-level** metrics endpoint `GET /orgs/{org}/members/{username}/copilot/metrics` (28-day window) landed daily into `bronze_github_copilot_user`. A silver view then computes:

```sql
CREATE OR REPLACE VIEW silver_dim_developer AS
SELECT
  s.DeveloperKey,
  s.DeveloperLogin,
  s.DeveloperName,
  m.TeamKey,
  s.AssignedDate,
  MIN(u.MetricDate)                           AS FirstUseDate,
  MAX(u.MetricDate)                           AS LastActiveDate,
  DATEDIFF(day, s.AssignedDate, MIN(u.MetricDate)) AS DaysToFirstUse,
  FORMAT(s.AssignedDate, 'yyyy-MM')           AS CohortMonth,
  CASE WHEN MIN(u.MetricDate) IS NOT NULL THEN 1 ELSE 0 END AS IsActivated,
  COUNT(DISTINCT DATE_TRUNC('week', u.MetricDate)) AS TotalActiveWeeks,
  CASE WHEN COUNT(DISTINCT DATE_TRUNC('week', u.MetricDate)) >= 3 THEN 1 ELSE 0 END AS IsSustained
FROM bronze_github_seats s
LEFT JOIN bronze_github_copilot_user u ON u.DeveloperLogin = s.DeveloperLogin AND u.Active = 1
LEFT JOIN ref_github_team_map m        ON m.DeveloperLogin = s.DeveloperLogin
GROUP BY s.DeveloperKey, s.DeveloperLogin, s.DeveloperName, m.TeamKey, s.AssignedDate;
```

### 3.4 Copilot billing (AI credits) → `AICreditsConsumed`

**Endpoint**: `GET /enterprises/{ent}/copilot/usage` (enterprise) or `/orgs/{org}/copilot/usage`.

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    pages = fnPagedGet("https://api.github.com", "/orgs/" & #"GitHubOrg" & "/copilot/usage", token),
    flat = List.Combine(pages),
    rows = List.Transform(flat, (d) => [
        Date = Date.FromText(d[day]),
        AICreditsConsumed = d[total_premium_requests] ?? 0
    ])
in
    Table.FromRecords(rows)
```

Merged into `FactTeamDaily` at the organisation level, then allocated per team using each team's share of `ChatSessions + AgentSessions + CodingAgentPRsCreated` for the same day.

### 3.5 GHAS code-scanning alerts → `VulnerabilitiesIntroduced`

**Endpoint**: `GET /orgs/{org}/code-scanning/alerts?state=open`.

```powerquery
let
    s = fnSecrets(),
    token = fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId]),
    pages = fnPagedGet("https://api.github.com", "/orgs/" & #"GitHubOrg" & "/code-scanning/alerts",
        token, [state="open", per_page="100"]),
    alerts = List.Combine(pages),
    rows = List.Transform(alerts, (a) => [
        AlertNumber   = a[number],
        RepoFullName  = a[repository][full_name],
        Severity      = a[rule][severity],
        CreatedAt     = DateTimeZone.FromText(a[created_at]),
        CreatedDate   = Date.From(DateTimeZone.FromText(a[created_at])),
        YearMonth     = Date.ToText(Date.From(DateTimeZone.FromText(a[created_at])), "yyyy-MM")
    ])
in
    Table.FromRecords(rows)
```

Silver rollup joins to a `ref_repo_to_team` map and groups by (`YearMonth`, `TeamKey`) → `VulnerabilitiesIntroduced` on `FactMonthlyQuality`.

---

## 4. Azure DevOps ingestion

### 4.1 Pull requests → `bronze_ado_pulls`

Drives `PRsMerged`, `PRCycleTimeHours`, `TimeToFirstReviewHours`, `LeadTimeHours`, `ReworkedPRs`.

**Endpoint**: `GET /{org}/{project}/_apis/git/pullrequests?searchCriteria.status=completed&searchCriteria.minTime=...`.
PRs are per repository — enumerate repos first.

```powerquery
let
    s = fnSecrets(),
    repos = fnAdoGet(#"AdoOrg", "/" & #"AdoProject" & "/_apis/git/repositories", s[AdoPat]){0}[value],
    perRepo = List.Transform(repos, (r) =>
        let
            prs = fnAdoGet(#"AdoOrg",
                "/" & #"AdoProject" & "/_apis/git/repositories/" & r[id] & "/pullrequests",
                s[AdoPat],
                [#"searchCriteria.status"="completed", #"searchCriteria.minTime"=Date.ToText(Date.AddDays(Date.From(DateTime.FixedUtcNow()), -400), "yyyy-MM-ddTHH:mm:ssZ")]),
            flat = List.Combine(List.Transform(prs, each _[value])),
            rows = List.Transform(flat, (pr) => [
                PRId            = pr[pullRequestId],
                RepoName        = r[name],
                CreatorEmail    = pr[createdBy][uniqueName],
                CreatedAt       = DateTimeZone.FromText(pr[creationDate]),
                ClosedAt        = DateTimeZone.FromText(pr[closedDate]),
                CycleTimeHours  = Duration.TotalHours(DateTimeZone.FromText(pr[closedDate]) - DateTimeZone.FromText(pr[creationDate])),
                SourceBranch    = pr[sourceRefName],
                TargetBranch    = pr[targetRefName],
                MergeStatus     = pr[mergeStatus]
            ])
        in rows),
    tbl = Table.FromRecords(List.Combine(perRepo))
in
    tbl
```

To get `TimeToFirstReviewHours`, follow up with `GET /_apis/git/repositories/{repoId}/pullRequests/{prId}/threads` for each PR and take `MIN(comments[0].publishedDate) − PR.CreatedAt`. For performance, do this inside a scheduled Fabric Notebook rather than inside the dataflow.

### 4.2 Pipeline runs → `bronze_ado_runs`

Drives `BuildRuns`, `BuildSuccesses`, `Deployments`, `FailedDeployments`.

```powerquery
let
    s = fnSecrets(),
    runs = fnAdoGet(#"AdoOrg", "/" & #"AdoProject" & "/_apis/pipelines", s[AdoPat]),
    pipelines = List.Combine(List.Transform(runs, each _[value])),
    perPipeline = List.Transform(pipelines, (p) =>
        let
            r = fnAdoGet(#"AdoOrg", "/" & #"AdoProject" & "/_apis/pipelines/" & Text.From(p[id]) & "/runs", s[AdoPat]),
            flat = List.Combine(List.Transform(r, each _[value])),
            rows = List.Transform(flat, (run) => [
                PipelineId   = p[id],
                PipelineName = p[name],
                RunId        = run[id],
                CreatedAt    = DateTimeZone.FromText(run[createdDate]),
                FinishedAt   = DateTimeZone.FromText(run[finishedDate]),
                State        = run[state],
                Result       = run[result],
                IsDeployment = Text.Contains(Text.Lower(p[name]), "deploy") or Text.Contains(Text.Lower(p[name]), "release"),
                Date         = Date.From(DateTimeZone.FromText(run[finishedDate]))
            ])
        in rows),
    tbl = Table.FromRecords(List.Combine(perPipeline))
in
    tbl
```

Silver rollup:

```sql
CREATE OR REPLACE VIEW silver_fact_team_daily_build AS
SELECT
  r.Date,
  m.TeamKey,
  COUNT_IF(NOT r.IsDeployment)                             AS BuildRuns,
  COUNT_IF(NOT r.IsDeployment AND r.Result = 'succeeded')  AS BuildSuccesses,
  COUNT_IF(r.IsDeployment AND r.Result = 'succeeded')      AS Deployments,
  COUNT_IF(r.IsDeployment AND r.Result = 'failed')         AS FailedDeployments
FROM bronze_ado_runs r
JOIN ref_pipeline_to_team m ON m.PipelineId = r.PipelineId
GROUP BY r.Date, m.TeamKey;
```

### 4.3 Test results → `TestsRun`, `TestsPassed`, `TestCoveragePct`

**Endpoints**:

- `GET /_apis/test/runs?minLastUpdatedDate=...&maxLastUpdatedDate=...` (per project)
- Coverage: `GET /_apis/test/codecoverage?buildId=...` for each build.

```powerquery
let
    s = fnSecrets(),
    runs = fnAdoGet(#"AdoOrg",
        "/" & #"AdoProject" & "/_apis/test/runs",
        s[AdoPat],
        [minLastUpdatedDate=Date.ToText(Date.AddDays(Date.From(DateTime.FixedUtcNow()), -40), "yyyy-MM-dd"),
         maxLastUpdatedDate=Date.ToText(Date.From(DateTime.FixedUtcNow()), "yyyy-MM-dd")]),
    flat = List.Combine(List.Transform(runs, each _[value])),
    rows = List.Transform(flat, (r) => [
        RunId    = r[id],
        PipelineRunId = r[build][id],
        TotalTests = r[totalTests],
        PassedTests = r[passedTests],
        StartedDate = DateTimeZone.FromText(r[startedDate]),
        Date = Date.From(DateTimeZone.FromText(r[startedDate]))
    ])
in
    Table.FromRecords(rows)
```

Group monthly in silver and join to `ref_pipeline_to_team`.

### 4.4 Work items — defects, incidents, tech debt

Use **WIQL** (Work Item Query Language) to find the right items, then expand their fields.

**Endpoint**: `POST /{org}/{project}/_apis/wit/wiql?api-version=7.1`.

```powerquery
let
    s = fnSecrets(),
    auth = "Basic " & Binary.ToText(Text.ToBinary(":" & s[AdoPat]), BinaryEncoding.Base64),
    wiql = "SELECT [System.Id] FROM WorkItems "
         & "WHERE [System.TeamProject] = '" & #"AdoProject" & "' "
         & "AND [System.WorkItemType] IN ('Bug','Incident') "
         & "AND [System.Tags] CONTAINS 'prod-defect' "
         & "AND [System.CreatedDate] >= @Today - 400",
    wiqlResp = Json.Document(Web.Contents("https://dev.azure.com/" & #"AdoOrg", [
        RelativePath = "/" & #"AdoProject" & "/_apis/wit/wiql",
        Query = [#"api-version"="7.1"],
        Headers = [Authorization=auth, #"Content-Type"="application/json"],
        Content = Json.FromValue([query=wiql])
    ])),
    ids = List.Transform(wiqlResp[workItems], each Text.From(_[id])),
    // Batch 200 ids at a time
    batches = List.Split(ids, 200),
    perBatch = List.Transform(batches, (b) =>
        Json.Document(Web.Contents("https://dev.azure.com/" & #"AdoOrg", [
            RelativePath = "/" & #"AdoProject" & "/_apis/wit/workitems",
            Query = [ids=Text.Combine(b, ","), #"$expand"="all", #"api-version"="7.1"],
            Headers = [Authorization=auth, Accept="application/json"]
        ]))[value]),
    flat = List.Combine(perBatch),
    rows = List.Transform(flat, (wi) => [
        Id = wi[id],
        Type = wi[fields][#"System.WorkItemType"],
        Title = wi[fields][#"System.Title"],
        State = wi[fields][#"System.State"],
        AreaPath = wi[fields][#"System.AreaPath"],
        Tags = wi[fields][#"System.Tags"] ?? "",
        CreatedAt = DateTimeZone.FromText(wi[fields][#"System.CreatedDate"]),
        ClosedAt = try DateTimeZone.FromText(wi[fields][#"Microsoft.VSTS.Common.ClosedDate"]) otherwise null,
        YearMonth = Date.ToText(Date.From(DateTimeZone.FromText(wi[fields][#"System.CreatedDate"])), "yyyy-MM")
    ])
in
    Table.FromRecords(rows)
```

Run three variants (change the `WHERE` clause):

| Variant | WIQL filter | Drives |
|---|---|---|
| Escaped defects | `Tags CONTAINS 'prod-defect'` | `EscapedDefects` |
| Incidents / MTTR | `WorkItemType = 'Incident'` | `MTTRHours` (AVG of `ClosedAt − CreatedAt`) |
| Tech debt | `Tags CONTAINS 'tech-debt' AND State <> 'Closed'` | `TechDebtItems` (snapshot at month end) |

Change failures are deployments followed by a hotfix or rollback deployment within 24 h — compute this in SQL by joining `bronze_ado_runs` (deployment runs) to incident work items whose `CreatedAt` falls within 24 h of a deployment.

---

## 5. Reference / manual data

### 5.1 `DimBusinessUnit`

Keep as a CSV in a central governance repo so the mapping is versioned.

| Column | Notes |
|---|---|
| `TeamKey` | Stable integer key you control |
| `BusinessUnit` / `Portfolio` / `Team` / `CostCentre` | HR / Finance owned |
| `EligibleDevelopers` | HR head-count |
| `GitHubTeamSlug` | Join key for Copilot per-team metrics |
| `AdoPipelineIds` | Comma-separated list used by `ref_pipeline_to_team` |

Load with:

```powerquery
let
    s = fnSecrets(),
    csv = Web.Contents("https://raw.githubusercontent.com/contoso-eng/governance/main/orgmap.csv", [
        Headers = [Authorization = "Bearer " & fnGitHubToken(s[GitHubAppId], s[GitHubPrivateKey], s[GitHubInstallationId])]
    ])
in
    Csv.Document(csv, [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv])
```

### 5.2 `Assumptions`

Same pattern — a single-row CSV in the governance repo, CODEOWNERS-restricted to Finance.

### 5.3 `DimFeature`, `ValueChain`

Keep as inline `#table` partitions — they rarely change and are owned by the Copilot programme team.

---

## 6. Loading into the semantic model

For every table that was synthetic, replace its inline `partition ... source = let ... in ...` block in the `.tmdl` with a Lakehouse-backed source. Example for `FactTeamDaily`:

```tmdl
partition FactTeamDaily = m
    mode: import
    source =
        let
            Source = Lakehouse.Contents([]){[workspaceId=#"WorkspaceId"]}[Data]
                      {[lakehouseId=#"LakehouseId"]}[Data]
                      {[Id="silver_fact_team_daily",ItemKind="Table"]}[Data]
        in
            Source
```

Parameters `WorkspaceId` and `LakehouseId` live alongside `GitHubOrg` / `AdoOrg` from §1.4.

**Mode choice**:

- **Import** — simplest. Refresh schedule drives freshness. Use for `DimDate`, `DimBusinessUnit`, `DimFeature`, `Assumptions`, `ValueChain`.
- **DirectLake** — zero-copy against the Lakehouse, near-real-time. Use for the three fact tables and `DimDeveloper`.

Keep the synthetic partitions behind a conditional:

```tmdl
partition FactTeamDaily_Live = m
    mode: directLake
    source = ...

partition FactTeamDaily_Sample = m
    mode: import
    source = ...  // existing synthetic
```

A model-level annotation `UseSampleData` toggles which partition is refreshed.

### 6.1 Relationship check

After switching sources, verify in **Model view**:

- `DimDate[Date]` → each fact's `Date` — single, 1:*
- `DimBusinessUnit[TeamKey]` → each fact's `TeamKey` — single, 1:*
- `DimFeature[FeatureKey]` → `FactFeatureDaily[FeatureKey]` — single, 1:*
- `DimDeveloper[TeamKey]` → `DimBusinessUnit[TeamKey]` — single, *:1

No measures need to change.

---

## 7. Incremental refresh

Configure incremental refresh **in the Lakehouse dataflow**, not the semantic model, so the semantic model can stay DirectLake.

| Table | Range | Store history | Refresh |
|---|---|---|---|
| `bronze_github_copilot_team` | 28 days | 2 years | Daily |
| `bronze_github_copilot_feature` | 28 days | 2 years | Daily |
| `bronze_github_seats` | Full | — | Daily (snapshot) |
| `bronze_github_copilot_user` | 28 days | 2 years | Daily |
| `bronze_github_copilot_usage` | 60 days | 2 years | Daily |
| `bronze_github_code_scanning` | Full | — | Daily (snapshot of open) |
| `bronze_ado_pulls` | 30 days | 400 days | Daily |
| `bronze_ado_runs` | 30 days | 400 days | Hourly (for cycle-time dashboards) |
| `bronze_ado_test_runs` | 30 days | 400 days | Daily |
| `bronze_ado_workitems_*` | 30 days | 400 days | Daily |

Each query uses `RangeStart` / `RangeEnd` parameters in its Web.Contents `Query` record.

---

## 8. Secrets, service principal, parameterisation

- All secrets live in **Azure Key Vault**. The dataflow reads them with `AzureKeyVault.Contents`. No PAT or private key is ever stored in Power Query.
- The dataflow runs under a **Fabric service principal** granted **Key Vault Secrets User** on the vault.
- The GitHub installation token is **minted at refresh time** (10-minute lifetime). Nothing persists.
- Rotate the ADO PAT every 90 days — automate with an Azure Function + Key Vault new version.

---

## 9. Scheduling and monitoring

| Job | Schedule | Owner |
|---|---|---|
| Dataflow `copilot_value_ingest` | 03:00 SAST daily | Data Platform |
| Semantic model refresh (if Import mode) | 04:00 SAST daily | Data Platform |
| Alert on >2 consecutive failures | Teams webhook | Platform Ops |

Fabric emits refresh events to Monitor Hub. Pipe failures to a Teams channel with the standard Fabric activity log notifier.

---

## 10. Row-level security

Executives see everything; engineering managers see only their business unit.

```dax
[Role: Manager]
Filter: DimBusinessUnit[Portfolio] = USERPRINCIPALNAME_LOOKUP()
```

Hold the mapping in `ref_user_to_portfolio` loaded from the governance repo.

---

## 11. Troubleshooting cheat-sheet

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 Unauthorized` on `/copilot/metrics` | App not re-authorised after permission change | Re-install the GitHub App on the org |
| `422` with `Metrics for this organization are not available` | Fewer than 5 Copilot users in a team | Fall back to the org-level metrics endpoint |
| Dataflow refresh takes > 2 h | Pulling all PRs instead of incremental window | Add `searchCriteria.minTime` / `RangeStart` parameters |
| `Column 'FeatureKey' not found` after schema change | Copilot API added a new feature (e.g. "Workspace") | Add it to the `featureKeyMap` lookup and `DimFeature` |
| DAX measure shows BLANK after cutover | Column rename in bronze table | Keep bronze column names identical to the synthetic schema — never rename, only add |
| `429 rate limit` from GitHub | More than 5 000 req/hr on the installation | Serialise team-slug queries and add `Function.InvokeAfter(..., #duration(0,0,0,0.2))` throttling |

---

## 12. Validation checklist

Before replacing the synthetic partitions in production:

- [ ] `bronze_github_copilot_team` row count ≈ `teams × days_in_window`
- [ ] `SELECT MAX(Date)` on every bronze table = yesterday
- [ ] `COUNT(DISTINCT DeveloperLogin)` on `bronze_github_seats` = licence spend / price-per-seat
- [ ] A sample team's `Suggestions Accepted` for last week matches the GitHub Copilot admin UI
- [ ] A sample pipeline's deployment count for last week matches Azure DevOps Pipelines UI
- [ ] The report's `Adoption Rate` card for the whole org matches `COPILOT_METRICS → total_active_users / seats`
- [ ] `Net Value` on `p06bizvalue` is within 2 % of a Finance-produced spreadsheet using the same assumptions
