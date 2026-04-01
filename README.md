# Schedule Optimizer Agent

A comprehensive construction schedule analyzer that ingests schedules from any major format, runs industry-standard quality checks, and (coming soon) provides AI-powered analysis.

## Current Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1. Multi-format ingestion | ✅ Done | CSV, XER, XML parsers with unified data model |
| 2. Unified schedule model | ✅ Done | Rich data classes for activities, relationships, calendars, WBS, resources |
| 3. DCMA 14-point analysis | 🔲 Next | Industry-standard schedule quality checks |
| 4. Risk & forensics | 🔲 Planned | Monte Carlo, delay analysis, update comparison |
| 5. AI agent | 🔲 Planned | Natural language schedule Q&A |
| 6. Web app | 🔲 Planned | Dashboard, Gantt, chat interface |

## Supported Formats

| Format | Extension | Source | Status |
|--------|-----------|--------|--------|
| CSV/TSV | `.csv`, `.tsv` | Any (flexible column mapping) | ✅ |
| Primavera P6 XER | `.xer` | Oracle Primavera P6 | ✅ |
| P6 PMXML | `.xml` | Oracle Primavera P6 | ✅ |
| MS Project XML | `.xml` | Microsoft Project | ✅ |
| MS Project Binary | `.mpp` | Microsoft Project | 🔲 |
| Asta Powerproject | `.pp` | Asta | 🔲 |
| PDF Schedules | `.pdf` | Any | 🔲 |

## Quick Start

```bash
git clone https://github.com/MunzirH/schedule-optimizer-agent.git
cd schedule-optimizer-agent
pip install -r requirements.txt

# Parse any schedule file
python -c "
from parsers.registry import create_default_registry
registry = create_default_registry()
schedule = registry.parse('data/sample_schedule.xer')
print(schedule.summary())
"

# Run tests
python -m unittest discover -s tests -v
```

## Project Structure

```
schedule-optimizer-agent/
├── models/
│   └── schedule.py          # Unified data model (ScheduleData, Activity, etc.)
├── parsers/
│   ├── base.py              # Abstract base parser interface
│   ├── registry.py          # Auto-routes files to correct parser
│   ├── csv_parser.py        # CSV/TSV with flexible column mapping
│   ├── xer_parser.py        # Primavera P6 XER
│   └── xml_parser.py        # P6 PMXML + MS Project XML
├── optimization/
│   └── critical_path.py     # Critical path + float computation
├── agent/
│   └── analyzer.py          # Schedule issue analysis
├── tests/
│   ├── test_models.py
│   ├── test_csv_parser.py
│   ├── test_xer_parser.py
│   ├── test_xml_parser.py
│   └── test_registry.py
├── data/                    # Sample schedule files for testing
├── requirements.txt
└── README.md
```

## Architecture

Every parser converts its format into a unified `ScheduleData` object:

```
  .csv ──→ CSVScheduleParser ──┐
  .xer ──→ XERParser ──────────┼──→ ScheduleData ──→ Analysis Engine
  .xml ──→ XMLParser ──────────┘                      (DCMA 14, Critical Path, AI)
```

Adding a new format: subclass `BaseParser`, implement `parse()`, register it in `registry.py`.

## Running Tests

```bash
python -m unittest discover -s tests -v
```

80 tests covering all parsers, data model, and registry routing.
