#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

usage() {
  cat <<'EOF'
LiteParse PoC runner for scanservjs addon (manual CLI path).

Usage:
  liteparse-test.sh --input <file-or-dir> [options]

Required:
  --input <path>                  Input file or directory

Optional:
  --output-dir <path>             PoC root output dir (default: /share/scanservjs-rag/liteparse-poc)
  --config <path>                 LiteParse config JSON (default: ../liteparse.config.json if present)
  --baseline-dir <path>           Baseline chunk directory for A/B comparison
  --chunk-size <n>                Chunk size in chars (default: 900)
  --chunk-overlap <n>             Chunk overlap in chars (default: 180)
  --min-chunk-size <n>            Minimum chunk chars (default: 120)
  --max-files <n>                 Limit number of files (default: all)
  --source <label>                Source label in chunks (default: scanservjs-manual-cli)
  --parser <name>                 Parser label in chunks (default: liteparse-cli)
  --liteparse-bin <cmd>           LiteParse binary (default: lit)
  --ocr-language <lang>           Override OCR language
  --ocr-server-url <url>          Override OCR server URL
  --target-pages <ranges>         Parse page ranges (e.g. 1-3,8)
  --max-pages <n>                 Max pages per document
  --dpi <n>                       Render DPI override
  --num-workers <n>               OCR workers override
  --no-ocr                        Disable OCR
  --quiet                         Suppress per-file progress logs
  -h, --help                      Show help

Output:
  /share/scanservjs-rag/liteparse-poc/runs/<timestamp>/
    raw/        LiteParse export JSON per document
    chunks/     Chunk JSONL per document
    reports/    run-summary.json, fallback-report.json, ab-summary.json, run-summary.md
    logs/       Command logs
EOF
}

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

fail() {
  log "ERROR: $*"
  exit 1
}

require_command() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "Command not found: ${cmd}"
}

assert_integer() {
  local label="$1"
  local value="$2"
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    fail "${label} must be an integer: ${value}"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADDON_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

INPUT_PATH=""
OUTPUT_DIR="/share/scanservjs-rag/liteparse-poc"
CONFIG_PATH=""
BASELINE_DIR=""
CHUNK_SIZE="900"
CHUNK_OVERLAP="180"
MIN_CHUNK_SIZE="120"
MAX_FILES="0"
SOURCE_LABEL="scanservjs-manual-cli"
PARSER_LABEL="liteparse-cli"
LITEPARSE_BIN="${LITEPARSE_BIN:-lit}"
OCR_LANGUAGE=""
OCR_SERVER_URL=""
TARGET_PAGES=""
MAX_PAGES=""
DPI=""
NUM_WORKERS=""
NO_OCR="false"
QUIET="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      INPUT_PATH="${2:-}"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --config)
      CONFIG_PATH="${2:-}"
      shift 2
      ;;
    --baseline-dir)
      BASELINE_DIR="${2:-}"
      shift 2
      ;;
    --chunk-size)
      CHUNK_SIZE="${2:-}"
      shift 2
      ;;
    --chunk-overlap)
      CHUNK_OVERLAP="${2:-}"
      shift 2
      ;;
    --min-chunk-size)
      MIN_CHUNK_SIZE="${2:-}"
      shift 2
      ;;
    --max-files)
      MAX_FILES="${2:-}"
      shift 2
      ;;
    --source)
      SOURCE_LABEL="${2:-}"
      shift 2
      ;;
    --parser)
      PARSER_LABEL="${2:-}"
      shift 2
      ;;
    --liteparse-bin)
      LITEPARSE_BIN="${2:-}"
      shift 2
      ;;
    --ocr-language)
      OCR_LANGUAGE="${2:-}"
      shift 2
      ;;
    --ocr-server-url)
      OCR_SERVER_URL="${2:-}"
      shift 2
      ;;
    --target-pages)
      TARGET_PAGES="${2:-}"
      shift 2
      ;;
    --max-pages)
      MAX_PAGES="${2:-}"
      shift 2
      ;;
    --dpi)
      DPI="${2:-}"
      shift 2
      ;;
    --num-workers)
      NUM_WORKERS="${2:-}"
      shift 2
      ;;
    --no-ocr)
      NO_OCR="true"
      shift
      ;;
    --quiet)
      QUIET="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

[[ -n "$INPUT_PATH" ]] || fail "--input is required"
[[ -e "$INPUT_PATH" ]] || fail "Input path does not exist: ${INPUT_PATH}"

assert_integer "--chunk-size" "$CHUNK_SIZE"
assert_integer "--chunk-overlap" "$CHUNK_OVERLAP"
assert_integer "--min-chunk-size" "$MIN_CHUNK_SIZE"
assert_integer "--max-files" "$MAX_FILES"

if (( CHUNK_OVERLAP >= CHUNK_SIZE )); then
  fail "--chunk-overlap must be smaller than --chunk-size"
fi

if [[ -z "$CONFIG_PATH" ]]; then
  DEFAULT_CONFIG="${ADDON_DIR}/liteparse.config.json"
  if [[ -f "$DEFAULT_CONFIG" ]]; then
    CONFIG_PATH="$DEFAULT_CONFIG"
  fi
fi

if [[ -n "$CONFIG_PATH" && ! -f "$CONFIG_PATH" ]]; then
  fail "Config file not found: ${CONFIG_PATH}"
fi

if [[ -n "$BASELINE_DIR" && ! -d "$BASELINE_DIR" ]]; then
  fail "Baseline directory not found: ${BASELINE_DIR}"
fi

EXPORT_SCRIPT="${SCRIPT_DIR}/liteparse-export.js"
CHUNKIFY_SCRIPT="${SCRIPT_DIR}/liteparse-chunkify.js"
[[ -f "$EXPORT_SCRIPT" ]] || fail "Missing script: ${EXPORT_SCRIPT}"
[[ -f "$CHUNKIFY_SCRIPT" ]] || fail "Missing script: ${CHUNKIFY_SCRIPT}"

require_command "node"
require_command "$LITEPARSE_BIN"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="${OUTPUT_DIR}/runs/${RUN_ID}"
RAW_DIR="${RUN_DIR}/raw"
CHUNK_DIR="${RUN_DIR}/chunks"
REPORT_DIR="${RUN_DIR}/reports"
LOG_DIR="${RUN_DIR}/logs"

mkdir -p "$RAW_DIR" "$CHUNK_DIR" "$REPORT_DIR" "$LOG_DIR"
printf '%s\n' "$RUN_DIR" > "${OUTPUT_DIR}/LATEST_RUN"

declare -a FILES=()
if [[ -f "$INPUT_PATH" ]]; then
  FILES+=("$(realpath "$INPUT_PATH")")
else
  while IFS= read -r -d '' candidate; do
    FILES+=("$(realpath "$candidate")")
  done < <(
    find "$INPUT_PATH" -type f \
      \( -iname '*.pdf' -o -iname '*.doc' -o -iname '*.docx' -o -iname '*.docm' -o -iname '*.odt' -o -iname '*.rtf' \
      -o -iname '*.ppt' -o -iname '*.pptx' -o -iname '*.pptm' -o -iname '*.odp' \
      -o -iname '*.xls' -o -iname '*.xlsx' -o -iname '*.xlsm' -o -iname '*.ods' -o -iname '*.csv' -o -iname '*.tsv' \
      -o -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.tif' -o -iname '*.tiff' \
      -o -iname '*.gif' -o -iname '*.bmp' -o -iname '*.webp' -o -iname '*.svg' \) \
      -print0 | sort -z
  )
fi

if (( ${#FILES[@]} == 0 )); then
  fail "No supported files found at: ${INPUT_PATH}"
fi

if (( MAX_FILES > 0 && ${#FILES[@]} > MAX_FILES )); then
  FILES=("${FILES[@]:0:MAX_FILES}")
fi

DOCS_TSV="${RUN_DIR}/documents.tsv"
{
  printf 'index\tfilePath\tstatus\tdocId\texportJson\tchunkJsonl\texportLog\tchunkLog\n'
} > "$DOCS_TSV"

log "LiteParse PoC run started: ${RUN_ID}"
log "Input files: ${#FILES[@]}"
log "Output root: ${RUN_DIR}"

index=0
for file_path in "${FILES[@]}"; do
  index=$((index + 1))
  base_name="$(basename "$file_path")"
  safe_name="$(printf '%s' "$base_name" | tr ' ' '_' | tr -cd 'A-Za-z0-9._-')"
  if [[ -z "$safe_name" ]]; then
    safe_name="document_${index}"
  fi
  idx="$(printf '%03d' "$index")"
  export_json="${RAW_DIR}/${idx}_${safe_name}.export.json"
  chunk_jsonl="${CHUNK_DIR}/${idx}_${safe_name}.chunks.jsonl"
  export_log="${LOG_DIR}/${idx}_${safe_name}.export.log"
  chunk_log="${LOG_DIR}/${idx}_${safe_name}.chunkify.log"

  if [[ "$QUIET" != "true" ]]; then
    log "Processing ${index}/${#FILES[@]}: ${file_path}"
  fi

  export_cmd=(
    node "$EXPORT_SCRIPT"
    --input-file "$file_path"
    --output-file "$export_json"
    --source "$SOURCE_LABEL"
    --parser "$PARSER_LABEL"
    --liteparse-bin "$LITEPARSE_BIN"
    --quiet
  )
  if [[ -n "$CONFIG_PATH" ]]; then
    export_cmd+=(--config "$CONFIG_PATH")
  fi
  if [[ -n "$OCR_LANGUAGE" ]]; then
    export_cmd+=(--ocr-language "$OCR_LANGUAGE")
  fi
  if [[ -n "$OCR_SERVER_URL" ]]; then
    export_cmd+=(--ocr-server-url "$OCR_SERVER_URL")
  fi
  if [[ -n "$TARGET_PAGES" ]]; then
    export_cmd+=(--target-pages "$TARGET_PAGES")
  fi
  if [[ -n "$MAX_PAGES" ]]; then
    export_cmd+=(--max-pages "$MAX_PAGES")
  fi
  if [[ -n "$DPI" ]]; then
    export_cmd+=(--dpi "$DPI")
  fi
  if [[ -n "$NUM_WORKERS" ]]; then
    export_cmd+=(--num-workers "$NUM_WORKERS")
  fi
  if [[ "$NO_OCR" == "true" ]]; then
    export_cmd+=(--no-ocr)
  fi

  if ! "${export_cmd[@]}" >"$export_log" 2>&1; then
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$index" "$file_path" "export_failed" "" "$export_json" "" "$export_log" "" >> "$DOCS_TSV"
    continue
  fi

  doc_id="$(node -e 'const fs=require("fs");const p=process.argv[1];const d=JSON.parse(fs.readFileSync(p,"utf8"));process.stdout.write(String(d.docId||""));' "$export_json" 2>/dev/null || true)"

  chunk_cmd=(
    node "$CHUNKIFY_SCRIPT"
    --input-file "$export_json"
    --output-file "$chunk_jsonl"
    --summary-file "${REPORT_DIR}/${idx}_${safe_name}.chunk-summary.json"
    --chunk-size "$CHUNK_SIZE"
    --chunk-overlap "$CHUNK_OVERLAP"
    --min-chunk-size "$MIN_CHUNK_SIZE"
  )

  if ! "${chunk_cmd[@]}" >"$chunk_log" 2>&1; then
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$index" "$file_path" "chunk_failed" "$doc_id" "$export_json" "$chunk_jsonl" "$export_log" "$chunk_log" >> "$DOCS_TSV"
    continue
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$index" "$file_path" "ok" "$doc_id" "$export_json" "$chunk_jsonl" "$export_log" "$chunk_log" >> "$DOCS_TSV"
done

RUN_SUMMARY_JSON="${REPORT_DIR}/run-summary.json"
FALLBACK_REPORT_JSON="${REPORT_DIR}/fallback-report.json"
AB_SUMMARY_JSON="${REPORT_DIR}/ab-summary.json"
RUN_SUMMARY_MD="${REPORT_DIR}/run-summary.md"

node - "$DOCS_TSV" "$RUN_SUMMARY_JSON" "$FALLBACK_REPORT_JSON" "$AB_SUMMARY_JSON" "$RUN_SUMMARY_MD" "$BASELINE_DIR" "$RUN_ID" "$INPUT_PATH" "$RUN_DIR" <<'NODE'
const fs = require("fs");
const path = require("path");

function normalizeHostPath(inputPath) {
  if (!inputPath) {
    return "";
  }
  if (process.platform === "win32" && /^\/[a-zA-Z]\//.test(inputPath)) {
    const drive = inputPath[1].toUpperCase();
    const rest = inputPath.slice(3).replace(/\//g, "\\");
    return `${drive}:\\${rest}`;
  }
  return inputPath;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(normalizeHostPath(filePath), "utf8"));
}

function fileExists(filePath) {
  const normalized = normalizeHostPath(filePath);
  return !!normalized && fs.existsSync(normalized) && fs.statSync(normalized).isFile();
}

function parseJsonLikeChunkFile(filePath) {
  const normalized = normalizeHostPath(filePath);
  if (!fileExists(normalized)) {
    return { chunkCount: 0, textChars: 0 };
  }
  const ext = path.extname(normalized).toLowerCase();
  if (ext === ".jsonl") {
    const lines = fs
      .readFileSync(normalized, "utf8")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    let textChars = 0;
    for (const line of lines) {
      try {
        const row = JSON.parse(line);
        textChars += String(row.text || "").length;
      } catch (_) {
        // ignore malformed line
      }
    }
    return { chunkCount: lines.length, textChars };
  }
  try {
    const data = readJson(normalized);
    const arr = Array.isArray(data) ? data : [];
    const textChars = arr.reduce((sum, row) => sum + String((row && row.text) || "").length, 0);
    return { chunkCount: arr.length, textChars };
  } catch (_) {
    return { chunkCount: 0, textChars: 0 };
  }
}

function findBaselineChunkFile(baselineDir, docId, filePath) {
  const normalizedBaselineDir = normalizeHostPath(baselineDir);
  if (!normalizedBaselineDir || !fs.existsSync(normalizedBaselineDir)) {
    return "";
  }
  const baseName = path.basename(filePath || "", path.extname(filePath || ""));
  const candidates = [
    docId ? path.join(normalizedBaselineDir, `${docId}.chunks.jsonl`) : "",
    docId ? path.join(normalizedBaselineDir, `${docId}.jsonl`) : "",
    baseName ? path.join(normalizedBaselineDir, `${baseName}.chunks.jsonl`) : "",
    baseName ? path.join(normalizedBaselineDir, `${baseName}.jsonl`) : "",
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (fileExists(candidate)) {
      return candidate;
    }
  }
  return "";
}

function parseTsv(tsvPath) {
  const rows = fs
    .readFileSync(tsvPath, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean);
  if (rows.length <= 1) {
    return [];
  }
  const dataRows = rows.slice(1);
  return dataRows.map((row) => {
    const cols = row.split("\t");
    return {
      index: Number(cols[0] || 0),
      filePath: cols[1] || "",
      status: cols[2] || "unknown",
      docId: cols[3] || "",
      exportJson: cols[4] || "",
      chunkJsonl: cols[5] || "",
      exportLog: cols[6] || "",
      chunkLog: cols[7] || "",
    };
  });
}

const [
  docsTsvPath,
  runSummaryPath,
  fallbackPath,
  abSummaryPath,
  summaryMdPath,
  baselineDir,
  runId,
  inputPath,
  runDir,
] = process.argv.slice(2);

const rows = parseTsv(docsTsvPath);
const documents = [];
const fallbackDocuments = [];
const abRows = [];

const totals = {
  documents: rows.length,
  ok: 0,
  export_failed: 0,
  chunk_failed: 0,
  fallbackRecommended: 0,
  criteria: {
    lowText: 0,
    strongFragmentation: 0,
    ocrArtifacts: 0,
    tableLoss: 0,
  },
};

for (const row of rows) {
  let exportData = null;
  let extraction = null;
  let quality = null;
  let parseQuality = "unknown";
  let fallbackRecommended = false;
  let criteria = {
    lowText: { triggered: false },
    strongFragmentation: { triggered: false },
    ocrArtifacts: { triggered: false },
    tableLoss: { triggered: false },
  };
  if (fileExists(row.exportJson)) {
    try {
      exportData = readJson(row.exportJson);
      extraction = exportData.extraction || null;
      quality = exportData.quality || null;
      parseQuality = String((quality && quality.parseQuality) || "unknown");
      fallbackRecommended = Boolean(quality && quality.fallbackRecommended);
      criteria = Object.assign(criteria, (quality && quality.criteria) || {});
    } catch (_) {
      // keep defaults
    }
  }

  const liteStats = parseJsonLikeChunkFile(row.chunkJsonl);
  if (row.status === "ok") {
    totals.ok += 1;
  } else if (row.status === "export_failed") {
    totals.export_failed += 1;
  } else if (row.status === "chunk_failed") {
    totals.chunk_failed += 1;
  }

  for (const key of Object.keys(totals.criteria)) {
    if (criteria[key] && criteria[key].triggered) {
      totals.criteria[key] += 1;
    }
  }
  if (fallbackRecommended) {
    totals.fallbackRecommended += 1;
  }

  const baselineFile = findBaselineChunkFile(baselineDir, row.docId, row.filePath);
  const baselineStats = baselineFile ? parseJsonLikeChunkFile(baselineFile) : null;
  let recommendation = "liteparse_ok";
  if (fallbackRecommended && !baselineStats) {
    recommendation = "fallback_candidate_baseline_missing";
  } else if (fallbackRecommended && baselineStats) {
    const textGain = baselineStats.textChars - liteStats.textChars;
    const chunkGain = baselineStats.chunkCount - liteStats.chunkCount;
    if (textGain > Math.max(200, Math.floor(liteStats.textChars * 0.2)) || chunkGain > 3) {
      recommendation = "fallback_to_baseline";
    } else {
      recommendation = "fallback_candidate_review";
    }
    abRows.push({
      docId: row.docId,
      filePath: row.filePath,
      liteparseChunks: liteStats.chunkCount,
      baselineChunks: baselineStats.chunkCount,
      liteparseTextChars: liteStats.textChars,
      baselineTextChars: baselineStats.textChars,
      textCharDelta: baselineStats.textChars - liteStats.textChars,
      chunkDelta: baselineStats.chunkCount - liteStats.chunkCount,
      recommendation,
      baselineFile,
    });
  }

  const docEntry = {
    index: row.index,
    docId: row.docId || null,
    filePath: row.filePath,
    status: row.status,
    parseQuality,
    fallbackRecommended,
    recommendation,
    extraction,
    criteria,
    liteparse: {
      chunkCount: liteStats.chunkCount,
      textChars: liteStats.textChars,
      exportJson: row.exportJson || null,
      chunkFile: row.chunkJsonl || null,
    },
    baseline: baselineStats
      ? {
          chunkCount: baselineStats.chunkCount,
          textChars: baselineStats.textChars,
          chunkFile: baselineFile,
        }
      : null,
    logs: {
      export: row.exportLog || null,
      chunkify: row.chunkLog || null,
    },
  };
  documents.push(docEntry);
  if (fallbackRecommended) {
    fallbackDocuments.push(docEntry);
  }
}

const runSummary = {
  runId,
  createdAt: new Date().toISOString(),
  inputPath: path.resolve(normalizeHostPath(inputPath)),
  runDir: path.resolve(normalizeHostPath(runDir)),
  baselineDir: baselineDir ? path.resolve(normalizeHostPath(baselineDir)) : null,
  totals,
  documents,
};

const abSummary = {
  runId,
  baselineDir: baselineDir ? path.resolve(normalizeHostPath(baselineDir)) : null,
  comparedDocuments: abRows.length,
  comparisons: abRows,
};

fs.writeFileSync(runSummaryPath, JSON.stringify(runSummary, null, 2));
fs.writeFileSync(fallbackPath, JSON.stringify({ runId, fallbackDocuments }, null, 2));
fs.writeFileSync(abSummaryPath, JSON.stringify(abSummary, null, 2));

const markdown = [
  `# LiteParse PoC Run ${runId}`,
  ``,
  `- Input: \`${path.resolve(normalizeHostPath(inputPath))}\``,
  `- Run dir: \`${path.resolve(normalizeHostPath(runDir))}\``,
  `- Documents: **${totals.documents}**`,
  `- Success: **${totals.ok}**`,
  `- Export failed: **${totals.export_failed}**`,
  `- Chunk failed: **${totals.chunk_failed}**`,
  `- Fallback candidates: **${totals.fallbackRecommended}**`,
  ``,
  `## Criteria Hits`,
  ``,
  `- lowText: ${totals.criteria.lowText}`,
  `- strongFragmentation: ${totals.criteria.strongFragmentation}`,
  `- ocrArtifacts: ${totals.criteria.ocrArtifacts}`,
  `- tableLoss: ${totals.criteria.tableLoss}`,
  ``,
];

if (abRows.length > 0) {
  markdown.push("## A/B Compared Documents", "");
  for (const row of abRows) {
    markdown.push(
      `- ${row.docId || row.filePath}: liteparse chunks=${row.liteparseChunks}, baseline chunks=${row.baselineChunks}, ` +
        `liteparse chars=${row.liteparseTextChars}, baseline chars=${row.baselineTextChars}, recommendation=${row.recommendation}`
    );
  }
  markdown.push("");
}

fs.writeFileSync(summaryMdPath, markdown.join("\n"));
NODE

log "Run summary: ${RUN_SUMMARY_JSON}"
log "Fallback report: ${FALLBACK_REPORT_JSON}"
log "A/B summary: ${AB_SUMMARY_JSON}"
log "Human summary: ${RUN_SUMMARY_MD}"
log "Run completed: ${RUN_ID}"
