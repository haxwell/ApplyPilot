# Workday CXS discovery failures: HTTP 406 / 422

This document records the investigation, reproducible tests, and recommended mitigations for the Workday CXS issues encountered while running ApplyPilot discovery against corporate Workday career sites (example: `kustomer.wd1.myworkdayjobs.com`). It is intended as a short, actionable reference for developers and operators so we don't re-learn the same debugging steps.

Summary
- Observed symptoms:
  - GET to some Workday tenant home pages returns HTTP 406 ("Not Acceptable").
  - Direct POSTs to the tenant CXS jobs endpoint (*/wday/cxs/{tenant}/{site_id}/jobs*) succeed (reachable) but return HTTP 422 with a small JSON error object: {"errorCode":"HTTP_422",...}.
  - Playwright headless captures did not always see the JS-issued CXS POSTs; a headful browser that the user interacts with is the reliable way to capture the exact request payload.
- Root cause (high level): per-tenant variability in Workday deployments. Two unknowns per-tenant:
  1. `site_id` — the path component used by that tenant's CXS API.
  2. request shape / required headers / session tokens — the JSON payload and any required cookies/headers can differ by tenant.
- Practical consequence: the generic CXS request we send (in `_workday_search_request()`) will work for many tenants but will produce 422/401/JSON errors for others. Some tenants also present host-level rejections (HTTP 406) for certain requests or user-agent/format combinations.

Files & code locations
- Workday helper and discovery: `src/applypilot/discovery/workday.py`
  - `_workday_search_request()` — constructs and sends the POST payload to the CXS endpoint
  - `_candidate_site_ids()` and `_try_discover_site_id()` — logic that guesses alternate `site_id` values
  - `run_workday_discovery()` / `search_employer()` — orchestrates per-employer queries and marks first-page failures as `WorkdayEmployerFailure` (quarantine semantics in that run)
- Where tests were run: interactive Playwright captures and curl requests from the developer environment.

---

New notes: noisy wdN probes vs correct discovery

What we tried (wdN brute-force)
- I probed tenant hostnames by brute-forcing region subdomains: `https://{tenant}.wd{1..20}.myworkdayjobs.com/`.
- Results were noisy: many hosts returned `000` (no response) or `406` for both valid and invalid tenants.

Why that approach is noisy and brittle
- 406 is often a generic front-end response from the Workday CDN/WAF for unknown or misrouted hosts. It does not reliably mean "this tenant doesn't exist" — it can also indicate content-negotiation or host-routing behavior that returns the same page for many inputs.
- `000` is usually a network/timeout/HEAD-rejection artifact from our probe (curl HEAD/GET with follow-location). Some Workday tenants simply don't respond to HEAD in a way curl expects, or they close/redirect in a way our quick probe doesn't follow.
- The tenant token (the leftmost subdomain label, e.g. `kustomer`) is frequently the real source of mismatch: the canonical host a browser uses may be a different label or a custom domain (for example: `company-careers.myworkdayjobs.com` or a routed vanity domain), not the raw `tenant` string in our registry.

Correct approach (what to do instead)
1. Use the registry-configured `base_url` first
   - Check `src/applypilot/config/employers.yaml` for a `base_url` entry for that employer. This registry often contains the canonical host that worked in prior discovery runs.
   - Test that `base_url` directly (GET + CXS POST) rather than guessing other wdN values.

2. If the registry entry fails or is missing, find the canonical host from the company's public career pages
   - Inspect the company website (homepage or `/careers`) and look for `workday` or `myworkdayjobs` links. Those links usually reveal the exact tenant host the browser uses.
   - Alternatively, inspect external job postings or apply links (LinkedIn, Indeed) which often point to the ATS/ATS-host and reveal the canonical host.

3. Capture the browser's real POST payload for tenant-specific payload shape
   - Use DevTools Network → filter `wday/cxs` while interacting with the careers page, or run a headful Playwright capture (visible Chromium) that intercepts `fetch` / XHR and records the request JSON and headers.
   - Use that exact payload/headers as an override (see "Per-tenant override" below) or implement a Playwright fallback if the tenant requires JS-auth/session flows.

4. If the CXS endpoint still returns 422 but GET works, the host is correct; the issue is payload/headers/session. Capture and adapt the payload.

What 406 vs 422 typically means (short)
- 406 Not Acceptable (front-end): the edge/CDN/workday front-end refused to serve a representation for this request or host — often a sign that the host/path is not correct or the request lacks proper Accept headers.
- 422 Unprocessable Entity (CXS): the API accepted the connection but the request payload or parameters are wrong for that tenant — usually a payload shape mismatch, missing required fields, or tenant-specific validation.

Playwright capture recipe (headful)
- Install Playwright in the active venv:

```bash
source .venv/bin/activate
python -m pip install playwright
python -m playwright install chromium
```

- Run a headful capture script (opens visible Chromium). Interact with the page (search / click job cards) and the script will dump any `/wday/cxs/*/*/jobs` request bodies and headers. Example script is in `docs/` in the capture recipe. Prefer headful capture because many tenants only issue the API calls after real user interactions.

Per-tenant override (recommended short-term fix)
- Add a `workday_request_template` entry to `config/employers.yaml` or to a dedicated `~/.applypilot/employers.overrides.yaml` that provides the exact JSON structure for that tenant. Example:

```yaml
kustomer:
  base_url: https://the.correct.host
  tenant: kustomer
  site_id: Kustomer
  workday_request_template: |
    {"appliedFacets": {}, "limit": {{limit}}, "offset": {{offset}}, "searchText": "{{search_text}}", "extraField": "value"}
```

- Implement template rendering (safely) inside `_workday_search_request()` so tenants can override the outgoing JSON even when the generic request fails.

Fallback: Playwright scraping
- If the tenant requires interactive session flows, complex JS, or cookies that cannot be reproduced easily via raw HTTP, use a Playwright-based scraper to drive the site and extract `apply_url` and job data directly. This is heavier but robust and avoids fragile per-tenant payload hacks.

Quick diagnostics / commands (cheat-sheet)
- Test registry base_url GET:

```bash
curl -i -L -H "User-Agent: Mozilla/5.0" "https://<tenant>.wd3.myworkdayjobs.com/" | sed -n '1,80p'
```

- Test the CXS POST for a configured employer:

```bash
curl -i -X POST "https://<tenant>.wd3.myworkdayjobs.com/wday/cxs/<tenant>/<site_id>/jobs" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -H 'User-Agent: Mozilla/5.0' \
  --data '{"appliedFacets": {}, "limit": 10, "offset": 0, "searchText": "engineer"}' | sed -n '1,200p'
```

- Run the Workday discovery for a small subset (what we used during debugging):

```bash
PYTHONPATH=src python - <<'PY'
import json
from applypilot.discovery.workday import run_workday_discovery, load_employers
all_emps = load_employers()
keys = ['enbridge','bmo','kustomer']
res = run_workday_discovery(employers={k: all_emps[k] for k in keys if k in all_emps}, workers=1)
print(json.dumps(res, indent=2))
PY
```

Key findings from the `kustomer` investigation
- `curl` POST to the CXS endpoint returned HTTP 422 + JSON error object — the endpoint is present but rejected the generic body.
- Simple GETs sometimes returned HTTP 406; a bogus tenant host produced the same 406, indicating the front-end rejects certain hosts/requests with a generic 406 page.
- Adding cookies and common headers (Origin/Referer/X-Requested-With) did not change the 422 result for Kustomer.
- Playwright headful capture is the most reliable way to observe the tenant's actual JS payload and headers.

Short-term mitigations (recommended)
1. Per-tenant payload capture + config override
   - After capturing the browser's POST payload for a failing tenant, add a small per-employer override in `config/employers.yaml` or in a new file under `~/.applypilot/` that the scraper reads. Example keys:

```yaml
kustomer:
  base_url: https://kustomer.wd1.myworkdayjobs.com
  tenant: kustomer
  site_id: Kustomer
  workday_request_template: |
    {"appliedFacets": {}, "limit": {{limit}}, "offset": {{offset}}, "searchText": "{{search_text}}", "extraField": "value"}
```

   - Implement `workday_request_template` support in `_workday_search_request()` so tenants can override the payload shape.

2. Headless -> headful / browser fallback
   - If CXS returns 4xx/422 or the tenant presents challenges, fall back to a Playwright-based scrape for that employer (`smartextract` style). This is heavier but robust (handles cookies, JS, WAFs).

3. Proxy option to bypass IP-based WAFs
   - If a tenant blocks based on IP or shows HTML challenge pages, configure a proxy in `~/.applypilot/searches.yaml` (`defaults.proxy`) and pass it to `run_workday_discovery()` so the `setup_proxy()` path is used.

4. Graceful quarantine + retries
   - Keep per-run quarantine behavior (skip employer for that crawl) but add a short backoff and retry policy for transient 422/406 vs permanent 401.

Long-term improvements
- Add per-employer `workday_request_template` support and a CLI helper to capture + persist the browser payload into `config/employers.yaml` or `~/.applypilot/employers.overrides.yaml`.
- Add a Workday fallback path that runs Playwright for employers that repeatedly return 4xx/422 and store the discovered `external_path`/`apply_url` reliably.
- Add automated tests (unit + integration) that simulate the Workday responses (422/401/JSON) and validate the fallback and override behavior.

Developer notes / quick references
- Code to inspect:
  - `src/applypilot/discovery/workday.py` — Workday scraping logic and site_id discovery
  - `src/applypilot/discovery/smartextract.py` — Playwright-based scraping framework (fallback target)
- Useful curl snippets are included above; DevTools capture is fastest for exact payloads.

If you want, next I will:
- Add a script under `scripts/capture_workday.py` in this repo (copy of the Playwright capture used during debugging) so teammates can run it easily, and
- Implement `workday_request_template` override reading in `workday._workday_search_request()` and a small test harness.

Choose next action:
- I will create `scripts/capture_workday.py` in the repo and a short README note, or
- I will implement `workday_request_template` support in `workday.py` and add a minimal unit test.

Which would you like me to do next? (capture script / implement template)
