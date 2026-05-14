# ApplyPilot Files in Use

This document lists the paths ApplyPilot **writes to at runtime**. Config files shipped in the repo (like `src/applypilot/config/*.yaml`) are treated as read‑only.

All paths below are rooted under a single user data directory:

- Default: `~/.applypilot`
- Overridable via env var: `APPLYPILOT_DIR`

## Core persistent data

- `applypilot.db`
  - Path: `<APP_DIR>/applypilot.db`
  - Purpose: Main SQLite database (jobs, enrichment status, scores, apply status, etc.).

- `profile.json`
  - Path: `<APP_DIR>/profile.json`
  - Purpose: User profile, contact info, preferences, and settings.

- `resume.json`
  - Path: `<APP_DIR>/resume.json`
  - Purpose: Primary structured resume used by LLM stages.

- `resume.txt`
  - Path: `<APP_DIR>/resume.txt`
  - Purpose: Legacy plain‑text resume fallback when `resume.json` is absent.

- `resume.pdf`
  - Path: `<APP_DIR>/resume.pdf`
  - Purpose: Exported resume PDF (used when PDF stage runs and when sites require upload).

- `searches.yaml`
  - Path: `<APP_DIR>/searches.yaml`
  - Purpose: User search configuration (queries, locations, boards). Written by `applypilot init` and by the user.

- `.env`
  - Path: `<APP_DIR>/.env`
  - Purpose: Environment variables (API keys, model overrides, etc.). Typically edited by the user or tooling, not by the discovery pipeline itself.

## Generated artifacts

- Tailored resumes
  - Directory: `<APP_DIR>/tailored_resumes/`
  - Contents: Per‑job tailored resume text and PDFs, created by the "tailor" + "pdf" stages.

- Cover letters
  - Directory: `<APP_DIR>/cover_letters/`
  - Contents: Per‑job cover letter text and PDFs, created by the "cover" + "pdf" stages.

- Tracking artifacts
  - Directory: `<APP_DIR>/tracking/`
  - Contents: Email tracking / classification artifacts (e.g., matched replies, status breakdown).

- Logs
  - Directory: `<APP_DIR>/logs/`
  - Contents:
    - Pipeline logs from `applypilot run ...`
    - Auto‑apply logs (e.g., `claude_*.txt` from apply workers)
    - Other operational logs and debug output.

## Browser and worker state

These directories isolate Chrome and apply workers; they can be created/updated during runs:

- Chrome workers
  - Directory: `<APP_DIR>/chrome-workers/`

- Apply workers
  - Directory: `<APP_DIR>/apply-workers/`

- Chrome sessions
  - Directory: `<APP_DIR>/chrome-sessions/`

## Optional uploaded files

- Extra documents
  - Directory: `<APP_DIR>/files/`
  - Contents: Optional user documents referenced in profile/config (ID scans, certs, photos, etc.) when provided.

## Repo-shipped config (read‑only at runtime)

These live in the repo and are **not** written by ApplyPilot at runtime:

- `src/applypilot/config/employers.yaml`   – Workday employer registry
- `src/applypilot/config/sites.yaml`       – Direct career sites and scraping config (your fork‑specific)
- `src/applypilot/config/sites.example.yaml` – Example sites config mirroring upstream
- `src/applypilot/config/greenhouse.yaml`  – Greenhouse scraping config
- `src/applypilot/config/searches.example.yaml` – Example search config template

User customizations to these live in the repo (via git) rather than being written by the running application.
