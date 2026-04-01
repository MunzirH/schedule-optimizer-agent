# Schedule Optimizer Agent

AI-powered construction schedule analyzer that ingests schedules from any major format, runs industry-standard DCMA 14-point quality checks, performs risk analysis, and provides an intelligent AI agent that can reason about your schedule data.

Built for construction project controls professionals who work with Primavera P6, Microsoft Project, and CPM schedules daily.

## What It Does

Upload any schedule file and get:

- **DCMA 14-Point Scorecard** — pass/fail on all 14 industry-standard checks with drill-down on failures
- **Risk Analysis** — float distribution, BEI/CPLI performance indices, top risk activities, WBS risk breakdown
- **Critical Path Computation** — independent CPM engine that builds the critical path from scratch
- **AI Agent** — ask questions in plain English ("why does BGE-04 have negative float?", "what happens if we delay foundation work 2 weeks?")

## Quick Start

```bash
git clone https://github.com/MunzirH/schedule-optimizer-agent.git
cd schedule-optimizer-agent
pip install -r requirements.txt
pip install -e .

# Run analysis on any schedule file
python main.py your_schedule.xer

# Run with AI chat mode (requires free Gemini API key)
set GEMINI_API_KEY=your-key-here
python main.py your_schedule.xer --chat
```

Get a free Gemini API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

## Supported Formats

| Format | Extension | Source | Status |
|--------|-----------|--------|--------|
| Primavera P6 XER | `.xer` | Oracle Primavera P6 | ✅ |
| P6 PMXML | `.xml` | Oracle Primavera P6 | ✅ |
| MS Project XML | `.xml` | Microsoft Project | ✅ |
| CSV/TSV | `.csv`, `.tsv` | Any (flexible column mapping) | ✅ |
| MS Project Binary | `.mpp` | Microsoft Project | Planned |
| PDF Schedules | `.pdf` | Any | Planned |

## Features

### DCMA 14-Point Assessment
All 14 checks from DCMA-EA PAM 200.1:

1. Missing Predecessors (≤5%)
2. Missing Successors (≤5%)
3. Missing Logic (≤5%)
4. Leads / Negative Lag (0%)
5. Lags (≤5%)
6. Relationship Types (≥90% FS)
7. Hard Constraints (≤5%)
8. High Float >44 days (≤5%)
9. Negative Float (0%)
10. High Duration >44 days (≤5%)
11. Invalid Dates (0%)
12. Resources (≤5% unassigned)
13. Missed Tasks (≤5%)
14. Critical Path Test

### Risk Analysis
- Float distribution histogram
- BEI (Baseline Execution Index) and CPLI (Critical Path Length Index)
- Top risk activities ranked by severity
- Risk breakdown by WBS area
- Resource conflict detection
- Schedule comparison between two versions

### CPM Engine
- Forward/backward pass with lag support
- Critical path computation with virtual START/END nodes
- Driving path tracer — find exactly what drives any activity's dates
- What-if simulator — delay an activity, see the project impact
- Missing logic detector with relationship suggestions

### AI Agent
- Natural language questions about your schedule
- Auto-calls the right analysis tools based on your question
- Traces delay causes through predecessor chains
- Runs what-if scenarios on demand
- Generates prioritized improvement recommendations
- Supports Google Gemini (free) and Anthropic Claude APIs

#### Example Questions
```
- What are the top 5 risks on this project?
- Why does activity 4468322 have -157 days of float?
- What happens if we delay Steel Erection by 2 weeks?
- Summarize the DCMA results for the owner's meeting
- Which WBS areas need immediate attention?
- What should we fix first to recover the schedule?
- Show me all activities with negative float
- What's driving the dates for the project completion milestone?
```

## Project Structure

```
schedule-optimizer-agent/
├── models/
│   └── schedule.py              # Unified data model (ScheduleData, Activity, etc.)
├── parsers/
│   ├── base.py                  # Abstract base parser interface
│   ├── registry.py              # Auto-routes files to correct parser
│   ├── csv_parser.py            # CSV/TSV with flexible column mapping
│   ├── xer_parser.py            # Primavera P6 XER
│   └── xml_parser.py            # P6 PMXML + MS Project XML
├── optimization/
│   └── critical_path.py         # CPM engine, driving path, what-if analysis
├── agent/
│   ├── dcma_assessment.py       # DCMA 14-point checks
│   ├── risk_analysis.py         # Risk metrics, float analysis, BEI/CPLI
│   ├── tools.py                 # 11 queryable tool functions for the AI agent
│   ├── ai_agent.py              # AI agent with tool calling (Gemini/Claude)
│   └── chat.py                  # Interactive chat interface
├── tests/                       # 168 tests
├── data/                        # Sample schedule files
├── main.py                      # CLI entry point
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Architecture

```
  .csv ──→ CSVParser ──────┐
  .xer ──→ XERParser ──────┼──→ ScheduleData ──→ DCMA Assessment ──→ AI Agent
  .xml ──→ XMLParser ──────┘         │            Risk Analysis         │
                                     │            CPM Engine            │
                                     │                                  │
                                     └──→ 11 Tool Functions ───────────┘
                                           get_activity()
                                           find_activities()
                                           compute_critical_path()
                                           get_driving_path()
                                           simulate_delay()
                                           check_logic_health()
                                           get_recommendations()
                                           ...
```

## Running Tests

```bash
python -m unittest discover -s tests -v
```

168 tests covering parsers, data model, DCMA checks, risk analysis, CPM engine, tools, and agent.

## CLI Usage

```bash
# Basic analysis (prints overview, DCMA scorecard, risk report)
python main.py schedule.xer

# With AI chat mode (Gemini - free)
set GEMINI_API_KEY=your-key
python main.py schedule.xer --chat

# With Claude instead of Gemini
set ANTHROPIC_API_KEY=your-key
python main.py schedule.xer --chat --claude

# Works with any supported format
python main.py schedule.csv
python main.py schedule.xml
```

## Roadmap

- [x] Multi-format ingestion (CSV, XER, XML)
- [x] Unified schedule data model
- [x] DCMA 14-point assessment
- [x] Risk analysis with BEI/CPLI
- [x] CPM engine with driving path and what-if
- [x] AI agent with tool calling
- [ ] Web dashboard (FastAPI + React)
- [ ] Interactive Gantt chart with critical path highlighting
- [ ] Schedule comparison visualization
- [ ] PDF report export
- [ ] MPP file support

## License

MIT
