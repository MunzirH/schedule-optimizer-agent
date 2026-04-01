"""
Schedule Optimizer Agent — CLI Entry Point

Usage:
    python main.py <schedule_file>              — Run analysis and print report
    python main.py <schedule_file> --chat       — Run analysis then enter AI chat mode

    python main.py data/sample_schedule.xer
    python main.py data/sample_schedule.xer --chat
"""

import sys
from pathlib import Path
from parsers.registry import create_default_registry
from models.schedule import ActivityStatus, ActivityType, RelationshipType


def print_header(text: str):
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def print_section(text: str):
    print(f"\n--- {text} ---")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    chat_mode = "--chat" in flags

    if not args:
        print("Usage: python main.py <schedule_file> [--chat]")
        print("Supported formats: .csv, .tsv, .xer, .xml")
        print("\nExamples:")
        print("  python main.py data/sample_schedule.xer")
        print("  python main.py data/sample_schedule.xer --chat")
        print("\nOptions:")
        print("  --chat    Enter interactive AI chat mode after analysis")
        sys.exit(1)

    file_path = args[0]

    if not Path(file_path).exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    # Parse the file
    registry = create_default_registry()

    try:
        parser = registry.get_parser(file_path)
        print(f"Detected format: {parser.format_name}")
        print(f"Parsing: {file_path}")
        schedule = registry.parse(file_path)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    # ── Project Overview ──────────────────────────────────────────────
    print_header("PROJECT OVERVIEW")
    print(f"  Project Name:    {schedule.project.name or 'Unknown'}")
    print(f"  Source Format:   {schedule.project.source_format}")
    print(f"  Data Date:       {schedule.project.data_date.strftime('%Y-%m-%d') if schedule.project.data_date else 'N/A'}")
    print(f"  Project Start:   {schedule.project.start_date.strftime('%Y-%m-%d') if schedule.project.start_date else 'N/A'}")
    print(f"  Project Finish:  {schedule.project.finish_date.strftime('%Y-%m-%d') if schedule.project.finish_date else 'N/A'}")

    # ── Schedule Statistics ───────────────────────────────────────────
    print_header("SCHEDULE STATISTICS")

    total = len(schedule.activities)
    tasks = [a for a in schedule.activities if a.activity_type == ActivityType.TASK]
    milestones = [a for a in schedule.activities if a.activity_type == ActivityType.MILESTONE]
    loe = [a for a in schedule.activities if a.activity_type == ActivityType.LOE]

    print(f"  Total Activities:    {total}")
    print(f"    Tasks:             {len(tasks)}")
    print(f"    Milestones:        {len(milestones)}")
    print(f"    LOE/Summary:       {len(loe)}")
    print(f"  Relationships:       {len(schedule.relationships)}")
    print(f"  Resources:           {len(schedule.resources)}")
    print(f"  Calendars:           {len(schedule.calendars)}")
    print(f"  WBS Nodes:           {len(schedule.wbs)}")

    # ── Status Breakdown ──────────────────────────────────────────────
    print_section("Status Breakdown")
    completed = [a for a in schedule.activities if a.status == ActivityStatus.COMPLETED]
    in_progress = [a for a in schedule.activities if a.status == ActivityStatus.IN_PROGRESS]
    not_started = [a for a in schedule.activities if a.status == ActivityStatus.NOT_STARTED]

    bar_width = 30
    if total > 0:
        c_pct = len(completed) / total
        p_pct = len(in_progress) / total
        n_pct = len(not_started) / total

        c_bar = int(c_pct * bar_width)
        p_bar = int(p_pct * bar_width)
        n_bar = bar_width - c_bar - p_bar

        print(f"  Completed:     {len(completed):>3} ({c_pct:.0%})")
        print(f"  In Progress:   {len(in_progress):>3} ({p_pct:.0%})")
        print(f"  Not Started:   {len(not_started):>3} ({n_pct:.0%})")
        print(f"\n  [{'#' * c_bar}{'~' * p_bar}{'.' * n_bar}]")
        print(f"   {'#=Done':<12}{'~=Active':<12}{'.=Pending'}")

    # ── Relationship Types ────────────────────────────────────────────
    print_section("Relationship Types")
    rel_counts = {}
    for r in schedule.relationships:
        key = r.relationship_type.name
        rel_counts[key] = rel_counts.get(key, 0) + 1

    total_rels = len(schedule.relationships)
    for rtype, count in sorted(rel_counts.items(), key=lambda x: -x[1]):
        pct = count / total_rels * 100 if total_rels > 0 else 0
        print(f"  {rtype:<4}  {count:>4}  ({pct:.0f}%)")

    # ── Lag/Lead Summary ──────────────────────────────────────────────
    rels_with_lag = [r for r in schedule.relationships if r.lag_days > 0]
    rels_with_lead = [r for r in schedule.relationships if r.lag_days < 0]

    if rels_with_lag or rels_with_lead:
        print_section("Lag/Lead Summary")
        if rels_with_lag:
            print(f"  Relationships with lag:   {len(rels_with_lag)}")
        if rels_with_lead:
            print(f"  Relationships with lead:  {len(rels_with_lead)}")

    # ── Quick Health Checks ───────────────────────────────────────────
    print_header("QUICK HEALTH CHECKS")

    activity_ids = schedule.activity_ids()
    issues = []
    warnings = []

    # Missing predecessors
    acts_with_preds = {r.successor_id for r in schedule.relationships}
    no_pred = [a for a in schedule.activities
               if a.activity_id not in acts_with_preds
               and a.activity_type == ActivityType.TASK
               and a.status != ActivityStatus.COMPLETED]
    if len(no_pred) > 1:
        issues.append(f"{len(no_pred)} tasks have no predecessors")

    # Missing successors
    acts_with_succs = {r.predecessor_id for r in schedule.relationships}
    no_succ = [a for a in schedule.activities
               if a.activity_id not in acts_with_succs
               and a.activity_type == ActivityType.TASK
               and a.status != ActivityStatus.COMPLETED]
    if len(no_succ) > 1:
        issues.append(f"{len(no_succ)} tasks have no successors")

    # Invalid predecessor references
    for r in schedule.relationships:
        if r.predecessor_id not in activity_ids:
            issues.append(f"Relationship references non-existent predecessor '{r.predecessor_id}'")
        if r.successor_id not in activity_ids:
            issues.append(f"Relationship references non-existent successor '{r.successor_id}'")

    # High float
    high_float = [a for a in schedule.activities
                  if a.total_float is not None and a.total_float > 44
                  and a.activity_type == ActivityType.TASK]
    if high_float:
        issues.append(f"{len(high_float)} tasks have total float > 44 days")

    # Negative float
    neg_float = [a for a in schedule.activities
                 if a.total_float is not None and a.total_float < 0]
    if neg_float:
        issues.append(f"{len(neg_float)} tasks have negative float")

    # Long activities
    long_acts = [a for a in schedule.activities
                 if a.duration > 44
                 and a.activity_type == ActivityType.TASK]
    if long_acts:
        warnings.append(f"{len(long_acts)} tasks have duration > 44 days")

    # FS percentage
    fs_count = rel_counts.get("FS", 0)
    if total_rels > 0:
        fs_pct = fs_count / total_rels * 100
        if fs_pct < 90:
            warnings.append(f"Only {fs_pct:.0f}% finish-to-start relationships (DCMA target: 90%+)")

    if issues:
        print(f"\n  Issues ({len(issues)}):")
        for issue in issues:
            print(f"    ! {issue}")
    else:
        print("\n  No critical issues found")

    if warnings:
        print(f"\n  Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"    ~ {w}")

    if not issues and not warnings:
        print("  Schedule looks healthy based on quick checks")

    # ── Activity List ─────────────────────────────────────────────────
    print_header("ACTIVITY LIST")

    # Column headers
    print(f"  {'ID':<8} {'Name':<30} {'Dur':>5} {'Status':<12} {'Float':>6}")
    print(f"  {'─'*8} {'─'*30} {'─'*5} {'─'*12} {'─'*6}")

    for a in schedule.activities:
        name = a.name[:28] + ".." if len(a.name) > 30 else a.name
        float_str = f"{a.total_float:.0f}" if a.total_float is not None else "-"
        status = a.status.value
        crit = " *" if a.total_float is not None and a.total_float == 0 else ""
        print(f"  {a.activity_id:<8} {name:<30} {a.duration:>5.1f} {status:<12} {float_str:>5}{crit}")

    print(f"\n  * = Critical (zero float)")

    # ── Resources ─────────────────────────────────────────────────────
    if schedule.resources:
        print_section("Resources")
        for r in schedule.resources:
            assignment_count = len([
                a for a in schedule.resource_assignments
                if a.resource_id == r.resource_id
            ])
            print(f"  {r.name:<30} {assignment_count} assignments")

    # ── DCMA 14-Point Assessment ─────────────────────────────────────
    from agent.dcma_assessment import run_dcma_assessment, print_dcma_report

    report = run_dcma_assessment(schedule)
    print_dcma_report(report)

    # ── Risk Analysis ─────────────────────────────────────────────────
    from agent.risk_analysis import analyze_risks, print_risk_report

    risk_report = analyze_risks(schedule)
    print_risk_report(risk_report)

    print(f"  Analysis complete. {total} activities processed.\n")

    # ── AI Chat Mode ──────────────────────────────────────────────────
    if chat_mode:
        from agent.chat import run_chat

        provider = "claude" if "--claude" in flags else "gemini"
        run_chat(schedule, report, risk_report, provider=provider)


if __name__ == "__main__":
    main()
