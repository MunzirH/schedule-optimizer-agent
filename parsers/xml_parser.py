"""
XML Schedule Parser.

Handles two major XML schedule formats:
  1. Primavera P6 PMXML (.xml with <APIBusinessObjects> root)
  2. Microsoft Project XML (.xml with <Project> root)

Auto-detects which format based on the root element.
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

from parsers.base import BaseParser, ParseError
from models.schedule import (
    ScheduleData, ProjectInfo, Activity, Relationship, Resource,
    ResourceAssignment, Calendar, WBSNode,
    RelationshipType, ActivityType, ActivityStatus, ConstraintType,
)


class XMLParser(BaseParser):
    """Parse P6 PMXML and Microsoft Project XML files."""

    @property
    def supported_extensions(self) -> list[str]:
        return [".xml"]

    @property
    def format_name(self) -> str:
        return "XML Schedule (P6 PMXML / MS Project)"

    def can_parse(self, file_path: str) -> bool:
        """Check if XML file is a schedule format we recognize."""
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
            return tag in ("APIBusinessObjects", "Project")
        except Exception:
            return False

    def parse(self, file_path: str) -> ScheduleData:
        path = Path(file_path)
        if not path.exists():
            raise ParseError(f"File not found: {file_path}")

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except ET.ParseError as e:
            raise ParseError(f"Invalid XML: {e}")

        # Strip namespace for easier element access
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        ns = root.tag.replace(tag, "") if "}" in root.tag else ""

        if tag == "APIBusinessObjects":
            return self._parse_pmxml(root, ns, file_path)
        elif tag == "Project":
            return self._parse_msp_xml(root, ns, file_path)
        else:
            raise ParseError(
                f"Unrecognized XML root element: '{tag}'. "
                f"Expected 'APIBusinessObjects' (P6) or 'Project' (MS Project)"
            )

    # ── Helper methods ───────────────────────────────────────────────────

    def _find(self, element: ET.Element, tag: str, ns: str) -> Optional[ET.Element]:
        """Find a child element, trying with and without namespace."""
        el = element.find(f"{ns}{tag}")
        if el is None:
            el = element.find(tag)
        return el

    def _findall(self, element: ET.Element, tag: str, ns: str) -> list[ET.Element]:
        """Find all matching child elements."""
        els = element.findall(f"{ns}{tag}")
        if not els:
            els = element.findall(tag)
        return els

    def _text(self, element: ET.Element, tag: str, ns: str, default: str = "") -> str:
        """Get text content of a child element."""
        el = self._find(element, tag, ns)
        return el.text.strip() if el is not None and el.text else default

    def _float_text(self, element: ET.Element, tag: str, ns: str) -> float:
        """Get float value from a child element's text."""
        val = self._text(element, tag, ns)
        try:
            return float(val) if val else 0.0
        except (ValueError, TypeError):
            return 0.0

    def _parse_date(self, val: str) -> Optional[datetime]:
        """Parse an XML date string."""
        if not val:
            return None
        formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(val.strip(), fmt)
            except ValueError:
                continue
        return None

    # ── P6 PMXML ─────────────────────────────────────────────────────────

    def _parse_pmxml(self, root: ET.Element, ns: str, file_path: str) -> ScheduleData:
        """Parse Primavera P6 PMXML format."""
        schedule = ScheduleData()

        # Project info
        projects = self._findall(root, "Project", ns)
        if projects:
            proj = projects[0]
            schedule.project = ProjectInfo(
                project_id=self._text(proj, "Id", ns),
                name=self._text(proj, "Name", ns),
                data_date=self._parse_date(self._text(proj, "DataDate", ns)),
                start_date=self._parse_date(self._text(proj, "StartDate", ns)
                            or self._text(proj, "PlannedStartDate", ns)),
                finish_date=self._parse_date(self._text(proj, "FinishDate", ns)),
                source_format="pmxml",
                source_file=str(file_path),
            )

        # WBS
        for wbs_el in self._findall(root, "WBS", ns):
            schedule.wbs.append(WBSNode(
                wbs_id=self._text(wbs_el, "ObjectId", ns) or self._text(wbs_el, "Code", ns),
                name=self._text(wbs_el, "Name", ns),
                parent_id=self._text(wbs_el, "ParentObjectId", ns) or None,
            ))

        # Activities
        for act_el in self._findall(root, "Activity", ns):
            act_type_str = self._text(act_el, "Type", ns)
            act_type = ActivityType.TASK
            if "Milestone" in act_type_str:
                act_type = ActivityType.MILESTONE
            elif "LOE" in act_type_str or "Level" in act_type_str:
                act_type = ActivityType.LOE

            status_str = self._text(act_el, "Status", ns)
            status = ActivityStatus.NOT_STARTED
            if "Completed" in status_str:
                status = ActivityStatus.COMPLETED
            elif "Progress" in status_str or "Active" in status_str:
                status = ActivityStatus.IN_PROGRESS

            dur_hours = self._float_text(act_el, "PlannedDuration", ns)
            if dur_hours == 0:
                dur_hours = self._float_text(act_el, "RemainingDuration", ns)

            activity = Activity(
                activity_id=self._text(act_el, "ObjectId", ns) or self._text(act_el, "Id", ns),
                name=self._text(act_el, "Name", ns),
                duration=dur_hours / 8.0 if dur_hours > 24 else dur_hours,  # heuristic: >24 likely hours
                start_date=self._parse_date(self._text(act_el, "StartDate", ns)
                            or self._text(act_el, "PlannedStartDate", ns)),
                finish_date=self._parse_date(self._text(act_el, "FinishDate", ns)
                             or self._text(act_el, "PlannedFinishDate", ns)),
                actual_start=self._parse_date(self._text(act_el, "ActualStartDate", ns)),
                actual_finish=self._parse_date(self._text(act_el, "ActualFinishDate", ns)),
                activity_type=act_type,
                status=status,
                percent_complete=self._float_text(act_el, "PhysicalPercentComplete", ns),
                wbs_id=self._text(act_el, "WBSObjectId", ns) or None,
                calendar_id=self._text(act_el, "CalendarObjectId", ns) or None,
                total_float=self._float_text(act_el, "TotalFloat", ns),
            )
            schedule.activities.append(activity)

        # Relationships
        for rel_el in self._findall(root, "Relationship", ns):
            rel_type_str = self._text(rel_el, "Type", ns)
            rel_type = RelationshipType.FS
            for rt in RelationshipType:
                if rt.name in rel_type_str:
                    rel_type = rt
                    break

            lag_hours = self._float_text(rel_el, "Lag", ns)

            schedule.relationships.append(Relationship(
                predecessor_id=self._text(rel_el, "PredecessorActivityObjectId", ns),
                successor_id=self._text(rel_el, "SuccessorActivityObjectId", ns),
                relationship_type=rel_type,
                lag_days=lag_hours / 8.0 if abs(lag_hours) > 24 else lag_hours,
            ))

        # Resources
        for res_el in self._findall(root, "Resource", ns):
            schedule.resources.append(Resource(
                resource_id=self._text(res_el, "ObjectId", ns),
                name=self._text(res_el, "Name", ns),
                resource_type=self._text(res_el, "ResourceType", ns, "Labor"),
            ))

        return schedule

    # ── Microsoft Project XML ────────────────────────────────────────────

    MSP_CONSTRAINT_MAP = {
        "0": ConstraintType.ASAP,
        "1": ConstraintType.ALAP,
        "2": ConstraintType.MSO,
        "3": ConstraintType.MFO,
        "4": ConstraintType.SNET,
        "5": ConstraintType.SNLT,
        "6": ConstraintType.FNET,
        "7": ConstraintType.FNLT,
    }

    MSP_REL_MAP = {
        "0": RelationshipType.FF,
        "1": RelationshipType.FS,
        "2": RelationshipType.SF,
        "3": RelationshipType.SS,
    }

    def _parse_msp_xml(self, root: ET.Element, ns: str, file_path: str) -> ScheduleData:
        """Parse Microsoft Project XML format."""
        schedule = ScheduleData()

        schedule.project = ProjectInfo(
            name=self._text(root, "Name", ns) or self._text(root, "Title", ns),
            start_date=self._parse_date(self._text(root, "StartDate", ns)),
            finish_date=self._parse_date(self._text(root, "FinishDate", ns)),
            data_date=self._parse_date(self._text(root, "StatusDate", ns)
                       or self._text(root, "LastSaved", ns)),
            source_format="msp_xml",
            source_file=str(file_path),
        )

        # Resources
        resources_el = self._find(root, "Resources", ns)
        resource_name_map = {}  # UID → name
        if resources_el is not None:
            for res_el in self._findall(resources_el, "Resource", ns):
                uid = self._text(res_el, "UID", ns)
                name = self._text(res_el, "Name", ns)
                if uid and name:
                    resource_name_map[uid] = name
                    schedule.resources.append(Resource(
                        resource_id=uid,
                        name=name,
                        resource_type=self._text(res_el, "Type", ns, "Labor"),
                    ))

        # Tasks
        tasks_el = self._find(root, "Tasks", ns)
        if tasks_el is None:
            raise ParseError("No <Tasks> element found in MS Project XML")

        uid_to_id = {}  # UID → activity_id mapping for relationships

        for task_el in self._findall(tasks_el, "Task", ns):
            uid = self._text(task_el, "UID", ns)
            if not uid or uid == "0":  # UID 0 is the project summary
                continue

            uid_to_id[uid] = uid

            # Duration — MSP uses ISO 8601 duration (PT8H0M0S = 8 hours)
            dur_str = self._text(task_el, "Duration", ns)
            duration = self._parse_msp_duration(dur_str)

            is_milestone = self._text(task_el, "Milestone", ns) == "1"
            is_summary = self._text(task_el, "Summary", ns) == "1"

            act_type = ActivityType.TASK
            if is_milestone:
                act_type = ActivityType.MILESTONE
            elif is_summary:
                act_type = ActivityType.SUMMARY

            pct = self._float_text(task_el, "PercentComplete", ns)
            status = ActivityStatus.NOT_STARTED
            if pct >= 100:
                status = ActivityStatus.COMPLETED
            elif pct > 0:
                status = ActivityStatus.IN_PROGRESS

            constraint_str = self._text(task_el, "ConstraintType", ns)
            constraint_type = self.MSP_CONSTRAINT_MAP.get(constraint_str, ConstraintType.NONE)

            activity = Activity(
                activity_id=uid,
                name=self._text(task_el, "Name", ns),
                duration=duration,
                original_duration=duration,
                start_date=self._parse_date(self._text(task_el, "Start", ns)),
                finish_date=self._parse_date(self._text(task_el, "Finish", ns)),
                actual_start=self._parse_date(self._text(task_el, "ActualStart", ns)),
                actual_finish=self._parse_date(self._text(task_el, "ActualFinish", ns)),
                baseline_start=self._parse_date(self._text(task_el, "BaselineStart", ns)),
                baseline_finish=self._parse_date(self._text(task_el, "BaselineFinish", ns)),
                activity_type=act_type,
                status=status,
                percent_complete=pct,
                constraint_type=constraint_type,
                constraint_date=self._parse_date(self._text(task_el, "ConstraintDate", ns)),
                total_float=self._float_text(task_el, "TotalSlack", ns) / 480 if self._float_text(task_el, "TotalSlack", ns) else None,
                free_float=self._float_text(task_el, "FreeSlack", ns) / 480 if self._float_text(task_el, "FreeSlack", ns) else None,
            )
            schedule.activities.append(activity)

            # Predecessor links are nested inside Task elements in MSP XML
            for pred_el in self._findall(task_el, "PredecessorLink", ns):
                pred_uid = self._text(pred_el, "PredecessorUID", ns)
                rel_type_str = self._text(pred_el, "Type", ns)
                rel_type = self.MSP_REL_MAP.get(rel_type_str, RelationshipType.FS)

                lag_minutes = self._float_text(pred_el, "LinkLag", ns)
                lag_days = lag_minutes / 4800 if lag_minutes else 0.0  # MSP: tenths of minutes, 480min/day

                schedule.relationships.append(Relationship(
                    predecessor_id=pred_uid,
                    successor_id=uid,
                    relationship_type=rel_type,
                    lag_days=lag_days,
                ))

        # Assignments
        assignments_el = self._find(root, "Assignments", ns)
        if assignments_el is not None:
            for asgn_el in self._findall(assignments_el, "Assignment", ns):
                task_uid = self._text(asgn_el, "TaskUID", ns)
                res_uid = self._text(asgn_el, "ResourceUID", ns)
                if task_uid and res_uid and task_uid in uid_to_id:
                    schedule.resource_assignments.append(ResourceAssignment(
                        activity_id=task_uid,
                        resource_id=res_uid,
                        planned_cost=self._float_text(asgn_el, "Cost", ns),
                        actual_cost=self._float_text(asgn_el, "ActualCost", ns),
                    ))

        return schedule

    def _parse_msp_duration(self, dur_str: str) -> float:
        """
        Parse MS Project ISO 8601 duration to days.
        Examples: 'PT8H0M0S' → 1.0, 'PT40H0M0S' → 5.0, 'PT0H0M0S' → 0.0
        """
        if not dur_str:
            return 0.0

        dur_str = dur_str.strip().upper()
        if not dur_str.startswith("PT"):
            try:
                return float(dur_str)
            except ValueError:
                return 0.0

        hours = 0.0
        minutes = 0.0

        import re
        h_match = re.search(r"(\d+(?:\.\d+)?)H", dur_str)
        m_match = re.search(r"(\d+(?:\.\d+)?)M", dur_str)

        if h_match:
            hours = float(h_match.group(1))
        if m_match:
            minutes = float(m_match.group(1))

        return (hours + minutes / 60.0) / 8.0  # convert to days
