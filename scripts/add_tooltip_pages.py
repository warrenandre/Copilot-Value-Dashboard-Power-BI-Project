"""Replace the previous Text-mode visualTooltip with proper Power BI report-page
tooltips so hovering any measure-driven visual shows the calculation.

For each unique measure used on the report, we generate:
  * a hidden tooltip page  `pt-<slug>` (400x200) with a textbox showing the
    measure name, DAX formula and one-line description;
  * a wiring on every visual that references the measure so its `visualTooltip`
    points to the matching tooltip page (`type = 'Canvas'`).

Multi-measure visuals point at their primary (first) measure's tooltip page.
Re-running the script is safe: existing `pt-*` pages are overwritten in place
and page order is deduplicated.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_ROOT = REPO_ROOT / "defaultProject.Report" / "definition"
PAGES_ROOT = REPORT_ROOT / "pages"
PAGES_JSON = PAGES_ROOT / "pages.json"

# Measure -> (compact DAX formula, one-line meaning). Kept in one place.
MEASURES: dict[str, tuple[str, str]] = {
    "Eligible Developers": (
        "SUM(DimBusinessUnit[EligibleDevelopers])",
        "Head-count of developers eligible for Copilot in the selected scope.",
    ),
    "Assigned Seats": (
        "COUNTROWS(DimDeveloper)",
        "Developers currently holding a Copilot seat.",
    ),
    "Activated Users": (
        "CALCULATE(COUNTROWS(DimDeveloper), DimDeveloper[IsActivated]=1)",
        "Seats that have logged at least one usage day.",
    ),
    "Active Users": (
        "SUMX(VALUES(TeamKey), CALCULATE(MAX(FactTeamDaily[ActiveUsers])))",
        "Peak distinct active developers per team in the period, summed across teams.",
    ),
    "Weekly Active Users": (
        "SUMX(VALUES(TeamKey), CALCULATE(MAX(FactTeamDaily[WeeklyActiveUsers])))",
        "Peak weekly-active developers per team in the period.",
    ),
    "Sustained Users": (
        "CALCULATE(COUNTROWS(DimDeveloper), DimDeveloper[IsSustained]=1)",
        "Developers active in at least 3 weeks of the period.",
    ),
    "Engaged Users": (
        "SUMX(VALUES(TeamKey), CALCULATE(MAX(FactTeamDaily[EngagedUsers])))",
        "Peak engaged (multi-feature) users per team in the period.",
    ),
    "Adoption Rate": (
        "DIVIDE([Active Users], [Assigned Seats])",
        "Share of assigned seats that were active in the period.",
    ),
    "Activation Rate": (
        "DIVIDE([Activated Users], [Assigned Seats])",
        "Share of assigned seats that have ever activated.",
    ),
    "Sustained Usage %": (
        "DIVIDE([Sustained Users], [Active Users])",
        "Share of active users who kept using Copilot for 3+ weeks.",
    ),
    "Inactive Seats": (
        "[Assigned Seats] - [Active Users]",
        "Assigned seats that were not active in the period.",
    ),
    "Avg Days to First Use": (
        "AVERAGEX(FILTER(DimDeveloper, IsActivated=1), DaysToFirstUse)",
        "Average onboarding delay between seat assignment and first usage day.",
    ),
    "Suggestions Made": (
        "SUM(FactTeamDaily[SuggestionsMade])",
        "Total inline code suggestions offered by Copilot.",
    ),
    "Suggestions Accepted": (
        "SUM(FactTeamDaily[SuggestionsAccepted])",
        "Total inline suggestions accepted by developers.",
    ),
    "Code Acceptance Rate": (
        "DIVIDE([Suggestions Accepted], [Suggestions Made])",
        "Share of Copilot suggestions accepted.",
    ),
    "Lines Accepted": (
        "SUM(FactTeamDaily[LinesAccepted])",
        "Total lines of code accepted from Copilot suggestions.",
    ),
    "Chat Sessions": (
        "SUM(FactTeamDaily[ChatSessions])",
        "Number of Copilot Chat sessions started.",
    ),
    "Agent Sessions": (
        "SUM(FactTeamDaily[AgentSessions])",
        "Number of Copilot Agent Mode sessions started.",
    ),
    "Coding Agent PRs Created": (
        "SUM(FactTeamDaily[CodingAgentPRsCreated])",
        "Pull requests raised by the Copilot coding agent.",
    ),
    "Coding Agent PRs Merged": (
        "SUM(FactTeamDaily[CodingAgentPRsMerged])",
        "Coding-agent PRs that were merged into main.",
    ),
    "AI Credits Consumed": (
        "SUM(FactTeamDaily[AICreditsConsumed])",
        "Total AI credits (premium requests) consumed.",
    ),
    "PRs Merged": (
        "SUM(FactTeamDaily[PRsMerged])",
        "Total pull requests merged in the period.",
    ),
    "Median PR Cycle Time (hrs)": (
        "MEDIANX(FILTER(FactTeamDaily, PRsMerged>0), PRCycleTimeHours)",
        "Median hours from PR open to merge (weighted by merged PRs).",
    ),
    "Avg Time to First Review (hrs)": (
        "AVERAGEX(FILTER(FactTeamDaily, PRsMerged>0), TimeToFirstReviewHours)",
        "Average hours from PR open to first reviewer comment.",
    ),
    "Avg Lead Time (hrs)": (
        "AVERAGEX(FILTER(FactTeamDaily, PRsMerged>0), LeadTimeHours)",
        "Average hours from first commit to production release.",
    ),
    "Deployments": (
        "SUM(FactTeamDaily[Deployments])",
        "Total successful deployments in the period.",
    ),
    "Failed Deployments": (
        "SUM(FactTeamDaily[FailedDeployments])",
        "Deployments that failed or were rolled back.",
    ),
    "Reworked PRs": (
        "SUM(FactTeamDaily[ReworkedPRs])",
        "Pull requests that required rework after review.",
    ),
    "Rework Rate": (
        "DIVIDE([Reworked PRs], [PRs Merged])",
        "Share of merged PRs that needed rework.",
    ),
    "Throughput per Active Engineer": (
        "DIVIDE([PRs Merged], [Active Users])",
        "Merged PRs per active developer.",
    ),
    "Escaped Defects": (
        "SUM(FactMonthlyQuality[EscapedDefects])",
        "Defects that reached production.",
    ),
    "Change Failures": (
        "SUM(FactMonthlyQuality[ChangeFailures])",
        "Changes that caused a production incident.",
    ),
    "Total Changes": (
        "SUM(FactMonthlyQuality[TotalChanges])",
        "All production changes attempted in the period.",
    ),
    "Change Failure Rate": (
        "DIVIDE([Change Failures], [Total Changes])",
        "Share of changes that led to a failure (DORA metric).",
    ),
    "Test Coverage %": (
        "AVERAGE(FactMonthlyQuality[TestCoveragePct])",
        "Average code coverage across teams in the period.",
    ),
    "Test Pass Rate": (
        "DIVIDE(SUM(TestsPassed), SUM(TestsRun))",
        "Share of tests passing in CI.",
    ),
    "Build Success Rate": (
        "DIVIDE(SUM(BuildSuccesses), SUM(BuildRuns))",
        "Share of CI builds that succeeded.",
    ),
    "Vulnerabilities Introduced": (
        "SUM(FactMonthlyQuality[VulnerabilitiesIntroduced])",
        "New vulnerabilities detected in the period.",
    ),
    "MTTR (hrs)": (
        "AVERAGE(FactMonthlyQuality[MTTRHours])",
        "Mean time to restore service after a failure (DORA metric).",
    ),
    "Flow State Score": (
        "AVERAGE(FactMonthlyQuality[FlowStateScore])",
        "Survey-based developer flow score (0-5).",
    ),
    "Tooling Satisfaction": (
        "AVERAGE(FactMonthlyQuality[ToolingSatisfaction])",
        "Survey-based tooling satisfaction score (0-5).",
    ),
    "Copilot Satisfaction": (
        "AVERAGE(FactMonthlyQuality[CopilotSatisfaction])",
        "Survey-based Copilot satisfaction score (0-5).",
    ),
    "Tech Debt Items": (
        "SUM(FactMonthlyQuality[TechDebtItems])",
        "Open technical-debt items tracked in the period.",
    ),
    "Licence Cost": (
        "Seats * Months * CostPerSeatMonth",
        "Total Copilot seat licence spend in the period.",
    ),
    "AI Credit Cost": (
        "[AI Credits Consumed] * CostPerCredit",
        "Spend on premium AI-credit consumption.",
    ),
    "Enablement Cost": (
        "Months * EnablementCostPerMonth",
        "Ongoing enablement, training and support spend.",
    ),
    "Copilot Investment": (
        "[Licence Cost] + [AI Credit Cost] + [Enablement Cost]",
        "Total Copilot programme cost in the period.",
    ),
    "Estimated Hours Saved": (
        "[Suggestions Accepted] * MinutesPerSuggestion / 60",
        "Developer hours saved from accepted Copilot suggestions.",
    ),
    "Capacity Released (FTEs)": (
        "HoursSaved * ConversionPct / (HoursPerFTEMonth * Months)",
        "FTE-equivalent capacity freed up by Copilot in the period.",
    ),
    "Gross Capacity Value": (
        "HoursSaved * ConversionPct * LoadedHourlyCost",
        "Monetised value of the capacity Copilot released.",
    ),
    "Avoided Defect Cost": (
        "MAX(0, Baseline - [Escaped Defects]) * DefectRemediationCost",
        "Value of production defects avoided vs baseline.",
    ),
    "Net Value": (
        "[Gross Capacity Value] + [Avoided Defect Cost] - [Copilot Investment]",
        "Net benefit of the Copilot programme in the period.",
    ),
    "ROI %": (
        "DIVIDE([Net Value], [Copilot Investment])",
        "Return on investment as a percentage of spend.",
    ),
    "Benefit-Cost Ratio": (
        "DIVIDE([Gross Value]+[Avoided Defect Cost], [Copilot Investment])",
        "Every R1 spent returns this many R in benefit.",
    ),
    "Cost per Active User": (
        "DIVIDE([Copilot Investment], [Active Users])",
        "Programme cost per active developer.",
    ),
    "Cost per Sustained User": (
        "DIVIDE([Copilot Investment], [Sustained Users])",
        "Programme cost per sustained (3+ week) user.",
    ),
    "Cost per Merged PR": (
        "DIVIDE([Copilot Investment], [PRs Merged])",
        "Programme cost amortised across merged PRs.",
    ),
    "Value Chain Count": (
        "SWITCH(StepOrder, 1..5, matching stage measure)",
        "Population at each stage of the eligible-to-sustained value chain.",
    ),
}

SKIP_VISUAL_TYPES = {
    "textbox", "image", "actionButton", "shape", "basicShape",
    "pageNavigator", "bookmarkNavigator", "slicer", "advancedSlicer",
}

TOOLTIP_PAGE_WIDTH = 420
TOOLTIP_PAGE_HEIGHT = 220


def slug(measure_name: str) -> str:
    s = measure_name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return f"pt-{s}"


def collect_visual_measures(visual: dict) -> list[str]:
    query_state = (visual.get("query") or {}).get("queryState") or {}
    ordered: list[str] = []
    seen: set[str] = set()
    for role in query_state.values():
        for projection in role.get("projections", []):
            measure = (projection.get("field") or {}).get("Measure")
            if not measure:
                continue
            name = measure.get("Property")
            if name and name not in seen:
                ordered.append(name)
                seen.add(name)
    return ordered


def build_tooltip_page(page_name: str, measure: str, formula: str, description: str) -> None:
    """Create the page.json and a single textbox visual inside `pages/<page_name>/`."""
    page_dir = PAGES_ROOT / page_name
    if page_dir.exists():
        shutil.rmtree(page_dir)
    (page_dir / "visuals" / f"v-{page_name}-body").mkdir(parents=True)

    page_doc = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
        "name": page_name,
        "displayName": f"Tooltip - {measure}",
        "displayOption": "ActualSize",
        "type": "Tooltip",
        "visibility": "HiddenInViewMode",
        "height": TOOLTIP_PAGE_HEIGHT,
        "width": TOOLTIP_PAGE_WIDTH,
        "pageBinding": {
            "name": page_name,
            "type": "Tooltip",
        },
        "objects": {
            "pageInformation": [
                {
                    "properties": {
                        "pageInformationType": {
                            "expr": {"Literal": {"Value": "'Tooltip'"}}
                        },
                        "pageInformationName": {
                            "expr": {"Literal": {"Value": dax_literal(f"Tooltip - {measure}")}}
                        },
                    }
                }
            ]
        },
    }
    (page_dir / "page.json").write_text(
        json.dumps(page_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    visual_doc = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.4.0/schema.json",
        "name": f"v-{page_name}-body",
        "position": {
            "x": 12, "y": 12, "z": 0,
            "height": TOOLTIP_PAGE_HEIGHT - 24,
            "width": TOOLTIP_PAGE_WIDTH - 24,
            "tabOrder": 0,
        },
        "visual": {
            "visualType": "textbox",
            "objects": {
                "general": [
                    {
                        "properties": {
                            "paragraphs": [
                                {
                                    "horizontalTextAlignment": "left",
                                    "textRuns": [
                                        {
                                            "value": measure,
                                            "textStyle": {
                                                "fontSize": "13pt",
                                                "fontWeight": "bold",
                                                "color": "#1F3A93",
                                            },
                                        }
                                    ],
                                },
                                {
                                    "horizontalTextAlignment": "left",
                                    "textRuns": [
                                        {
                                            "value": "Calculation",
                                            "textStyle": {
                                                "fontSize": "9pt",
                                                "fontWeight": "bold",
                                                "color": "#666666",
                                            },
                                        }
                                    ],
                                },
                                {
                                    "horizontalTextAlignment": "left",
                                    "textRuns": [
                                        {
                                            "value": formula,
                                            "textStyle": {
                                                "fontSize": "10pt",
                                                "fontFamily": "Consolas, monospace",
                                                "color": "#111111",
                                            },
                                        }
                                    ],
                                },
                                {
                                    "horizontalTextAlignment": "left",
                                    "textRuns": [{"value": " "}],
                                },
                                {
                                    "horizontalTextAlignment": "left",
                                    "textRuns": [
                                        {
                                            "value": "Description",
                                            "textStyle": {
                                                "fontSize": "9pt",
                                                "fontWeight": "bold",
                                                "color": "#666666",
                                            },
                                        }
                                    ],
                                },
                                {
                                    "horizontalTextAlignment": "left",
                                    "textRuns": [
                                        {
                                            "value": description,
                                            "textStyle": {
                                                "fontSize": "10pt",
                                                "color": "#333333",
                                            },
                                        }
                                    ],
                                },
                            ]
                        }
                    }
                ]
            },
            "drillFilterOtherVisuals": True,
        },
    }
    visual_path = page_dir / "visuals" / f"v-{page_name}-body" / "visual.json"
    visual_path.write_text(
        json.dumps(visual_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def dax_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _measure_field_expr(measure_name: str, entity: str = "_Measures") -> dict:
    return {
        "Measure": {
            "Expression": {"SourceRef": {"Entity": entity}},
            "Property": measure_name,
        }
    }


def _stable_filter_name(visual_name: str, measure_name: str) -> str:
    import hashlib
    return hashlib.sha1(f"{visual_name}|{measure_name}".encode()).hexdigest()[:20]


def wire_visual_tooltip(doc: dict, visual: dict, visual_name: str,
                        measure: str, tooltip_page_name: str) -> None:
    """Match the exact shape Power BI Desktop writes when Tooltips is toggled on."""

    # Strip any legacy visualTooltip we placed under objects (wrong location).
    obj = visual.get("objects") or {}
    obj.pop("visualTooltip", None)
    if "objects" in visual and not obj:
        del visual["objects"]
    elif "objects" in visual:
        visual["objects"] = obj

    vco = visual.setdefault("visualContainerObjects", {})
    vco["visualTooltip"] = [
        {
            "properties": {
                "show": {"expr": {"Literal": {"Value": "true"}}},
                "section": {"expr": {"Literal": {"Value": dax_literal(tooltip_page_name)}}},
            }
        }
    ]

    filter_config = doc.setdefault("filterConfig", {"filters": []})
    filters = filter_config.setdefault("filters", [])
    target_field = _measure_field_expr(measure)
    stable_name = _stable_filter_name(visual_name, measure)
    for f in filters:
        if f.get("field") == target_field and f.get("type") == "Advanced":
            f["name"] = stable_name
            break
    else:
        filters.append({
            "name": stable_name,
            "field": target_field,
            "type": "Advanced",
        })


def process_report_visual(path: Path, used_measures: set[str]) -> str:
    with path.open("r", encoding="utf-8-sig") as fh:
        doc = json.load(fh)

    visual = doc.get("visual") or {}
    visual_type = visual.get("visualType")
    if not visual_type or visual_type in SKIP_VISUAL_TYPES:
        # Strip any stale visualTooltip we may have added previously.
        objs = visual.get("objects") or {}
        vco = visual.get("visualContainerObjects") or {}
        changed = False
        if "visualTooltip" in objs:
            objs.pop("visualTooltip", None); changed = True
        if "visualTooltip" in vco:
            vco.pop("visualTooltip", None); changed = True
        if changed:
            _write_json(path, doc)
            return "cleared"
        return "skipped-type"

    measures = collect_visual_measures(visual)
    if not measures:
        objs = visual.get("objects") or {}
        vco = visual.get("visualContainerObjects") or {}
        changed = False
        if "visualTooltip" in objs:
            objs.pop("visualTooltip", None); changed = True
        if "visualTooltip" in vco:
            vco.pop("visualTooltip", None); changed = True
        if changed:
            _write_json(path, doc)
            return "cleared"
        return "skipped-nomeasures"

    primary = measures[0]
    used_measures.add(primary)
    wire_visual_tooltip(doc, visual, path.parent.name, primary, slug(primary))
    _write_json(path, doc)
    return "wired"


def _write_json(path: Path, doc: dict) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def update_pages_order(new_pages: list[str]) -> None:
    with PAGES_JSON.open("r", encoding="utf-8-sig") as fh:
        pages_doc = json.load(fh)

    order = pages_doc.get("pageOrder", [])
    existing = set(order)
    # Drop old tooltip pages first so the order list stays clean.
    order = [p for p in order if not p.startswith("pt-")]
    for name in new_pages:
        if name not in existing or True:
            order.append(name)
    pages_doc["pageOrder"] = order

    with PAGES_JSON.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(pages_doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def cleanup_stale_tooltip_pages() -> None:
    for entry in PAGES_ROOT.iterdir():
        if entry.is_dir() and entry.name.startswith("pt-"):
            shutil.rmtree(entry)


def main() -> None:
    used: set[str] = set()

    # Remove old tooltip pages up front so this run is idempotent.
    cleanup_stale_tooltip_pages()

    stats = {"wired": 0, "cleared": 0, "skipped-type": 0, "skipped-nomeasures": 0}
    for path in sorted(PAGES_ROOT.rglob("visual.json")):
        # Only touch report visuals, not tooltip page bodies (none yet, but safe).
        if any(part.startswith("pt-") for part in path.parts):
            continue
        stats[process_report_visual(path, used)] += 1

    # Generate one tooltip page per measure actually referenced.
    new_pages: list[str] = []
    for measure in sorted(used):
        meta = MEASURES.get(measure)
        formula, description = meta if meta else (
            "(defined in the semantic model)",
            "See _Measures.tmdl for the full DAX definition.",
        )
        page_name = slug(measure)
        build_tooltip_page(page_name, measure, formula, description)
        new_pages.append(page_name)

    update_pages_order(new_pages)

    print(
        f"Wired visuals: {stats['wired']}  "
        f"Cleared stale: {stats['cleared']}  "
        f"Skipped (type): {stats['skipped-type']}  "
        f"Skipped (no measures): {stats['skipped-nomeasures']}  "
        f"Tooltip pages: {len(new_pages)}"
    )


if __name__ == "__main__":
    main()
