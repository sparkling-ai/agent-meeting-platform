# AGENTS.md — Project Rules

Every AI agent (Codex, Claude Code, Chopper, etc.) working on this repo MUST follow these rules.

## Change Workflow

**For every code change (feature, fix, refactor):**

1. **Make the change** — write clean, tested code
2. **Run tests** — `cd backend && source .venv/bin/activate && python -m pytest tests/ -v`
3. **Update CHANGELOG.md** — add entry under a `[Unreleased]` section at the top (don't bump version yet)
   - Use categories: `### Added`, `### Fixed`, `### Changed`, `### Removed`
   - One bullet per change, concise but specific
4. **Update README.md** if the change affects user-facing features, API, or setup instructions
5. **Commit** with a clear conventional-commit message: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
6. **Push** to remote

### When to bump version

When a logical "release" is ready (a sprint completed, a milestone hit), rename `[Unreleased]` to the version number + date, following the existing format in CHANGELOG.md.

## Testing Rules

- **Never push without running tests first.** If tests fail, fix before committing.
- **New features MUST include tests.** No exceptions.
- **Bug fixes SHOULD include a regression test** that would have caught the bug.

## CHANGELOG Conventions

- Keep entries at **high feature level** — not every line change, but every meaningful user/developer-facing change
- Use plain language — a new developer should understand what changed from reading it
- Group by version with dates, using Keep a Changelog format
- The changelog serves as our **retrospective history** — it tells the story of the project

## Code Style

- Python 3.12+, type hints on public APIs
- `uv` for dependency management, never global pip
- Follow existing patterns in the codebase
- Backend: FastAPI async patterns, SQLAlchemy 2.0 style
- SDK: Event-driven, clean public API

## Meeting Records

After every meeting (demo, retrospective, planning, etc.):
1. Save the transcript to `meetings/YYYY-MM-DD-<type>-<description>.md`
2. Update the index table in `meetings/README.md`
3. Commit with: `docs: meeting YYYY-MM-DD <type>`

## Project Structure

- `/backend` — FastAPI backend (Python)
- `/frontend` — Next.js dashboard (TypeScript)
- `/sdk` — Python SDK (`agent_meeting` package)
- `/docs` — Design docs and architecture
- `/meetings` — Meeting transcripts and decisions (indexed in meetings/README.md)
- `/team` — Team member profiles (used as personas for meetings)
- `PLAN.md` — Implementation roadmap with phase tracking
- `CHANGELOG.md` — Version history (this file is always up to date)
