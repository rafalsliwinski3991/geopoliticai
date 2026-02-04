# geopoliticai

## Documentation

# Multi-Agent Political Analysis System  
**Architecture & Functional Specification**

## 1. Purpose

The application is a multi-agent political analysis platform designed to:

1. Collect up-to-date real-world political information  
2. Analyze it from multiple ideological frameworks  
3. Rigorously fact-check all claims  
4. Produce a neutral, balanced, evidence-based synthesis  

It is intended for analysis of:
- Current political events  
- Public policy  
- Elections  
- Geopolitical conflicts  
- Government decisions  
- Political speeches and trends  

The system must avoid advocacy and maintain academic neutrality.

---

## 2. High-Level Architecture

The system consists of:

- **7 Specialized LLM Agents**
- **1 Supervisor / Orchestrator Agent**
- **Sequential Execution Pipeline**
- **Structured Output Formatter**

The Supervisor controls execution order and information flow between agents.

---

## 3. Agent Roles & Responsibilities

### Agent 1 — Web Searcher (OSINT Layer)
**Function:**  
- Retrieve current, verifiable information.  
- Gather timelines, statistics, key actors, official statements.  
- Provide multiple reputable sources (news, academic, government, think tanks).  
- No ideological interpretation.  

**Output:**  
- Factual background  
- Source list with credibility notes  

---

### Agent 2 — Leftist Political Analyst
**Function:**  
- Interpret issues through:  
  - Social justice  
  - Class analysis  
  - Labor rights  
  - Inequality  
  - Climate and welfare policy  
  - Power structures and corporate influence  

---

### Agent 3 — Centrist Policy Analyst
**Function:**  
- Analyze through:  
  - Institutional stability  
  - Policy tradeoffs  
  - Economic feasibility  
  - Bipartisan compromise  
  - Risk management  
  - Governance constraints  

---

### Agent 4 — Right-Wing Political Analyst
**Function:**  
- Analyze through:  
  - Free markets  
  - National sovereignty  
  - Constitutional limits  
  - Security  
  - Cultural continuity  
  - Limited government  

---

### Agent 5 — Fact Checker
**Function:**  
- Cross-verify claims made by Agents 2–4 against Agent 1’s sources.  
- Classify each claim as:  
  - TRUE  
  - PARTIALLY TRUE  
  - MISLEADING  
  - FALSE  
- Provide explanations and evidence.  

---

### Agent 6 — Summarizer & Methodological Judge
**Function:**  
- Compare ideological arguments.  
- Evaluate evidence quality.  
- Identify:  
  - Consensus points  
  - Disagreements  

