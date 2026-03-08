# Contributing to Arkhe

Everything you need to know to work on this project — setup, running it, and Git workflow.

---

## First-time setup

### 1. Install UV (the only thing you install manually)

**Mac/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installing. UV manages Python and all dependencies — you do not need to install Python separately.

### 2. Clone and set up

```bash
git clone https://github.com/sync7319/Arkhe.git
cd Arkhe
uv sync
```

`uv sync` reads the `uv.lock` file and creates an identical environment to everyone else on the team — same packages, same versions, regardless of your OS. No manual pip installs, no version mismatches.

### 3. Set up your API keys

```bash
cp .env.example .env
```

Open `.env` and fill in at least one provider. Groq and Gemini both have free tiers — no credit card needed.

| Provider | Get your key at | Free tier? |
|----------|----------------|------------|
| Groq | console.groq.com | Yes |
| Gemini | aistudio.google.com | Yes |
| Anthropic | console.anthropic.com | No |

Your `.env` is in `.gitignore` — it will never be committed or shared.

### 4. Run it

```bash
uv run python main.py .
```

This runs Arkhe on the Arkhe repo itself (self-test). Output goes to `docs/`.

---

## Running commands day-to-day

Always use `uv run` — it uses the project venv automatically, no activation needed.

```bash
uv run python main.py ./path/to-any-repo    # map a repo
uv run python main.py .                     # map Arkhe itself (self-test)
uv run pytest                               # run tests
```

If someone adds a new dependency, after pulling just run:
```bash
uv sync
```

---

## Adding a dependency

```bash
uv add package-name              # production dependency
uv add --dev package-name        # dev only (tests, tooling)
```

This updates both `pyproject.toml` and `uv.lock`. Commit both files together.

---

## Git Workflow

### Branch structure

```
main  ← official, always working, never push here directly
  └── dev  ← shared work-in-progress, all features land here first
        ├── feature/shreeyut/...   ← nshreeyut's work
        └── feature/sync/...       ← sync7319's work
```

### Starting any piece of work

Always branch off `dev`, never off `main`:

```bash
git checkout dev                              # switch to dev
git pull                                      # get the latest
git checkout -b feature/your-name/task-name   # create your sandbox
```

### While working

```bash
git add filename.py                           # stage what you changed
git commit -m "fix: cache llm clients"        # save a checkpoint
```

Commit as often as you want. Nothing is shared until you push.

### Push your branch and open a PR

```bash
git push -u origin feature/your-name/task-name
```

Then go to github.com/sync7319/Arkhe — you'll see a yellow banner saying "Compare & pull request". Click it, make sure the target branch is set to **`dev`** (not main), and submit.

The other person reviews it, approves it, and merges it on GitHub.

### After your PR is merged

```bash
git checkout dev
git pull
git branch -d feature/your-name/task-name    # clean up
```

Then start fresh with a new branch for your next task.

### If dev moved forward while you were working

```bash
git checkout dev && git pull
git checkout feature/your-name/task-name
git merge dev                                # bring in the latest changes
```

Resolve any conflicts, then keep going.

### Releasing to main

When `dev` is stable, open a PR from **`dev` → `main`** on GitHub. Both people review and approve, then merge. That's a release.

---

## Code review rules

- You do not merge your own PR — the other person approves and merges it
- Target is always `dev`, never `main`
- If you're reviewing: click "Files changed", leave comments on specific lines if needed, then "Approve"

---

## Commit message format

```
feat: add watch command for live reloading
fix: make llm_call_async actually use async clients
refactor: replace recursive AST walk with iterative stack
docs: update contributing guide
chore: add pyproject.toml and uv lockfile
test: add batch grouping unit tests
```

| Prefix | When to use |
|--------|------------|
| `feat:` | new feature |
| `fix:` | bug fix |
| `refactor:` | restructuring without behaviour change |
| `docs:` | documentation only |
| `chore:` | setup, config, dependencies |
| `test:` | adding or fixing tests |

---

## Quick reference

| What | Command |
|------|---------|
| What branch am I on? | `git status` |
| See all branches | `git branch -a` |
| Switch branch | `git checkout branch-name` |
| Get latest | `git pull` |
| See local changes | `git diff` |
| Stage a file | `git add filename` |
| Commit | `git commit -m "message"` |
| Push branch | `git push -u origin branch-name` |
| Delete local branch | `git branch -d branch-name` |
| Sync dependencies | `uv sync` |
| Add a package | `uv add package-name` |
