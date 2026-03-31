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
