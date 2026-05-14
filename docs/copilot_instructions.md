# Copilot instructions — workspace facts & SOP (general)

Purpose
- A short, practical reference for the Copilot agent to work efficiently in this repository.
- Keep it general: environment facts, debugging SOP, testing and validation rules, and communication guidelines.

Checklist (what I'll follow when investigating any new issue)
- Reproduce the problem locally (fast minimal test) or confirm logs/inputs if reproduction not possible.
- Locate the relevant code & config files from repository structure.
- Try a minimal fix or diagnostic (unit test, curl, small script) that isolates root cause.
- Run repo tests or a targeted unit test after change; iterate until green or blocked.
- Document findings in `docs/` and propose a persistent configuration or code change if needed.

Quick facts (environment & repo pointers)
- Repo layout: `src/`, `scripts/`, `docs/`, `config/`, `tests/`.
- Python virtualenv: `.venv` (activate with `source .venv/bin/activate`). Use `python -m pip` to install packages consistently.
- App dir and settings: many runtime files live under `~/.applypilot/` (see `src/applypilot/config.py` for `APP_DIR`, `DB_PATH`, `SEARCH_CONFIG_PATH`).
- Important files to check first:
  - `src/applypilot/config.py` — path constants and loading logic
  - `src/applypilot/database.py` — DB schema and helpers
  - `src/applypilot/discovery/` — discovery sources (job boards, ATS scrapers)
  - `src/applypilot/apply/` — applying/launcher code (auto-apply behavior)
  - `src/applypilot/wizard/` — init/wizard flows

General debugging SOP (step-by-step)
1. Clarify the user-observed symptoms and expected behavior. If the user provided logs, open them and note timestamps and error messages.
2. Reproduce locally with the smallest test that demonstrates the issue: a single curl, a focused unit test, or a short Python script using the repo modules. Avoid long pipeline runs initially.
3. Trace the code path: use code search (grep/semantic search) to locate the functions involved. Open those files and find where inputs are validated and where external calls happen.
4. Run targeted diagnostics:
   - For HTTP/API failures: craft a curl or Python requests test with the same headers/body and capture response headers, status, and body.
   - For browser/JS issues: use Playwright headful to capture network requests and console logs; prefer headful (visible) mode for interactive debugging.
   - For DB issues: query the SQLite DB (`~/.applypilot/applypilot.db`) with `sqlite3` to inspect rows and state.
5. Propose minimal, reversible changes. Make a small edit, run relevant unit tests, and validate manually if necessary.
6. Document the change in docs (under `docs/`) and add tests or config overrides as appropriate.

Playwright & browser debugging notes
- Install Playwright in the active venv: `python -m pip install playwright` and `python -m playwright install chromium`.
- Prefer `headful` mode during capture so a human can interact. Inject a small init script to intercept `fetch` and `XMLHttpRequest` to record POST payloads and headers.
- If a site returns non-JSON or WAF/Cloudflare challenges, consider running with a realistic User-Agent, `Accept` headers, and/or using a proxy.

How to run quick diagnostics (cheat-sheet)
- Run single-URL POST test:

```bash
curl -i -X POST "<url>" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  --data '{"limit": 10, "offset": 0, "searchText": "engineer"}'
```

- Inspect DB state:

```bash
sqlite3 ~/.applypilot/applypilot.db "SELECT url, title, site, applied_at FROM jobs ORDER BY discovered_at DESC LIMIT 20;"
```

- Capture browser requests with Playwright (headful): create a small script that injects a capturing init script, then interact and dump `window.__captures`.

Communication & behavior guidelines (how to talk with the user)
- Be concise and focused. Start with one sentence describing what you'll do next.
- Provide a short checklist of steps you're taking and a quick status update before running any long tasks.
- Ask a single clarifying question only if it is essential to proceed. Prefer to act autonomously when the repository contains enough context.
- When reporting results, include commands you ran and exact error messages. Offer 1–2 next actions and recommend the least-risky one.

Code edit rules
- Make the smallest, testable change. Group related edits in one commit and include a brief test or example run.
- Prefer feature toggles or config overrides for per-tenant/workaround behavior rather than hardcoding exceptions.
- Add unit tests for new behavior and run the test suite (or relevant subset) before finalizing.

Testing & validation
- Run targeted tests first: `pytest tests/discovery/test_workday*.py` or similar.
- If you change runtime behavior, run `pytest -q` for the repository if quick; otherwise run a focused test file.
- After edits, run `applypilot run --dry-run` or a short pipeline stage to smoke-test end-to-end behavior.

Documentation SOP
- For each non-trivial debugging session, create or update a document under `docs/` with:
  - Short summary of the issue and symptoms
  - Reproduction steps (commands) and expected vs actual output
  - Diagnostics performed and their results
  - Fix or mitigation applied
  - Next steps (if any)

File storage conventions
- Short-term findings or overrides: `~/.applypilot/` (user-specific state)
- Repo-tracked, persistent employer-specific overrides or templates: `config/` or `config/employers.yaml` (document where to store and how to name keys)
- Long-term documentation and instructions: `docs/` (one issue per document, named clearly)

Next steps I can take now (pick one)
- Create `scripts/capture_workday.py` (headful Playwright capture script) and a README note in `docs/` — quick and low-risk.
- Implement `workday_request_template` support in `src/applypilot/discovery/workday.py` and add a minimal unit test — more invasive but useful for per-tenant fixes.

Which would you like me to do next? (capture script / implement template)
