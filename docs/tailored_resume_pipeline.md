# Tailored Resume Generation Pipeline

This document describes how ApplyPilot generates a tailored resume artifact from source profile/resume data and a target job description.

## Scope and Entry Point

Primary runtime path:

- `src/applypilot/scoring/tailor.py`
  - `run_tailoring(...)`
  - `tailor_resume(...)`
  - `assemble_resume_text(...)`

CLI entry:

- `applypilot run tailor`
- `applypilot tailor`

## Inputs

`run_tailoring(...)` loads:

1. Normalized profile data via `load_profile()` (from `~/.applypilot/resume.json` and settings/profile sources).
2. Deterministic base resume text via `load_resume_text()`.
3. Target jobs from DB (`pending_tailor` stage, filtered by score/limit or `target_url`).

Input provenance note:

- `load_resume_text()` typically derives base resume text from canonical `~/.applypilot/resume.json`.
- If canonical JSON is unavailable, legacy `~/.applypilot/resume.txt` is used as fallback.

For each target job, the tailoring request uses:

- job title
- company/site
- location
- job description text (truncated to 6000 chars in prompt payload)

## Generation Model Contract

`tailor_resume(...)` asks the LLM for **JSON**, not final printable text.

Expected JSON shape includes:

- `title`
- `summary`
- `skills`
- `experience` (list)
- `projects` (list)
- `education`

Important current policy:

- The LLM step is quality and relevance focused.
- It must preserve full profile-company coverage in `experience`.
- Length fitting is not delegated to the LLM as a page-budget task.

## Retry and Validation Loop

`tailor_resume(...)` runs attempts (`max_retries + 1`) with a fresh chat each attempt.

Per attempt:

1. Parse JSON from model output.
2. Strip disallowed watchlist skills from generated `skills`.
3. Run `validate_json_fields(...)`.
4. Enforce missing-company hard check via `_missing_profile_companies_in_generated_experience(...)`.
   - If any profile company is missing, this is a hard validation error.
5. Add warning when no renderable projects exist.

If validation fails:

- retry until attempts exhausted
- on final failed attempt: still assemble TXT from the last JSON and mark `failed_validation`

If validation passes:

- assemble deterministic resume text
- optionally run LLM judge (`strict`/`normal`; skipped in `lenient`)

## Deterministic Assembly and Compaction

`assemble_resume_text(...)` turns validated JSON into final text sections:

- header/contact (profile-injected)
- `SUMMARY`
- `TECHNICAL SKILLS`
- `EXPERIENCE`
- optional `SELECTED EXPERIENCE`
- optional `PROJECTS`
- `EDUCATION`

JSON-to-text rendering path:

- `assemble_resume_text(...)` prepares section data and experience compaction state.
- `_render_resume_lines(...)` emits the actual ordered plain-text lines.
- Those lines are joined into the final `{prefix}.txt` artifact.

Behavior details:

1. Experience starts from LLM-provided entries (no silent reinsertion of omitted roles).
2. For matched profile roles, thin entries are enriched from profile highlights before compaction.
3. A line budget is computed from profile tailoring config:
   - `tailoring_config.global_rules.max_resume_pages`
   - `tailoring_config.global_rules.formatting.lines_per_page`
4. If over budget, oldest roles are moved from `EXPERIENCE` to `SELECTED EXPERIENCE`.
5. If still over budget, `SELECTED EXPERIENCE` is further compacted (fewer bullets/subtitle removal).

This is where length enforcement occurs.

## Artifact Outputs

For each processed job, `run_tailoring(...)` writes to `~/.applypilot/tailored_resumes`:

- `{prefix}.txt` (assembled resume text)
- `{prefix}_JOB.txt` (job snapshot)
- `{prefix}_REPORT.json` (attempt/validator/judge report)
- `{prefix}.pdf` (only for approved statuses)

PDF generation path:

- `src/applypilot/scoring/pdf.py`
  - `convert_to_pdf(...)`
  - `parse_resume(...)`
  - `build_html(...)`
  - `render_pdf(...)` (Playwright Chromium)

Approved statuses for PDF conversion:

- `approved`
- `approved_with_judge_warning`

## Database Effects

On success (`approved` or `approved_with_judge_warning`):

- store `tailored_resume_path`
- store `tailored_at`
- increment `tailor_attempts`

On non-success:

- increment `tailor_attempts`
- do not update `tailored_resume_path`

## Validation Modes

`validation_mode` affects strictness:

- `strict`: strongest rejection behavior (plus judge required)
- `normal`: balanced default
- `lenient`: lighter checks; judge skipped

See:

- `src/applypilot/scoring/validator.py`
- `src/applypilot/scoring/tailor.py` (`tailor_resume`)
