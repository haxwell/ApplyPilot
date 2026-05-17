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

Production default template:

- `professional_compact` (measurement-aware)

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
  - `classic` template ignores it.
  - `default` aliases `professional_compact`, so it may use `compact_summary` for selected entries during measurement-aware planning.
  - `compact` template uses it for Selected Experience entries when those entries are planned as compact.
- Education can carry optional JSON Resume extension metadata per entry:
  - `education[i].x-applypilot.degree_completed` (boolean)
  - `education[i].x-applypilot.education_display` (string)
  - When `education_display` is provided, education rendering prefers it.
  - When `degree_completed=false` and no display override is provided, rendering uses coursework phrasing (for example, `Computer Science coursework`) rather than degree-major wording.
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
- Template render options are copied into `ResumeRenderModel.render_options` with priority:
  1. `profile["tailoring_config"]["global_rules"]["max_resume_pages"]` -> mapped to `render_options["max_resume_pages"]`
  2. `profile["tailoring_config"]["render_options"]`
  3. `profile["tailoring_config"]["pdf_render_options"]`
  4. `profile["render"]["options"]` (highest)
  Missing/non-dict values are ignored.

Defensive normalization:

- Missing/invalid optional fields become empty values.
- Bullets are normalized to strings.
- Entry compact summary is read from first available key:
  - `compact_summary`, `summary`, `short_summary`

## Contract 3: Template Prepare Phase

In `src/applypilot/scoring/pdf.py`:

```python
template = get_template(template_name)
if hasattr(template, "prepare_with_measurement"):
    prepared = template.prepare_with_measurement(model, measure_html_page_count)
else:
    prepared = template.prepare(model)
html = template.build_html(prepared)
```

Meaning:

- `ResumeRenderModel` represents shared available content.
- `ResumeRenderModel.render_options` carries optional template-tuning inputs from profile config.
- `template.prepare(...)` is template-owned planning/normalization seam.
- `template.build_html(...)` renders the prepared object.

Current template behavior:

- `professional_compact.prepare_with_measurement(...)` is the production measurement-aware template:
  - starts with maximum detailed experience (or explicit hard cap from render options)
  - measures full rendered resume HTML page count
  - progressively moves later entries into Earlier Experience (Selected) only as needed to fit page target
  - always keeps at least one detailed `EXPERIENCE` entry when experience exists
  - interprets fractional page targets as physical-page allowance (`ceil`)
  - preserves order and keeps projects/summary/skills/education renderable
  - uses a roomier polished two-page visual style so page measurement/compaction has meaningful effect
  - allows detailed experience entries to flow across physical pages (instead of forcing full-entry page keeps), reducing large blank gaps
  - resolves page target in this order:
    1. template-local override (if the template defines one)
    2. `model.render_options["max_resume_pages"]`
    3. template default `2.5` (when neither value is present/valid)
  - supports explicit renderer modes in its prepared view (summary/skills/projects/experience/education/certifications).
  - applies an idempotent staged compaction ladder when over page budget:
    - each stage performs one deterministic transition
    - full HTML is measured after each transition
    - planner stops immediately on first fit
    - detailed-experience count reduction is the final fallback stage
- `classic.prepare(model)` is the baseline/simple renderer:
  - no measurement-aware planning
  - all experience entries remain detailed
- `compact.prepare(model)` is a simple heuristic alternate:
  - keeps first `N` experience entries as detailed (`N` defaults to 4)
  - moves remaining entries into compact Selected Experience
  - preserves order
  - keeps all projects renderable
  - supports optional template-local override via `model.render_options["compact_max_detailed_experience"]`
  - template owns the final planning decision; `render_options` are hints/inputs, not upstream compaction logic
- `default` is a compatibility alias to `professional_compact`.

### Page Budget Policy

ApplyPilot page-budget policy should be:

1. User-level global default in profile settings:
   - `tailoring_config.global_rules.max_resume_pages`
2. Optional template-local override owned by the template implementation/config (not user profile).
3. Hard default fallback when neither is provided.

Design intent:
- Keep user config global and simple.
- Allow template-specific behavior only when a template explicitly needs a different page budget.
- Avoid requiring users to set per-template page limits in `~/.applypilot/profile.json`.

## Contract 4: HTML Generation

Templates are loaded dynamically by reference through:

- `src/applypilot/scoring/pdf_templates/registry.py`
- `get_template(template_ref)`

Built-in template references resolve to modules under:

- `applypilot.scoring.pdf_templates.<template_ref>`

Examples:

- `default`
- `compact`
- `professional_compact`
- `classic`

Required template contract:

- `build_html(prepared) -> str`
- and either:
  - `prepare(model)`
  - or `prepare_with_measurement(model, measure_html_page_count)`

The orchestrating PDF code only calls the template contract and does not hardcode
template-specific layout behavior.
When both hooks are present, orchestration prefers `prepare_with_measurement(...)`.

Optional template metadata (not required yet):

- `TEMPLATE_INFO` (dict)
- `TEMPLATE_CAPABILITIES` (list/tuple of strings)
- `TEMPLATE_INPUT_PREFERENCES` (dict)
- `TEMPLATE_REQUIREMENTS` (dict)
- `TEMPLATE_OPTIONS` (dict)

Registry behavior:

- metadata fields are read/validated when present
- missing metadata is allowed
- invalid metadata types raise template load validation errors
- template input preferences are surfaced for reporting/introspection via
  `get_template_input_preferences(template_ref)`
- current usage is informational (for reports/debugging), not behavior-changing
- future work may use these preferences to inform upstream content preparation
- tailoring now persists a `content_preparation_context` object in reports that
  includes selected template + input preferences; this is a seam for future
  prompt/content-preparation decisions without hardcoding template assumptions

`resolve_pdf_template_name(profile, explicit_template=None)` resolves template selection order:

1. explicit argument
2. `profile["render"]["theme"]`
3. `profile["tailoring_config"]["pdf_template"]`
4. `"professional_compact"`

Recommended explicit config value:

- `"pdf_template": "professional_compact"`

Unknown names are handled safely in `run_tailoring(...)`:

- warning logged
- fallback to `"professional_compact"`

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
- `measure_model_page_count(model: ResumeRenderModel, template_name: str = "professional_compact") -> int`

These helpers render template HTML to a temporary PDF and return measured page count.

Current status:

- available as generic helper in `pdf.py`
- used by measurement-aware templates such as `professional_compact`
- not pushed upstream into `tailor.py` or `assemble_resume_text(...)`

## Artifacts and Status Behavior

`run_tailoring(...)` always persists text/report artifacts; PDF is produced only for:

- `approved`
- `approved_with_judge_warning`

DB write behavior remains unchanged:

- approved statuses update `tailored_resume_path` and `tailored_at`
- all statuses increment `tailor_attempts`

## Render Planning Telemetry in `_REPORT.json`

When structured rendering is used, tailoring reports now include a `pdf_render_planning` block
to make template planning decisions observable.

Typical fields:

- `template_used`
- `page_target_config`
- `allowed_physical_pages`
- `measured_pages_final`
- `planning_attempts` (candidate detailed-role counts + measured pages + fit flag)
- `planning_operations` (ordered compaction operations with `step`, `from`, `to`, `measured_pages`, `fit`)
- `render_modes_final`
- `detailed_bullet_cap_final`
- `detailed_roles`
- `earlier_selected_roles`

If structured rendering fails and text fallback is used, `pdf_render_planning` includes
`render_path: "text_fallback"` plus a reason.
