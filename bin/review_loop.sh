#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bin/review_loop.sh --url <job_url> --output-name <name> [options]

Runs applypilot tailor, then creates a zip containing:
  - ~/.applypilot/tailored_resumes/<output-name>.pdf
  - ~/.applypilot/tailored_resumes/<output-name>_REPORT.json

Options:
  --url <job_url>            Required. Job URL for applypilot tailor.
  --output-name <name>       Required. Base output name for generated artifacts.
  --validation <mode>        Optional. Validation mode (default: normal).
  --force                    Optional. Pass --force to applypilot tailor (default: on).
  --no-force                 Optional. Do not pass --force.
  --zip-name <file.zip>      Optional. Zip filename (default: <name>_review_<timestamp>.zip).
  --tailor-bin <command>     Optional. Tailor command (default: applypilot).
  -h, --help                 Show this help.

Examples:
  bin/review_loop.sh \
    --url "https://job-boards.greenhouse.io/affirm/jobs/7511993003" \
    --output-name affirm_sr_engr

  bin/review_loop.sh \
    --url "https://example.com/job/123" \
    --output-name my_test \
    --validation strict \
    --zip-name my_test_review.zip \
    --no-force
EOF
}

URL=""
OUTPUT_NAME=""
VALIDATION_MODE="normal"
FORCE_FLAG=1
ZIP_NAME=""
TAILOR_BIN="applypilot"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      URL="${2:-}"
      shift 2
      ;;
    --output-name)
      OUTPUT_NAME="${2:-}"
      shift 2
      ;;
    --validation)
      VALIDATION_MODE="${2:-}"
      shift 2
      ;;
    --force)
      FORCE_FLAG=1
      shift
      ;;
    --no-force)
      FORCE_FLAG=0
      shift
      ;;
    --zip-name)
      ZIP_NAME="${2:-}"
      shift 2
      ;;
    --tailor-bin)
      TAILOR_BIN="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$URL" ]]; then
  echo "Error: --url is required." >&2
  usage
  exit 2
fi

if [[ -z "$OUTPUT_NAME" ]]; then
  echo "Error: --output-name is required." >&2
  usage
  exit 2
fi

TAILORED_DIR="${HOME}/.applypilot/tailored_resumes"
mkdir -p "$TAILORED_DIR"

PDF_PATH="${TAILORED_DIR}/${OUTPUT_NAME}.pdf"
REPORT_PATH="${TAILORED_DIR}/${OUTPUT_NAME}_REPORT.json"

if [[ -z "$ZIP_NAME" ]]; then
  TS="$(date +%Y%m%d_%H%M%S)"
  ZIP_NAME="${OUTPUT_NAME}_review_${TS}.zip"
fi
ZIP_PATH="${TAILORED_DIR}/${ZIP_NAME}"

echo "Running tailor for: ${URL}"
CMD=( "$TAILOR_BIN" tailor --url "$URL" --validation "$VALIDATION_MODE" --output-name "$OUTPUT_NAME" )
if [[ "$FORCE_FLAG" -eq 1 ]]; then
  CMD+=( --force )
fi
"${CMD[@]}"

if [[ ! -f "$PDF_PATH" ]]; then
  echo "Error: Expected PDF not found: ${PDF_PATH}" >&2
  exit 1
fi

if [[ ! -f "$REPORT_PATH" ]]; then
  echo "Error: Expected report not found: ${REPORT_PATH}" >&2
  exit 1
fi

rm -f "$ZIP_PATH"
(
  cd "$TAILORED_DIR"
  zip -q "$ZIP_PATH" "$(basename "$PDF_PATH")" "$(basename "$REPORT_PATH")"
)

echo "Review bundle created:"
echo "  ${ZIP_PATH}"
