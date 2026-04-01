"""
CSV Schedule Parser.

Handles CSV/TSV files with flexible column mapping. Supports:
  - Standard columns (task_id, task_name, duration, predecessors, etc.)
  - Alternate column names (ID, Activity Name, Original Duration, etc.)
  - Auto-detection of delimiter (comma, tab, semicolon)
"""

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from parsers.base import BaseParser, ParseError
from models.schedule import (
    ScheduleData, ProjectInfo, Activity, Relationship, Resource,
    ResourceAssignment, RelationshipType, ActivityType, ActivityStatus,
    ConstraintType,
)

# Maps common column name variants → our canonical field names
COLUMN_ALIASES = {
    # Activity ID
    "task_id": "activity_id", "activity_id": "activity_id", "id": "activity_id",
    "activity id": "activity_id", "task id": "activity_id",
    "activity code": "activity_id", "task_code": "activity_id",
    # Activity Name
    "task_name": "name", "activity_name": "name", "name": "name",
    "activity name": "name", "task name": "name",
    "description": "name", "activity description": "name",
    # Duration
    "duration": "duration", "original_duration": "duration",
    "original duration": "duration", "dur": "duration",
    "remaining_duration": "remaining_duration",
    "remaining duration": "remaining_duration",
    # Dates
    "start_date": "start_date", "start date": "start_date", "start": "start_date",
    "planned_start": "start_date", "early_start": "start_date", "early start": "start_date",
    "end_date": "finish_date", "end date": "finish_date",
    "finish_date": "finish_date", "finish date": "finish_date", "finish": "finish_date",
    "planned_finish": "finish_date", "early_finish": "finish_date", "early finish": "finish_date",
    "actual_start": "actual_start", "actual start": "actual_start",
    "actual_finish": "actual_finish", "actual finish": "actual_finish",
    "baseline_start": "baseline_start", "baseline start": "baseline_start", "bl_start": "baseline_start",
    "baseline_finish": "baseline_finish", "baseline finish": "baseline_finish", "bl_finish": "baseline_finish",
    # Predecessors
    "predecessors": "predecessors", "predecessor": "predecessors",
    "pred": "predecessors", "depends_on": "predecessors", "dependencies": "predecessors",
    # Resource
    "resource": "resource", "resources": "resource",
    "assigned_to": "resource", "assigned to": "resource",
    # Float
    "total_float": "total_float", "total float": "total_float",
    "float": "total_float", "slack": "total_float",
    "free_float": "free_float", "free float": "free_float",
    # WBS
    "wbs": "wbs", "wbs_id": "wbs", "wbs id": "wbs",
    # Percent complete
    "percent_complete": "percent_complete", "percent complete": "percent_complete",
    "% complete": "percent_complete", "pct_complete": "percent_complete", "progress": "percent_complete",
    # Type
    "type": "activity_type", "task_type": "activity_type",
    "activity_type": "activity_type", "activity type": "activity_type",
    # Constraint
    "constraint_type": "constraint_type", "constraint type": "constraint_type",
    "constraint_date": "constraint_date", "constraint date": "constraint_date",
    # Calendar
    "calendar": "calendar_id", "calendar_id": "calendar_id", "calendar id": "calendar_id",
}

REQUIRED_FIELDS = {"activity_id", "name", "duration"}


class CSVScheduleParser(BaseParser):
    """Parse CSV/TSV schedule files with flexible column mapping."""

    @property
    def supported_extensions(self) -> list[str]:
        return [".csv", ".tsv"]

    @property
    def format_name(self) -> str:
        return "CSV/TSV Schedule"

    def parse(self, file_path: str) -> ScheduleData:
        path = Path(file_path)
        if not path.exists():
            raise ParseError(f"File not found: {file_path}")

        try:
            raw = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                raw = path.read_text(encoding="latin-1")
            except Exception as e:
                raise ParseError(f"Cannot read file encoding: {e}")

        if not raw.strip():
            raise ParseError(f"File is empty: {file_path}")

        delimiter = self._detect_delimiter(raw)

        try:
            df = pd.read_csv(io.StringIO(raw), delimiter=delimiter)
        except Exception as e:
            raise ParseError(f"Failed to parse CSV: {e}")

        if df.empty:
            raise ParseError("CSV file has no data rows")

        # Map columns
        column_map = self._map_columns(df.columns.tolist())
        mapped_fields = set(column_map.values())
        missing = REQUIRED_FIELDS - mapped_fields
        if missing:
            raise ParseError(
                f"Cannot find required columns: {', '.join(sorted(missing))}. "
                f"Detected columns: {', '.join(df.columns.tolist())}"
            )

        df = df.rename(columns={orig: canonical for orig, canonical in column_map.items()})

        # Build ScheduleData
        schedule = ScheduleData()
        schedule.project = ProjectInfo(
            name=path.stem,
            source_format="csv",
            source_file=str(path),
        )

        activities, relationships, resources, assignments = self._build_objects(df)
        schedule.activities = activities
        schedule.relationships = relationships
        schedule.resources = resources
        schedule.resource_assignments = assignments

        starts = [a.start_date for a in activities if a.start_date]
        finishes = [a.finish_date for a in activities if a.finish_date]
        if starts:
            schedule.project.start_date = min(starts)
        if finishes:
            schedule.project.finish_date = max(finishes)

        return schedule

    def _detect_delimiter(self, raw: str) -> str:
        first_lines = raw.split("\n", 5)[:5]
        sample = "\n".join(first_lines)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            return dialect.delimiter
        except csv.Error:
            return ","

    def _map_columns(self, columns: list[str]) -> dict[str, str]:
        mapping = {}
        for col in columns:
            normalized = col.strip().lower().replace("-", "_")
            if normalized in COLUMN_ALIASES:
                mapping[col] = COLUMN_ALIASES[normalized]
        return mapping

    def _parse_date(self, val) -> Optional[datetime]:
        if pd.isna(val) or str(val).strip() == "":
            return None
        try:
            return pd.to_datetime(val)
        except Exception:
            return None

    def _parse_float_val(self, val) -> Optional[float]:
        if pd.isna(val) or str(val).strip() == "":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _parse_predecessors(self, val) -> list[tuple[str, RelationshipType, float]]:
        """
        Parse predecessor string. Supports:
          "T1, T2"           → FS with 0 lag
          "T1FS, T2SS+3"     → typed with lag
          "T1FS-2"           → typed with lead
        """
        if pd.isna(val) or str(val).strip() == "":
            return []

        results = []
        for part in str(val).split(","):
            part = part.strip()
            if not part:
                continue

            rel_type = RelationshipType.FS
            lag = 0.0
            pred_id = part

            for rt in ["FS", "SS", "FF", "SF"]:
                idx = part.upper().find(rt)
                if idx > 0:
                    pred_id = part[:idx].strip()
                    rel_type = RelationshipType[rt]
                    remainder = part[idx + 2:].strip()
                    if remainder:
                        try:
                            lag = float(remainder.replace("+", ""))
                        except ValueError:
                            pass
                    break

            if pred_id:
                results.append((pred_id, rel_type, lag))

        return results

    def _infer_status(self, row: dict) -> ActivityStatus:
        pct = self._parse_float_val(row.get("percent_complete"))
        if pct is not None and pct >= 100:
            return ActivityStatus.COMPLETED
        if self._parse_date(row.get("actual_finish")):
            return ActivityStatus.COMPLETED
        if self._parse_date(row.get("actual_start")):
            return ActivityStatus.IN_PROGRESS
        if pct is not None and pct > 0:
            return ActivityStatus.IN_PROGRESS
        return ActivityStatus.NOT_STARTED

    def _build_objects(self, df: pd.DataFrame) -> tuple:
        activities = []
        relationships = []
        resource_map = {}
        assignments = []

        for _, row in df.iterrows():
            row_dict = row.to_dict()

            activity_id = str(row_dict.get("activity_id", "")).strip()
            if not activity_id:
                continue

            dur = self._parse_float_val(row_dict.get("duration"))
            if dur is None:
                raise ParseError(f"Activity '{activity_id}' has invalid duration")

            act_type = ActivityType.TASK
            if dur == 0:
                act_type = ActivityType.MILESTONE
            type_str = str(row_dict.get("activity_type", "")).strip().upper()
            if type_str in ("MILESTONE", "MILE"):
                act_type = ActivityType.MILESTONE
            elif type_str in ("LOE", "LEVEL OF EFFORT", "HAMMOCK"):
                act_type = ActivityType.LOE
            elif type_str in ("SUMMARY", "WBS"):
                act_type = ActivityType.SUMMARY

            activity = Activity(
                activity_id=activity_id,
                name=str(row_dict.get("name", activity_id)).strip(),
                duration=dur,
                original_duration=dur,
                start_date=self._parse_date(row_dict.get("start_date")),
                finish_date=self._parse_date(row_dict.get("finish_date")),
                actual_start=self._parse_date(row_dict.get("actual_start")),
                actual_finish=self._parse_date(row_dict.get("actual_finish")),
                baseline_start=self._parse_date(row_dict.get("baseline_start")),
                baseline_finish=self._parse_date(row_dict.get("baseline_finish")),
                activity_type=act_type,
                status=self._infer_status(row_dict),
                percent_complete=self._parse_float_val(row_dict.get("percent_complete")) or 0.0,
                wbs_id=str(row_dict.get("wbs", "")).strip() or None,
                calendar_id=str(row_dict.get("calendar_id", "")).strip() or None,
                total_float=self._parse_float_val(row_dict.get("total_float")),
                free_float=self._parse_float_val(row_dict.get("free_float")),
            )

            ct = str(row_dict.get("constraint_type", "")).strip().upper()
            if ct and ct != "NONE":
                for c in ConstraintType:
                    if c.name == ct:
                        activity.constraint_type = c
                        activity.constraint_date = self._parse_date(row_dict.get("constraint_date"))
                        break

            activities.append(activity)

            preds = self._parse_predecessors(row_dict.get("predecessors"))
            for pred_id, rel_type, lag in preds:
                relationships.append(Relationship(
                    predecessor_id=pred_id,
                    successor_id=activity_id,
                    relationship_type=rel_type,
                    lag_days=lag,
                ))

            res_name = str(row_dict.get("resource", "")).strip()
            if res_name and res_name.lower() not in ("", "nan", "none"):
                if res_name not in resource_map:
                    resource_map[res_name] = Resource(
                        resource_id=f"R{len(resource_map) + 1}",
                        name=res_name,
                    )
                assignments.append(ResourceAssignment(
                    activity_id=activity_id,
                    resource_id=resource_map[res_name].resource_id,
                ))

        return activities, relationships, list(resource_map.values()), assignments
