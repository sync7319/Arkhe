# Arkhe — GitLab Duo Hackathon Roadmap

## Hackathon Phase (due March 25, 2026)

**Status: 3-agent multi-agent flow — CI passing ✅**

- [x] `flows/flow.yml` — valid GitLab Duo flow YAML, CI passing
- [x] `agents/agent.yml` — Arkhe agent with full 5-phase system prompt and tool list
- [x] Upgrade to 3-agent multi-agent flow: Scanner → Analyst → Reporter
  - **Scanner** — get_project, get_merge_request, list_merge_request_diffs, list_repository_tree, find_files
  - **Analyst** — read_files, grep, gitlab_blob_search, get_commit_diff — 6-dimensional analysis
  - **Reporter** — create_merge_request_note, create_file_with_contents, create_commit
- [x] Create git tag `v1.0.0` on hackathon repo to publish to GitLab catalog
- [ ] Enable flow in the project settings
- [ ] Test end-to-end: mention agent in MR → analysis runs → reports committed + MR comment posted
- [ ] Record demo video (<3 min): trigger → analysis → MR comment posted + docs committed
- [ ] Submit on Devpost before **March 25, 2026 at 2:00 PM ET**

## Prize Strategy

| Prize | Amount | Requirement |
|-------|--------|-------------|
| Grand Prize | $15,000 | Best overall |
| Most Impactful on GitLab & Google | $10,000 | GitLab + Google Cloud Run (Stage 3 hosting) |
| Most Impactful on GitLab & Anthropic | $10,000 | GitLab + Anthropic (already integrated as provider) |

A project can win one Grand Prize + one Category Prize. Eligible for both category prizes.

## Post-Hackathon Phase

- [ ] Connect Duo flow to Cloud Run backend — Duo flow triggers Cloud Run for deep analysis, posts full results back to GitLab
- [ ] Web server toggle — "Quick mode" (Duo flow, instant, GitLab's AI) vs "Full mode" (Cloud Run, full pipeline, all 7 outputs)
- [ ] GitLab OAuth on web server — user connects once, we auto-register webhooks on selected repos
- [ ] GitLab webhook receiver — `POST /gitlab-webhook`, parse `X-Gitlab-Event` MR payload, run full Python pipeline, post results via GitLab Notes API
- [ ] Commit full `docs/` output to repo via GitLab API after full pipeline run
- [ ] Maintain and improve the Duo flow as GitLab platform capabilities expand

## Judging Timeline

- Deadline: March 25, 2026 at 2:00 PM ET
- Judging: March 30 – April 17, 2026
- Winners announced: ~April 22, 2026
