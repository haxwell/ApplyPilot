# Tailored Resume + PDF Rendering Pipeline

This document defines the current rendering architecture and the contract boundaries between:

1. LLM-tailored JSON
2. `ResumeRenderModel`
3. `template.prepare(...)`
4. `template.build_html(...)`
5. text-based fallback rendering

## Runtime Flow

Primary orchestration:

- `src/applypilot/scoring/tailor.py`
  - `tailor_resume(...)`
  - `run_tailoring(...)`
- `src/applypilot/scoring/pdf_render_model.py`
- `src/applypilot/scoring/pdf.py`
- `src/applypilot/scoring/pdf_templates/`

High-level flow for approved resumes:

1. LLM returns tailored JSON.
2. `tailor_resume(...)` validates JSON and stores accepted object in `report["tailored_json"]`.
3. `run_tailoring(...)` always writes:
   - `{prefix}.txt`
   - `{prefix}_JOB.txt`
   - `{prefix}_REPORT.json`
4. For approved statuses, PDF generation prefers structured rendering:
   - `build_render_model_from_tailored_json(...)`
   - `render_model_to_pdf(...)`
5. If structured rendering is unavailable or fails, PDF falls back to text parsing:
   - `convert_to_pdf(txt_path, ...)`

## Contract 1: Tailored JSON

Produced by `tailor_resume(...)` prompt contract in `src/applypilot/scoring/tailor.py`.

Expected shape:

```json
{
  "title": "Role Title",
  "summary": "4-6 tailored sentences.",
  "skills": {
    "Languages": "...",
    "Backend": "..."
  },
  "experience": [
    {
      "header": "Title at Company",
      "subtitle": "Tech | Dates",
      "bullets": ["..."],
      "compact_summary": "Optional single-sentence compact variant."
    }
  ],
  "projects": [
    {
      "header": "Project Name - Description",
      "subtitle": "Tech | Dates",
      "bullets": ["..."],
      "compact_summary": "Optional single-sentence compact variant."
    }
  ],
  "education": "..."
}
```

Notes:

- `compact_summary` is optional alternate content.
  - `default` template ignores it.
  - `compact` template uses it for Selected Experience entries when those entries are planned as compact.
- `tailor_resume(...)` puts accepted parsed JSON into `report["tailored_json"]` so downstream PDF generation can avoid reparsing text.

## Contract 2: Tailored JSON -> ResumeRenderModel

Owned by `build_render_model_from_tailored_json(data, profile)` in `src/applypilot/scoring/pdf_render_model.py`.

Mapping rules:

- Header/contact fields come from normalized profile `personal` data:
  - `name` <- `personal.full_name`
  - `contact` <- joined `email`, `phone`, `github_url`, `linkedin_url`
  - `location` <- `_build_location(personal)` using `city`, `province_state`, `country`, `postal_code` (with `location` as fallback)
- Content fields come from tailored JSON:
  - `title`, `summary`, `education`
  - `skills` -> `list[SkillSection]`
  - `experience`/`projects` -> `list[ResumeEntry]`

Defensive normalization:

- Missing/invalid optional fields become empty values.
- Bullets are normalized to strings.
- Entry compact summary is read from first available key:
  - `compact_summary`, `summary`, `short_summary`

## Contract 3: Template Prepare Phase

In `src/applypilot/scoring/pdf.py`:

```python
template = get_template(template_name)
prepared = template.prepare(model)
html = template.build_html(prepared)
```

Meaning:

- `ResumeRenderModel` represents shared available content.
- `template.prepare(...)` is template-owned planning/normalization seam.
- `template.build_html(...)` renders the prepared object.

Current template behavior:

- `default.prepare(model)` returns `ResumeRenderModel` unchanged.
- `compact.prepare(model)` performs heuristic layout planning in a template-specific prepared view:
  - keeps first `N` experience entries as detailed (`N` defaults to 4)
  - moves remaining entries into compact Selected Experience
  - preserves order
  - keeps all projects renderable
  - supports optional template-local override via `model.render_options["compact_max_detailed_experience"]`

## Contract 4: HTML Generation

Each template module must expose:

- `prepare(...)`
- `build_html(...) -> str`

Registry:

- `src/applypilot/scoring/pdf_templates/registry.py`
- Supported names today: `default`, `compact`

`resolve_pdf_template_name(profile, explicit_template=None)` resolves template selection order:

1. explicit argument
2. `profile["render"]["theme"]`
3. `profile["tailoring_config"]["pdf_template"]`
4. `"default"`

Unknown names are handled safely in `run_tailoring(...)`:

- warning logged
- fallback to `"default"`

## Contract 5: Text Fallback Path

Text fallback stays fully supported and is the resilience path:

1. `convert_to_pdf(text_path, ...)`
2. `parse_resume(text)` -> section dict
3. `build_render_model(parsed)` -> `ResumeRenderModel`
4. template `prepare(...)` -> `build_html(...)`
5. `render_pdf(...)` via Playwright

Fallback is used when:

- `report["tailored_json"]` is missing, or
- structured model rendering raises at runtime

This preserves artifact generation even if the structured path breaks.

## Page Count Measurement (Low-Level)

`src/applypilot/scoring/pdf.py` provides measurement helpers:

- `measure_html_page_count(html: str) -> int`
- `measure_model_page_count(model: ResumeRenderModel, template_name: str = "default") -> int`

These helpers render template HTML to a temporary PDF and return measured page count.

Current status:

- measurement only
- not used yet to make layout/compaction decisions
- intended as a future input for template-specific planning in `template.prepare(...)`
- future compact iterations may combine measurement with retry/tighter layout variants

## Artifacts and Status Behavior

`run_tailoring(...)` always persists text/report artifacts; PDF is produced only for:

- `approved`
- `approved_with_judge_warning`

DB write behavior remains unchanged:

- approved statuses update `tailored_resume_path` and `tailored_at`
- all statuses increment `tailor_attempts`
