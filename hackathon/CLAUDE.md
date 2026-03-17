# Arkhe — GitLab Duo Hackathon Context

## What this folder is

This folder contains the GitLab Duo Agent Platform submission for the **GitLab AI Hackathon** (deadline: March 25, 2026 at 2:00 PM ET).

It is completely separate from the Python/CLI app in the repo root. Nothing here runs Python code — it uses GitLab's built-in tools via the AI Gateway.

## Hackathon repo (GitLab)

- **URL:** `gitlab.com/gitlab-ai-hackathon/participants/35223940`
- **Owner:** nshreeyut1 (Shreeyut is the team representative)
- **Partner:** sync7319 (Om) — has member access
- **To deploy:** copy `flows/flow.yml` and `agents/agent.yml` to the hackathon repo via Web IDE

## Folder structure

```
hackathon/
  agents/
    agent.yml        — standalone single-agent definition (directly triggerable by @mention)
  flows/
    flow.yml         — multi-agent pipeline: Scanner → Analyst → Reporter
  AGENTS.md          — GitLab Duo agent context file (read by the platform at workspace root)
  CLAUDE.md          — this file
```

## Flow architecture

**3-agent sequential pipeline** — `scanner → analyst → reporter`

| Agent | Tools | Job |
|-------|-------|-----|
| `scanner` | get_project, get_merge_request, list_merge_request_diffs, list_repository_tree, find_files | Establish context, map repo structure, build priority read list |
| `analyst` | read_files, read_file, grep, gitlab_blob_search, get_commit_diff | Deep read 10–15 files, run 6-dimensional analysis (arch, deps, PR impact, OWASP, test coverage, quality) |
| `reporter` | create_merge_request_note, create_file_with_contents, create_commit | Post MR comment + commit docs/CODEBASE_MAP.md + docs/SECURITY_REPORT.md |

Data passes between agents via `context:component_name.final_answer` — each agent's output becomes the next agent's input.

## Confirmed working schema (flow.yml)

- Component type: `AgentComponent` uses `prompt_id` + plain string `toolset`
- Multi-agent inputs: `- from: "context:goal" as: "var"` (object syntax, NOT plain strings)
- Data passing: `- from: "context:scanner.final_answer" as: "scanner_output"`
- `ui_log_events`: only 2 — `on_agent_final_answer` + `on_tool_execution_success`
- `DeterministicStepComponent` is a third type (no LLM, calls one tool) — uses `tool_name` instead of `prompt_id`. Never use `tool_name` on an `AgentComponent`.
- CI validates on every push to the hackathon repo

## Prize strategy

| Prize | Requirement |
|-------|-------------|
| Grand Prize ($15,000) | Best overall |
| Most Impactful on GitLab & Google ($10,000) | GitLab + Google Cloud Run (Stage 3 hosting) |
| Most Impactful on GitLab & Anthropic ($10,000) | GitLab + Anthropic (already integrated as provider) |

A project can win one Grand Prize + one Category Prize. Eligible for both category prizes.

## Remaining to do

- [ ] Enable flow in the hackathon project settings
- [ ] Test — mention agent handle in an MR comment, verify analysis runs
- [ ] Record demo video (<3 min): trigger → analysis → reports committed + MR comment posted. Must be public on YouTube/Vimeo.
- [ ] Live demo URL required — judges test it free through April 17
- [ ] Submit on Devpost before **March 25, 2026 at 2:00 PM ET**

## Judging timeline

- Judging: March 30 – April 17, 2026
- Winners announced: ~April 22, 2026
