# Schedule Optimizer Agent

An open-source AI agent for analyzing and optimizing project schedules.

It detects dependency issues, resource conflicts, and critical path risks — and recommends smarter task sequencing with clear, explainable outputs.

---

## 🚀 Overview

Project schedules are often complex, manually maintained, and prone to cascading delays.  
This project introduces an AI-driven approach to schedule analysis and optimization across multiple industries.

It supports common scheduling formats including:
- CSV / Excel
- Primavera P6 (XER files)

---

## 🧠 Key Features

### 🔍 Schedule Analysis
- Detect missing or broken dependencies  
- Identify critical path and zero-float tasks  
- Highlight bottlenecks and schedule risks  

### ⚙️ Optimization
- Recommend task resequencing  
- Suggest parallelization opportunities  
- Improve resource allocation  
- Reduce overall project duration  

### 💬 Explainability
- Generate clear, human-readable insights  
- Understand *why* changes are recommended  
- Make better decisions with context  

---

## 📂 Supported Formats

### ✅ CSV / Excel
Standard tabular schedule format with:
- Task ID
- Start / End dates
- Duration
- Predecessors
- Resources

### 🏗️ Primavera P6 (XER)
- Parse XER files into structured task data  
- Extract:
  - Activities
  - Relationships
  - Resources
- Enable enterprise-scale schedule analysis  

---

## 📊 Example

### Input (CSV)

```csv
task_id,task_name,start_date,end_date,duration,predecessors,resource
1,Design,2026-01-01,2026-01-05,5,,Engineer A
2,Review,2026-01-06,2026-01-08,3,1,Engineer A
3,Build,2026-01-06,2026-01-12,7,1,Engineer B
```

### Output

- Critical Path: Task 1 → Task 3  
- Resource Conflict: Engineer A assigned to overlapping tasks  
- Recommendations:
  - Delay Task 2 or reassign resource  
  - Parallelize tasks where possible  
  - Reduce downstream delays  

---

## 🏗️ Project Structure

```
schedule-optimizer-agent/
├── agent/              # Core agent logic
├── optimization/       # Algorithms (CPM, leveling, etc.)
├── parsers/            # CSV, Excel, XER parsers
├── data/               # Sample datasets
├── app/                # UI / API (Streamlit, FastAPI)
├── notebooks/          # Demos and experiments
├── tests/              # Unit tests
```

---

## ⚡ Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/schedule-optimizer-agent.git
cd schedule-optimizer-agent
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the app
```bash
python app/main.py
```

---

## 🛠️ Tech Stack

- Python  
- pandas / numpy  
- OR-Tools (planned)  
- Streamlit (UI)  
- NetworkX (dependency graphs)  

---

## 🌍 Use Cases

### Construction & Infrastructure
- Optimize activity sequencing  
- Protect key milestones  
- Manage shared crews  

### Transportation Projects
- Analyze large program schedules  
- Reduce cascading delays  
- Improve planning reliability  

### Software Development
- Identify blocked tasks  
- Improve sprint planning  
- Balance workloads  

---

## 🤝 Contributing

We welcome contributions from:

- Data scientists  
- Software engineers  
- Project managers  
- Students and researchers  

### Ways to contribute:
- Add support for new file formats  
- Improve optimization algorithms  
- Build visualizations (Gantt charts, dashboards)  
- Enhance documentation  
- Add integrations (Primavera, MS Project, etc.)  

Check issues labeled `good first issue` or `help wanted` to get started.

---

## 🔮 Roadmap

- [ ] Critical Path Method (CPM)  
- [ ] Resource leveling  
- [ ] Monte Carlo schedule simulation  
- [ ] Full XER parser with relationships & calendars  
- [ ] LLM-powered explanation engine  
- [ ] What-if scenario analysis  
- [ ] Integration with MS Project (XML)  

---

## 📌 Vision

To build a community-driven AI platform that transforms how project schedules are analyzed, optimized, and managed across industries.
