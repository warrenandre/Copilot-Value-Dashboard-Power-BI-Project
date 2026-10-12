# Simple View and Executive Value Scorecard Guide

## Dashboard context

The dashboard evaluates a GitHub Copilot rollout across adoption, usage, productivity, quality, business value, and governance. The current project uses synthetic sample data for eight teams. Daily activity covers 1 March through 27 September 2026; monthly quality data covers March through September 2026.

All values respond to the current report filters unless noted otherwise. Currency is displayed in South African rand (`R`).

### Calculation conventions

- Additive activity such as suggestions, sessions, pull requests, deployments, and credits is summed over the selected period.
- `Active Users` is calculated as the maximum daily active-user value for each selected team, summed across teams. It is a peak-based proxy, not a true person-level distinct count.
- `Sustained Users`, `Assigned Seats`, and other developer counts come from `DimDeveloper`. The report's date slicer does not filter this table, so these are not historical as-of counts.
- Ratios use DAX `DIVIDE`, which returns blank when the denominator is zero.
- Financial value and capacity metrics are modeled estimates based on the `Assumptions` table, not observed cash benefits.

### Current financial assumptions

| Assumption | Value |
|---|---:|
| Loaded hourly cost | R850 |
| Hours per FTE month | 160 |
| Capacity conversion percentage | 60% |
| Defect remediation cost | R12,500 |
| Licence cost per seat per month | R350 |
| Enablement cost per month | R45,000 |
| AI credit cost per unit | R0.15 |
| Minutes saved per accepted suggestion | 0.8 minutes |

## Page 0: Simple View - 6 Questions

### Page purpose

The Simple View is the executive landing page. It presents six management questions with three KPIs per question. It is designed to identify where further investigation is needed, rather than to prove that Copilot caused an outcome.

### Page filters

| Filter | Field | Effect |
|---|---|---|
| Business unit | `DimBusinessUnit[BusinessUnit]` | Restricts teams and all related fact data. |
| Month | `DimDate[YearMonth]` | Restricts daily and monthly fact data. It does not time-slice `DimDeveloper`. |

### Question 1: Are people using it?

| Metric | Source data points | Calculation | Information provided |
|---|---|---|---|
| Adoption Rate | `FactTeamDaily[ActiveUsers]`, developer rows in `DimDeveloper` | `[Active Users] / [Assigned Seats]` | Percentage of assigned seats represented by active users. Higher is generally better, but it should be read with sustained usage. |
| Active Users | `FactTeamDaily[ActiveUsers]`, grouped by team | For each selected team, calculate `MAX(ActiveUsers)` and then sum the team maxima. | Approximate active population in the selected period. This avoids summing the same users every day but remains a peak-based proxy. |
| Sustained Usage % | `DimDeveloper[IsSustained]`, `FactTeamDaily[ActiveUsers]` | `[Sustained Users] / [Active Users]`, where sustained users have `IsSustained = 1` and the sample definition represents at least three active weeks. | Indicates whether usage has become habitual rather than remaining trial activity. |

#### How to read this question

- High adoption and high sustained usage indicate broad, durable use.
- High adoption and low sustained usage indicate initial uptake without habit formation.
- Low adoption with many assigned seats may indicate onboarding, enablement, access, or licence-allocation issues.

### Question 2: Are they getting value from it?

| Metric | Source data points | Calculation | Information provided |
|---|---|---|---|
| Code Acceptance Rate | `FactTeamDaily[SuggestionsAccepted]`, `FactTeamDaily[SuggestionsMade]` | `SUM(SuggestionsAccepted) / SUM(SuggestionsMade)` | Share of code suggestions accepted. It is a relevance and usability signal, not proof that accepted code is correct or valuable. |
| Chat Sessions | `FactTeamDaily[ChatSessions]` | `SUM(ChatSessions)` | Total conversational Copilot usage in the selected period. Normalise by active users when comparing differently sized teams. |
| Agent Sessions | `FactTeamDaily[AgentSessions]` | `SUM(AgentSessions)` | Total agent-mode activity. It shows adoption of agentic workflows but does not measure successful completion. |

#### How to read this question

- Acceptance rate and volume should be considered together. A high rate on very low volume may not be material.
- Chat and agent sessions indicate workflow expansion beyond code completion.
- Usage volume should be linked to productivity and quality outcomes before claiming value.

### Question 3: Are engineers more productive?

| Metric | Source data points | Calculation | Information provided |
|---|---|---|---|
| Median PR Cycle Time (hrs) | `FactTeamDaily[PRCycleTimeHours]`, `FactTeamDaily[PRsMerged]` | Median `PRCycleTimeHours` across team-day rows where `PRsMerged > 0`. Live source duration should be PR merged time minus PR created time. | Typical pull-request elapsed time. Lower is generally better. The model takes a median of daily aggregate values, not individual PR records. |
| PRs Merged | `FactTeamDaily[PRsMerged]` | `SUM(PRsMerged)` | Completed pull-request throughput. Counts depend on PR size and working practices, so higher is not automatically better. |
| Estimated Hours Saved | `FactTeamDaily[SuggestionsAccepted]`, `Assumptions[MinutesSavedPerAcceptedSuggestion]` | `SUM(SuggestionsAccepted) * 0.8 / 60` | Modeled time benefit from accepted suggestions. It is an estimate, not measured elapsed time. |

#### How to read this question

- A desirable pattern is stable or increasing throughput with declining cycle time and no quality deterioration.
- Estimated hours saved should be validated through time studies, surveys, or comparable delivery cohorts.
- These metrics are team-level outcomes and must not be used to rank individual developers.

### Question 4: Is quality improving?

| Metric | Source data points | Calculation | Information provided |
|---|---|---|---|
| Change Failure Rate | `FactMonthlyQuality[ChangeFailures]`, `FactMonthlyQuality[TotalChanges]` | `SUM(ChangeFailures) / SUM(TotalChanges)` | Percentage of production changes that cause failure, rollback, hotfix, or another configured failure event. Lower is better. |
| Test Coverage % | `FactMonthlyQuality[TestCoveragePct]` | `AVERAGE(TestCoveragePct)` | Average monthly team test coverage. The measure is not weighted by codebase size or tests run. |
| MTTR (hrs) | `FactMonthlyQuality[MTTRHours]` | `AVERAGE(MTTRHours)` | Mean time to restore service after an incident. Lower is generally better; incident scope and severity must be comparable. |

#### How to read this question

- Faster delivery is only desirable when change failure and recovery performance remain controlled.
- Coverage is a control indicator, not direct evidence that tests are effective.
- Confirm that teams use the same failure and incident definitions before comparing them.

### Question 5: What business value are we creating?

| Metric | Source data points | Calculation | Information provided |
|---|---|---|---|
| Net Value | Suggestions accepted, escaped defects, seats, AI credits, selected months, and financial assumptions | `[Gross Capacity Value] + [Avoided Defect Cost] - [Copilot Investment]` | Estimated value remaining after modeled programme costs. It is sensitive to assumptions and does not equal realised cash. |
| Capacity Released (FTEs) | Estimated hours saved, capacity conversion percentage, hours per FTE month, selected month count | `([Estimated Hours Saved] * 60%) / (160 * DISTINCTCOUNT(YearMonth))` | Average monthly FTE-equivalent usable capacity. It represents potential redeployment of time, not head-count reduction. |
| ROI % | Net value and Copilot investment | `[Net Value] / [Copilot Investment]` | Estimated net return relative to cost. For example, 25% means modeled net value equals 25% of modeled investment. |

#### Component calculations

| Component | Calculation |
|---|---|
| Licence Cost | `Assigned Seats * selected month count * R350` |
| AI Credit Cost | `AI Credits Consumed * R0.15` |
| Enablement Cost | `Selected month count * R45,000` |
| Copilot Investment | `Licence Cost + AI Credit Cost + Enablement Cost` |
| Gross Capacity Value | `Estimated Hours Saved * 60% * R850` |
| Avoided Defect Cost | `MAX(0, 8 * selected team count * quality month count - Escaped Defects) * R12,500` |

#### How to read this question

- Treat all values as an expected scenario until Finance approves the assumptions.
- Capacity becomes business value only when released time is deliberately redirected to valuable work.
- The avoided-defect calculation assumes a baseline of eight defects per team per month and requires independent validation.

### Question 6: Are we governing it responsibly?

| Metric | Source data points | Calculation | Information provided |
|---|---|---|---|
| Inactive Seats | Assigned developer rows and Active Users | `[Assigned Seats] - [Active Users]` | Assigned seats not represented in the active-user proxy. Use it to investigate enablement, reassignment, or licence removal. |
| Vulnerabilities Introduced | `FactMonthlyQuality[VulnerabilitiesIntroduced]` | `SUM(VulnerabilitiesIntroduced)` | New security findings introduced in the selected period. It does not describe severity, remediation status, or total open risk. |
| Copilot Investment | Seats, selected months, AI credits, and cost assumptions | `[Licence Cost] + [AI Credit Cost] + [Enablement Cost]` | Total modeled cost of the programme in the selected context. |

#### How to read this question

- Inactive seats indicate an optimisation opportunity, not necessarily waste; recent assignments and leave should be considered.
- Security findings should be segmented by severity and status in a production model.
- Governance requires transparent costs, approved assumptions, access controls, and responsible team-level use of metrics.

## Page 1: Executive Value Scorecard

### Page purpose

The Executive Value Scorecard connects rollout reach to sustained behaviour, delivery flow, quality, capacity, and financial outcome. Use the cards for current status, trends for direction, the funnel for conversion, and the team table for variation.

### Page filters

| Filter | Field | Effect |
|---|---|---|
| Business unit | `DimBusinessUnit[BusinessUnit]` | Restricts the selected organisational area. |
| Team | `DimBusinessUnit[Team]` | Restricts the report to one or more teams. |
| Month | `DimDate[YearMonth]` | Restricts daily and monthly facts, but not historical developer-seat status. |

### Headline KPI cards

| Metric | Source data points | Calculation | Information provided |
|---|---|---|---|
| Adoption Rate | Active users and assigned seats | `[Active Users] / [Assigned Seats]` | Rollout reach among licensed developers. |
| Sustained Usage % | Sustained users and active users | `[Sustained Users] / [Active Users]` | Durability of use among the active population. |
| Median PR Cycle Time (hrs) | Daily cycle time on rows with merged PRs | `MEDIANX(FILTER(FactTeamDaily, PRsMerged > 0), PRCycleTimeHours)` | Typical delivery-flow speed. |
| Change Failure Rate | Monthly change failures and total changes | `SUM(ChangeFailures) / SUM(TotalChanges)` | Production delivery stability. |
| Estimated Hours Saved | Accepted suggestions and minutes-saved assumption | `SUM(SuggestionsAccepted) * 0.8 / 60` | Modeled capacity input from code-suggestion acceptance. |
| Net Value | Gross capacity value, avoided defect cost, investment | `Gross Capacity Value + Avoided Defect Cost - Copilot Investment` | Estimated financial result after programme costs. |

### Adoption trend

| Element | Field or calculation |
|---|---|
| X-axis | `DimDate[WeekStart]` |
| Active Users line | Sum of team-level maximum daily active users within each week context |
| Sustained Users line | Count of developer rows where `IsSustained = 1` |

**Information provided:** whether active reach grows over time and whether durable use follows. Because `DimDeveloper` is not related to `DimDate`, the Sustained Users line may remain constant across weeks. It should not be interpreted as a historical weekly sustained-user trend without a dated user-activity fact table.

### Delivery trend

| Element | Field or calculation |
|---|---|
| X-axis | `DimDate[YearMonth]` |
| Deployment columns | `SUM(FactTeamDaily[Deployments])` |
| PR cycle-time line | Median daily `PRCycleTimeHours` where `PRsMerged > 0` |

**Information provided:** whether deployment volume changes alongside delivery speed. A positive pattern is rising or stable deployments with falling cycle time, provided quality remains stable.

### Quality trend

| Element | Field or calculation |
|---|---|
| X-axis | `DimDate[YearMonth]` |
| Change Failure Rate line | `SUM(ChangeFailures) / SUM(TotalChanges)` |
| Test Coverage line | `AVERAGE(TestCoveragePct)` |

**Information provided:** whether release stability and automated-test coverage improve together. The two lines use different units, so compare each line's direction rather than its absolute height against the other.

### Adoption value-chain funnel

The funnel uses `ValueChain[StepName]` and the `Value Chain Count` measure. The measure switches calculation according to the current funnel step.

| Funnel step | Calculation | Meaning |
|---|---|---|
| Eligible Developers | `SUM(DimBusinessUnit[EligibleDevelopers])` | Total addressable developer population. |
| Assigned Seats | `COUNTROWS(DimDeveloper)` | Developers allocated a licence. |
| Active Users | Sum of team peak daily active users | Developers represented by period activity. |
| Engaged Users | Sum of each team's maximum daily `FactTeamDaily[EngagedUsers]` | Users performing an action classified as engaged. |
| Sustained Users | Count developers where `IsSustained = 1` | Developers with recurring use, represented by at least three active weeks in the sample model. |

**Information provided:** the largest conversion loss in the rollout. Common interpretations are:

- Eligible to assigned: licence coverage gap.
- Assigned to active: activation or enablement gap.
- Active to engaged: shallow-use gap.
- Engaged to sustained: retention or workflow-integration gap.

The stages are calculated from different grains and time behaviours, so a production implementation should validate that every stage uses compatible populations and periods.

### Net-value waterfall

| Element | Field or calculation |
|---|---|
| Category | `DimDate[YearMonth]` |
| Value | `[Net Value]` |
| Net Value | `Gross Capacity Value + Avoided Defect Cost - Copilot Investment` |

**Information provided:** each month's positive or negative contribution to modeled value. Monthly changes may be caused by accepted-suggestion volume, defect counts, AI-credit consumption, seat count, or recurring licence and enablement costs.

### Business-unit performance table

| Column | Calculation | Information provided |
|---|---|---|
| Business Unit | `DimBusinessUnit[BusinessUnit]` | Organisational grouping. |
| Team | `DimBusinessUnit[Team]` | Team-level comparison unit. |
| Adoption Rate | `Active Users / Assigned Seats` | Reach of active use. |
| Sustained Usage % | `Sustained Users / Active Users` | Durability of adoption. |
| Median PR Cycle Time (hrs) | Median daily cycle time on rows with merged PRs | Delivery speed. |
| Change Failure Rate | `Change Failures / Total Changes` | Delivery stability. |
| Net Value | `Gross Capacity Value + Avoided Defect Cost - Investment` | Modeled financial outcome. |

**Information provided:** where outcomes differ across business units and teams. The table is a starting point for investigation, not an employee ranking. Team differences may reflect product complexity, delivery practices, data completeness, rollout timing, and baseline performance.

## Recommended executive reading sequence

1. Start with Adoption Rate and Sustained Usage % to confirm that a meaningful population is using Copilot.
2. Check Estimated Hours Saved, PR Cycle Time, and the delivery trend for possible flow improvement.
3. Check Change Failure Rate and the quality trend before describing productivity gains as successful.
4. Use the funnel and team table to locate the organisational source of gaps.
5. Review Net Value and the waterfall only after confirming data quality and approving financial assumptions.
6. Record training, licence changes, policy changes, and rollout events so movement has business context.

## Measurement guardrails

- Copilot telemetry measures usage, not productivity by itself.
- Activity and lines of code are not business-value measures.
- Results should be reported at team and portfolio level, not used to rank individuals.
- Baseline and current cohorts must be comparable.
- Productivity must always be evaluated with quality.
- Estimated value and validated realised value should be reported separately.
- Financial assumptions need an owner, effective date, and confidence level.
- Correlation between Copilot use and an outcome does not establish causation.

## Technical sources

- Page definitions: `defaultProject.Report/definition/pages/p00simple/` and `defaultProject.Report/definition/pages/p01execscore/`
- Authoritative DAX: `defaultProject.SemanticModel/definition/tables/_Measures.tmdl`
- Model relationships: `defaultProject.SemanticModel/definition/relationships.tmdl`
- Assumption values: `defaultProject.SemanticModel/definition/tables/Assumptions.tmdl`
