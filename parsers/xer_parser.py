"""
Primavera P6 XER Parser.

XER files are tab-delimited text files with a specific structure:
  %T <TABLE_NAME>     → table header
  %F <field1> <field2> → field names
  %R <val1> <val2>     → data row
  %E                   → end of file

Key tables we extract:
  TASK      → activities
  TASKPRED  → relationships
  CALENDAR  → calendars
  RSRC      → resources
  TASKRSRC  → resource assignments
  PROJWBS   → WBS structure
  PROJECT   → project metadata
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from parsers.base import BaseParser, ParseError
from models.schedule import (
    ScheduleData, ProjectInfo, Activity, Relationship, Resource,
    ResourceAssignment, Calendar, WBSNode,
    RelationshipType, ActivityType, ActivityStatus, ConstraintType,
)

# P6 relationship type codes → our enum
P6_REL_TYPES = {
    "PR_FS": RelationshipType.FS,
    "PR_SS": RelationshipType.SS,
    "PR_FF": RelationshipType.FF,
    "PR_SF": RelationshipType.SF,
}

# P6 task type codes → our enum
P6_TASK_TYPES = {
    "TT_Task": ActivityType.TASK,
    "TT_Mile": ActivityType.MILESTONE,
    "TT_LOE": ActivityType.LOE,
    "TT_Rsrc": ActivityType.TASK,
    "TT_WBS": ActivityType.WBS_SUMMARY,
    "TT_FinMile": ActivityType.MILESTONE,
}

# P6 task status codes → our enum
P6_STATUS = {
    "TK_NotStart": ActivityStatus.NOT_STARTED,
    "TK_Active": ActivityStatus.IN_PROGRESS,
    "TK_Complete": ActivityStatus.COMPLETED,
}

# P6 constraint type codes → our enum
P6_CONSTRAINTS = {
    "CS_ALAP": ConstraintType.ALAP,
    "CS_ASAP": ConstraintType.ASAP,
    "CS_MEO": ConstraintType.MSO,
    "CS_MEOB": ConstraintType.MSO,
    "CS_MSO": ConstraintType.MSO,
    "CS_MSOB": ConstraintType.MSO,
    "CS_MFO": ConstraintType.MFO,
    "CS_MFOB": ConstraintType.MFO,
    "CS_SNET": ConstraintType.SNET,
    "CS_SNLT": ConstraintType.SNLT,
    "CS_FNET": ConstraintType.FNET,
    "CS_FNLT": ConstraintType.FNLT,
}

# P6 workday flags per calendar type
P6_WEEKDAYS = {
    "d1": 0, "d2": 1, "d3": 2, "d4": 3,
    "d5": 4, "d6": 5, "d7": 6,
}


class XERParser(BaseParser):
    """Parse Primavera P6 XER files."""

    @property
    def supported_extensions(self) -> list[str]:
        return [".xer"]

    @property
    def format_name(self) -> str:
        return "Primavera P6 XER"

    def can_parse(self, file_path: str) -> bool:
        """XER files start with 'ERMHDR'."""
        try:
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
                first_line = f.readline()
                return first_line.strip().startswith("ERMHDR")
        except Exception:
            return False

    def parse(self, file_path: str) -> ScheduleData:
        path = Path(file_path)
        if not path.exists():
            raise ParseError(f"File not found: {file_path}")

        # Read and parse raw XER tables
        tables = self._read_xer_tables(file_path)

        if not tables:
            raise ParseError("XER file contains no recognizable tables")

        schedule = ScheduleData()

        # Extract project info
        schedule.project = self._extract_project(tables, file_path)

        # Extract calendars
        schedule.calendars = self._extract_calendars(tables)

        # Extract WBS
        schedule.wbs = self._extract_wbs(tables)

        # Extract resources
        schedule.resources = self._extract_resources(tables)

        # Extract activities (TASK table)
        schedule.activities = self._extract_activities(tables)

        # Extract relationships (TASKPRED table)
        schedule.relationships = self._extract_relationships(tables)

        # Extract resource assignments (TASKRSRC table)
        schedule.resource_assignments = self._extract_assignments(tables)

        # Fallback: compute project dates from activities if not in PROJECT table
        if schedule.activities:
            if not schedule.project.start_date:
                starts = [a.start_date for a in schedule.activities if a.start_date]
                if starts:
                    schedule.project.start_date = min(starts)
            if not schedule.project.finish_date:
                finishes = [a.finish_date for a in schedule.activities if a.finish_date]
                if finishes:
                    schedule.project.finish_date = max(finishes)

        return schedule

    # ── Raw XER parsing ──────────────────────────────────────────────────

    def _read_xer_tables(self, file_path: str) -> dict[str, list[dict]]:
        """
        Parse the XER file into a dict of table_name → list of row dicts.

        XER structure:
          %T TABLE_NAME
          %F field1  field2  field3
          %R value1  value2  value3
          %R value1  value2  value3
          %T NEXT_TABLE
          ...
        """
        tables = {}
        current_table = None
        current_fields = []

        encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
        lines = None

        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc, errors="replace") as f:
                    lines = f.readlines()
                break
            except Exception:
                continue

        if lines is None:
            raise ParseError(f"Cannot read XER file with any known encoding")

        for line in lines:
            line = line.rstrip("\n").rstrip("\r")

            if line.startswith("%T"):
                # Table header
                parts = line.split("\t")
                current_table = parts[1].strip() if len(parts) > 1 else None
                current_fields = []
                if current_table and current_table not in tables:
                    tables[current_table] = []

            elif line.startswith("%F") and current_table:
                # Field definitions
                current_fields = [f.strip() for f in line.split("\t")[1:]]

            elif line.startswith("%R") and current_table and current_fields:
                # Data row
                values = line.split("\t")[1:]
                row = {}
                for i, field_name in enumerate(current_fields):
                    row[field_name] = values[i].strip() if i < len(values) else ""
                tables[current_table].append(row)

        return tables

    def _parse_p6_date(self, val: str) -> Optional[datetime]:
        """Parse P6 date string (format: 'yyyy-mm-dd HH:MM' or similar)."""
        if not val or val.strip() == "":
            return None

        formats = [
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%d-%b-%y %H:%M",
            "%d-%b-%y",
            "%m/%d/%Y",
            "%m/%d/%Y %H:%M",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(val.strip(), fmt)
            except ValueError:
                continue

        return None

    def _safe_float(self, val: str) -> float:
        """Parse a string to float, returning 0.0 on failure."""
        try:
            return float(val) if val and val.strip() else 0.0
        except (ValueError, TypeError):
            return 0.0

    # ── Table extractors ─────────────────────────────────────────────────

    def _extract_project(self, tables: dict, file_path: str) -> ProjectInfo:
        """Extract project metadata from PROJECT table."""
        info = ProjectInfo(
            source_format="xer",
            source_file=str(file_path),
        )

        project_rows = tables.get("PROJECT", [])
        if project_rows:
            row = project_rows[0]  # take first project
            info.project_id = row.get("proj_id", "")
            info.name = row.get("proj_short_name", "") or row.get("proj_name", "")
            info.data_date = self._parse_p6_date(
                row.get("last_recalc_date", "") or row.get("last_schedule_date", "")
            )
            info.start_date = self._parse_p6_date(
                row.get("plan_start_date", "") or row.get("scd_start_date", "")
                or row.get("act_start_date", "")
            )
            info.finish_date = self._parse_p6_date(
                row.get("plan_end_date", "") or row.get("scd_end_date", "")
                or row.get("plan_finish_date", "") or row.get("fcst_end_date", "")
            )

        return info

    def _extract_calendars(self, tables: dict) -> list[Calendar]:
        """Extract calendars from CALENDAR table."""
        calendars = []

        for row in tables.get("CALENDAR", []):
            cal = Calendar(
                calendar_id=row.get("clndr_id", ""),
                name=row.get("clndr_name", "Unknown Calendar"),
                is_default=row.get("default_flag", "") == "Y",
                hours_per_day=self._safe_float(row.get("day_hr_cnt", "8")),
            )

            # Parse work days from clndr_data if available
            clndr_data = row.get("clndr_data", "")
            if clndr_data:
                work_days = []
                for day_key, day_num in P6_WEEKDAYS.items():
                    if f"({day_key}(s()" in clndr_data.lower() or f"|{day_key}|" in clndr_data:
                        pass  # non-working
                    else:
                        work_days.append(day_num)
                if work_days:
                    cal.work_days = work_days

            calendars.append(cal)

        return calendars

    def _extract_wbs(self, tables: dict) -> list[WBSNode]:
        """Extract WBS hierarchy from PROJWBS table."""
        wbs_nodes = []

        for row in tables.get("PROJWBS", []):
            node = WBSNode(
                wbs_id=row.get("wbs_id", ""),
                name=row.get("wbs_name", "") or row.get("wbs_short_name", ""),
                parent_id=row.get("parent_wbs_id") or None,
            )

            # Calculate level from seq_num or parent chain
            seq = row.get("seq_num", "0")
            try:
                node.level = int(seq) if seq else 0
            except ValueError:
                node.level = 0

            wbs_nodes.append(node)

        return wbs_nodes

    def _extract_resources(self, tables: dict) -> list[Resource]:
        """Extract resources from RSRC table."""
        resources = []

        for row in tables.get("RSRC", []):
            res = Resource(
                resource_id=row.get("rsrc_id", ""),
                name=row.get("rsrc_name", "") or row.get("rsrc_short_name", ""),
                resource_type=row.get("rsrc_type", "RT_Labor").replace("RT_", ""),
                max_units=self._safe_float(row.get("max_qty_per_hr", "1")),
            )
            resources.append(res)

        return resources

    def _extract_activities(self, tables: dict) -> list[Activity]:
        """Extract activities from TASK table."""
        activities = []

        for row in tables.get("TASK", []):
            task_type_str = row.get("task_type", "TT_Task")
            act_type = P6_TASK_TYPES.get(task_type_str, ActivityType.TASK)

            status_str = row.get("status_code", "TK_NotStart")
            status = P6_STATUS.get(status_str, ActivityStatus.NOT_STARTED)

            # Duration — P6 stores hours, convert to days
            hours_per_day = 8.0
            target_drtn = self._safe_float(row.get("target_drtn_hr_cnt", "0"))
            remain_drtn = self._safe_float(row.get("remain_drtn_hr_cnt", "0"))
            duration_days = remain_drtn / hours_per_day if remain_drtn else target_drtn / hours_per_day

            # Constraint
            constraint_type = ConstraintType.NONE
            constraint_str = row.get("cstr_type", "")
            if constraint_str:
                constraint_type = P6_CONSTRAINTS.get(constraint_str, ConstraintType.NONE)

            activity = Activity(
                activity_id=row.get("task_id", ""),
                name=row.get("task_name", ""),
                duration=duration_days,
                original_duration=target_drtn / hours_per_day if target_drtn else duration_days,
                start_date=self._parse_p6_date(row.get("early_start_date", "")),
                finish_date=self._parse_p6_date(row.get("early_end_date", "")),
                actual_start=self._parse_p6_date(row.get("act_start_date", "")),
                actual_finish=self._parse_p6_date(row.get("act_end_date", "")),
                baseline_start=self._parse_p6_date(row.get("target_start_date", "")),
                baseline_finish=self._parse_p6_date(row.get("target_end_date", "")),
                activity_type=act_type,
                status=status,
                percent_complete=self._safe_float(row.get("phys_complete_pct", "0")),
                wbs_id=row.get("wbs_id") or None,
                calendar_id=row.get("clndr_id") or None,
                total_float=self._safe_float(row.get("total_float_hr_cnt", "0")) / hours_per_day,
                free_float=self._safe_float(row.get("free_float_hr_cnt", "0")) / hours_per_day,
                constraint_type=constraint_type,
                constraint_date=self._parse_p6_date(row.get("cstr_date", "")),
            )

            activities.append(activity)

        return activities

    def _extract_relationships(self, tables: dict) -> list[Relationship]:
        """Extract relationships from TASKPRED table."""
        relationships = []

        for row in tables.get("TASKPRED", []):
            rel_type_str = row.get("pred_type", "PR_FS")
            rel_type = P6_REL_TYPES.get(rel_type_str, RelationshipType.FS)

            # P6 stores lag in hours
            lag_hours = self._safe_float(row.get("lag_hr_cnt", "0"))
            lag_days = lag_hours / 8.0

            rel = Relationship(
                predecessor_id=row.get("pred_task_id", ""),
                successor_id=row.get("task_id", ""),
                relationship_type=rel_type,
                lag_days=lag_days,
            )
            relationships.append(rel)

        return relationships

    def _extract_assignments(self, tables: dict) -> list[ResourceAssignment]:
        """Extract resource assignments from TASKRSRC table."""
        assignments = []

        for row in tables.get("TASKRSRC", []):
            assignment = ResourceAssignment(
                activity_id=row.get("task_id", ""),
                resource_id=row.get("rsrc_id", ""),
                planned_units=self._safe_float(row.get("target_qty", "0")),
                actual_units=self._safe_float(row.get("act_reg_qty", "0")),
                planned_cost=self._safe_float(row.get("target_cost", "0")),
                actual_cost=self._safe_float(row.get("act_reg_cost", "0")),
            )
            assignments.append(assignment)

        return assignments
