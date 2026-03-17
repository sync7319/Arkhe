# Arkhe — GitLab Duo Agent Context

Arkhe is an autonomous codebase intelligence agent built on the GitLab Duo Agent Platform. Triggered by a mention or MR assignment, it runs a three-agent pipeline that reads the repository using GitLab's built-in tools, analyzes architecture and security, and posts a full intelligence report as an MR comment — then commits generated docs back to the repo.

No installation. No API keys. No webhooks. Runs entirely on GitLab's compute using GitLab's AI Gateway.

---

## How to trigger

- Mention the Arkhe agent handle in any MR or issue comment
- Assign Arkhe as a reviewer on a merge request

---

## What Arkhe does

Arkhe runs three agents in sequence. Each agent receives the previous agent's output as its input.

### Agent 1 — Scanner
**Tools:** `get_project`, `get_merge_request`, `list_merge_request_diffs`, `list_repository_tree`, `find_files`

Establishes full context before any files are read:
- Calls `get_project` to identify the language, default branch, and project description
- In MR mode: calls `get_merge_request` + `list_merge_request_diffs` to get the exact set of changed files and their line-level diffs
- Calls `list_repository_tree` to map the repo structure — entry points, core modules, test directories, config layers, API surfaces
- Builds a prioritized read list and import grep patterns for the Analyst

### Agent 2 — Analyst
**Tools:** `read_files`, `read_file`, `grep`, `gitlab_blob_search`, `get_commit_diff`

Reads source files and runs six-dimensional analysis:
- Batches file reads using `read_files` — 2–3 calls covering 10–15 files
- Uses `grep` and `gitlab_blob_search` to trace which files import changed modules (blast radius)
- **A. Architecture** — what the system does, architectural pattern, data flow, load-bearing modules
- **B. Dependencies** — import graph, circular deps, risky external packages
- **C. PR Impact** — per-file change type, importers, risk score (🟢/🟡/🔴), overall risk
- **D. Security** — OWASP Top 10 static scan (A01–A09) on code actually read
- **E. Test Coverage** — changed files with no corresponding test file, untested public functions
- **F. Code Quality** — oversized functions, deep nesting, TODOs in changed code, missing docstrings

### Agent 3 — Reporter
**Tools:** `create_merge_request_note`, `create_file_with_contents`, `create_commit`

Posts the report and commits docs:
- Calls `create_merge_request_note` once with the full structured intelligence report
- Calls `create_file_with_contents` + `create_commit` to commit two files to the default branch:
  - `docs/CODEBASE_MAP.md` — architecture narrative, core modules table, dependency map, gotchas
  - `docs/SECURITY_REPORT.md` — OWASP findings with severity, file, and description

---

## What Arkhe cannot do in this context

These are constraints of the GitLab Duo Agent Platform — not limitations of Arkhe's design:

- **No code execution** — analysis is static only; no running tests, linters, or build tools
- **No external HTTP calls** — cannot call GitHub, npm registry, CVE databases, or any external API
- **No file system writes outside GitLab** — all output goes through `create_file_with_contents` + `create_commit`
- **No persistent memory** — each trigger starts fresh; no history across MRs
- **No parallel agents** — pipeline is sequential: Scanner → Analyst → Reporter
- **GitLab's AI model only** — uses whatever model GitLab's AI Gateway provides; no BYOK

---

## Output

| Output | Where |
|--------|-------|
| Intelligence report | MR comment (posted by Reporter agent) |
| `docs/CODEBASE_MAP.md` | Committed to default branch |
| `docs/SECURITY_REPORT.md` | Committed to default branch |

---

## Flow definition

See `flows/flow.yml` for the full YAML definition.
See `agents/agent.yml` for the standalone single-agent definition (directly triggerable).
