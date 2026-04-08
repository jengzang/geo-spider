# Skill: Code Commit Protocol

## Skill Name
`code_commit_protocol`

## Purpose

This skill defines the rules for committing code changes during development.

Whenever the user explicitly says **"提交"** (commit), the system must perform a `git commit` operation following the rules below.

This skill ensures clean version history, traceability, and structured development workflow.


---

## Trigger Condition

This skill is triggered only when:

- The user explicitly instructs to "提交"
- Or clearly indicates that the current stage of work should be committed

No automatic commit should occur without explicit instruction.


---

## Commit Rules

### 1. Always Use `git commit`

When triggered:

- Stage relevant changes
- Execute `git commit`
- Do NOT execute `git push`

Push operations are strictly manual and handled by the user.


---

### 2. Commit Message Requirements

Every commit message must:

- Clearly describe what was implemented or modified
- Be specific and informative
- Avoid vague descriptions such as:
  - "update"
  - "fix"
  - "modify"
  - "change"

Instead, use structured and meaningful messages.

Recommended structure:

[Module/Scope] Short summary
- Detailed explanation of what was added or modified
- Any algorithmic changes
- Any structural changes
- Any new files introduced


Clarity and precision are mandatory.


---

### 3. Commit Frequency Rules

- Every major change should result in a separate commit
- Logical units of work should not be merged into one commit
- Refactoring, feature addition, and structural updates should be separated when possible

Small iterative edits during active development may remain unstaged until a logical milestone is reached.


---

### 4. Explicit Restrictions

- Do NOT execute `git push`
- Do NOT amend previous commits unless explicitly instructed
- Do NOT squash commits
- Do NOT modify git history
- Do NOT use vague commit messages
- Do NOT commit database files or large binary files
- MUST use Chinese for the description of commit


---

## Design Principle

This skill enforces:

- Clean development history
- Traceable analytical evolution
- Professional repository hygiene
- Controlled deployment workflow

Push operations remain under manual control by the project owner.
