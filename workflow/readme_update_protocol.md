# Skill: README Update Protocol

## Skill Name
`readme_update_protocol`

## Purpose

This skill defines the mandatory rules for maintaining and updating the project `README.md`.

The README file serves as the **only documentation file** for this project.
No additional standalone documentation files should be created.


---

## Core Principles

1. Every meaningful update must be reflected in `README.md`
2. README must be written in **Simplified Chinese**
3. Documentation must be detailed and structured
4. A clear update log (更新日志) must be maintained
5. No separate documentation files are allowed


---

## Trigger Condition

This skill is triggered whenever:

- A new feature is implemented
- A module is added
- An algorithm is updated
- A structural change occurs
- A statistical method is modified
- A new dependency is introduced
- Any important logic is changed

Minor formatting edits do not require full documentation updates.


---

## README Writing Rules

### 1. Language

- Must be written in **简体中文**
- No mixed-language documentation (unless technical terms require English)
- Explanations should be clear and complete


---

### 2. Required Sections

README should generally contain:

- 项目简介
- 数据说明
- 统计口径说明
- 核心分析方法概述
- NLP相关方法说明
- 运行方式（脚本如何执行）
- 性能边界说明
- 更新日志

Structure may evolve as the project grows.


---

### 3. Update Log (更新日志) Requirement

Each update must append a new entry under a dedicated section:

更新日志 YYYY-MM-DD
- 新增功能说明
- 修改内容说明
- 算法变更说明
- 结构调整说明


Rules:

- Use date-based entries
- Do not delete previous log records
- Keep chronological order (latest at top or bottom consistently)


---

### 4. No Additional Documentation Files

Strict rule:

- Do NOT create additional `.md` documentation files
- Do NOT create separate "docs/" directory
- Do NOT create explanatory text files
- All explanations must go into `README.md`

If clarification is needed, it must be appended to README.


---

## Documentation Philosophy

README should function as:

- Project introduction
- Technical specification summary
- Development record
- Analytical method description
- Evolution history

It must remain self-contained and comprehensive.


---

## Restrictions

- Do not overwrite large sections unless necessary
- Do not remove historical content without explicit instruction
- Do not fragment documentation across multiple files
- Do not summarize excessively — detailed explanation is preferred

README is the single source of truth for project documentation.
