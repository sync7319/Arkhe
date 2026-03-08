# Contributing to Arkhe

## First-time setup (5 minutes)

### 1. Install UV
UV is the only tool you need to install manually. It manages Python and all dependencies.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal after installing.

### 2. Clone and set up the environment

```bash
git clone <repo-url>
cd Arkhe
uv sync
```

That's it. UV reads `uv.lock` and creates an identical environment to everyone else on the team.
No manual pip installs. No version mismatches.

### 3. Set up your API keys

```bash
cp .env.example .env
```

Open `.env` and fill in your keys. You need at least one provider to run the tool:

| Provider | Get key at | Required? |
|----------|-----------|-----------|
| Groq | console.groq.com | Recommended (free tier) |
| Gemini | aistudio.google.com | Recommended (free tier) |
| Anthropic | console.anthropic.com | Optional (no free tier) |

Your `.env` is gitignored — it will never be committed.

### 4. Run it

```bash
uv run python main.py .
```

---

## Daily workflow

Always prefix commands with `uv run` — this uses the project venv automatically without needing to activate it.

```bash
uv run python main.py ./some-repo    # run Arkhe on a repo
uv run pytest                        # run tests
```

If a teammate adds a new dependency, pull and re-sync:

```bash
git pull
uv sync
```

---

## Branch strategy

```
main        — always deployable, protected
dev         — integration branch, merge feature branches here
feature/your-name/feature-name   — your work
```

**Never push directly to `main` or `dev`.** Open a PR and get a review.

---

## Adding a dependency

```bash
uv add <package-name>          # adds to pyproject.toml + updates uv.lock
uv add --dev <package-name>    # dev-only dependency (testing, tooling)
```

Commit both `pyproject.toml` and `uv.lock` together.
