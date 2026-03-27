#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

class AppError extends Error {
  constructor(message, code = "E_APP") {
    super(message);
    this.name = "AppError";
    this.code = code;
  }
}

function printHelp() {
  process.stdout.write(
    [
      "LiteParse export helper for scanservjs PoC",
      "",
      "Usage:",
      "  node liteparse-export.js --input-file <path> --output-file <path> [options]",
      "",
      "Required:",
      "  --input-file <path>           Source document",
      "  --output-file <path>          Target JSON file",
      "",
      "Optional:",
      "  --doc-id <id>                 Stable document id",
      "  --source <label>              Source label (default: scanservjs-manual-cli)",
      "  --parser <name>               Parser label (default: liteparse-cli)",
      "  --config <path>               LiteParse JSON config file",
      "  --liteparse-bin <cmd>         LiteParse command (default: lit)",
      "  --ocr-language <lang>         OCR language override",
      "  --ocr-server-url <url>        OCR server URL override",
      "  --target-pages <ranges>       Target pages (e.g. 1-3,7)",
      "  --max-pages <n>               Max pages",
      "  --dpi <n>                     Render DPI",
      "  --num-workers <n>             OCR workers",
      "  --created-at <iso-date>       Timestamp override",
      "  --no-ocr                      Disable OCR",
      "  --preserve-small-text         Preserve very small text",
      "  --no-precise-bbox             Disable deprecated boundingBoxes output",
      "  --quiet                       Suppress LiteParse progress output",
      "  --min-text-chars <n>          Threshold for low-text criterion (default: 220)",
      "  --fragmentation-threshold <f> Threshold for fragmentation criterion (default: 0.62)",
      "  --ocr-artifact-threshold <f>  Threshold for OCR artifacts criterion (default: 0.34)",
      "  --table-loss-threshold <f>    Threshold for table-loss criterion (default: 0.45)",
      "  -h, --help                    Show this help",
      "",
      "Output:",
      "  JSON with page-level extraction + quality metrics + fallback recommendation.",
      "",
    ].join("\n")
  );
}

function parseArgs(argv) {
  const options = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "-h" || arg === "--help") {
      options.help = true;
      continue;
    }
    if (!arg.startsWith("--")) {
      throw new AppError(`Unknown argument: ${arg}`, "E_ARGS");
    }
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (next !== undefined && !next.startsWith("--")) {
      options[key] = next;
      i += 1;
    } else {
      options[key] = true;
    }
  }
  return options;
}

function asInt(value, fieldName, min = Number.MIN_SAFE_INTEGER) {
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed) || Number.isNaN(parsed)) {
    throw new AppError(`${fieldName} must be an integer`, "E_ARGS");
  }
  if (parsed < min) {
    throw new AppError(`${fieldName} must be >= ${min}`, "E_ARGS");
  }
  return parsed;
}

function asFloat(value, fieldName, min = Number.NEGATIVE_INFINITY, max = Number.POSITIVE_INFINITY) {
  const parsed = Number.parseFloat(String(value));
  if (!Number.isFinite(parsed) || Number.isNaN(parsed)) {
    throw new AppError(`${fieldName} must be a number`, "E_ARGS");
  }
  if (parsed < min || parsed > max) {
    throw new AppError(`${fieldName} must be between ${min} and ${max}`, "E_ARGS");
  }
  return parsed;
}

function toNumberOrNull(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function clamp(value, min = 0, max = 1) {
  return Math.max(min, Math.min(max, value));
}

function round(value, digits = 4) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function ensureReadableFile(filePath, name) {
  if (!filePath || typeof filePath !== "string") {
    throw new AppError(`${name} is required`, "E_ARGS");
  }
  if (!fs.existsSync(filePath)) {
    throw new AppError(`${name} not found: ${filePath}`, "E_PATH");
  }
  const stat = fs.statSync(filePath);
  if (!stat.isFile()) {
    throw new AppError(`${name} is not a file: ${filePath}`, "E_PATH");
  }
}

function ensureDirectoryFor(filePath) {
  const dir = path.dirname(path.resolve(filePath));
  fs.mkdirSync(dir, { recursive: true });
}

function generateDocId(inputFile) {
  const basename = path.basename(inputFile).replace(/[^A-Za-z0-9._-]+/g, "_");
  const resolved = path.resolve(inputFile);
  const digest = crypto.createHash("sha1").update(resolved).digest("hex").slice(0, 10);
  return `${basename}-${digest}`;
}

function normalizeTextItem(rawItem, index) {
  const rawText = rawItem && typeof rawItem === "object" ? rawItem.text ?? rawItem.str : "";
  const text = String(rawText ?? "").replace(/\r/g, "").trim();
  if (!text) {
    return null;
  }
  const result = {
    index,
    text,
    x: toNumberOrNull(rawItem.x),
    y: toNumberOrNull(rawItem.y),
    width: toNumberOrNull(rawItem.width ?? rawItem.w),
    height: toNumberOrNull(rawItem.height ?? rawItem.h),
  };
  if (rawItem.fontName !== undefined) {
    result.fontName = String(rawItem.fontName);
  }
  if (rawItem.fontSize !== undefined && Number.isFinite(Number(rawItem.fontSize))) {
    result.fontSize = Number(rawItem.fontSize);
  }
  return result;
}

function normalizeBoundingBoxes(rawBoundingBoxes) {
  if (!Array.isArray(rawBoundingBoxes)) {
    return [];
  }
  const output = [];
  for (const box of rawBoundingBoxes) {
    if (!box || typeof box !== "object") {
      continue;
    }
    const x1 = toNumberOrNull(box.x1);
    const y1 = toNumberOrNull(box.y1);
    const x2 = toNumberOrNull(box.x2);
    const y2 = toNumberOrNull(box.y2);
    if (x1 === null || y1 === null || x2 === null || y2 === null) {
      continue;
    }
    output.push({ x1, y1, x2, y2 });
  }
  return output;
}

function rebuildTextFromItems(textItems) {
  if (!Array.isArray(textItems) || textItems.length === 0) {
    return "";
  }
  const ordered = [...textItems].sort((a, b) => {
    const yA = Number.isFinite(a.y) ? a.y : Number.POSITIVE_INFINITY;
    const yB = Number.isFinite(b.y) ? b.y : Number.POSITIVE_INFINITY;
    if (Math.abs(yA - yB) >= 2) {
      return yA - yB;
    }
    const xA = Number.isFinite(a.x) ? a.x : Number.POSITIVE_INFINITY;
    const xB = Number.isFinite(b.x) ? b.x : Number.POSITIVE_INFINITY;
    return xA - xB;
  });

  const lines = [];
  let currentLine = [];
  let anchorY = null;
  for (const item of ordered) {
    const y = Number.isFinite(item.y) ? item.y : anchorY;
    if (anchorY === null) {
      anchorY = y;
      currentLine.push(item.text);
      continue;
    }
    const lineBreakThreshold = Number.isFinite(item.height) ? Math.max(item.height, 4) : 6;
    if (y !== null && Math.abs(y - anchorY) > lineBreakThreshold) {
      lines.push(currentLine.join(" ").trim());
      currentLine = [item.text];
      anchorY = y;
    } else {
      currentLine.push(item.text);
      if (y !== null) {
        anchorY = y;
      }
    }
  }
  if (currentLine.length > 0) {
    lines.push(currentLine.join(" ").trim());
  }
  return lines.filter(Boolean).join("\n");
}

function normalizePage(rawPage, index) {
  const pageCandidate = rawPage.page ?? rawPage.pageNum ?? index + 1;
  const page = Number.isFinite(Number(pageCandidate)) ? Number(pageCandidate) : index + 1;
  const rawTextItems = Array.isArray(rawPage.textItems) ? rawPage.textItems : [];
  const textItems = [];
  for (let i = 0; i < rawTextItems.length; i += 1) {
    const item = normalizeTextItem(rawTextItems[i], i);
    if (item) {
      textItems.push(item);
    }
  }
  const textFromPage = String(rawPage.text ?? "").replace(/\r/g, "");
  const text = textFromPage.trim() ? textFromPage : rebuildTextFromItems(textItems);
  const boundingBoxes = normalizeBoundingBoxes(rawPage.boundingBoxes);
  return {
    page,
    width: toNumberOrNull(rawPage.width),
    height: toNumberOrNull(rawPage.height),
    text,
    textItems,
    boundingBoxes,
    stats: {
      textCharCount: text.length,
      textItemCount: textItems.length,
      lineCount: text.split(/\n+/).filter((line) => line.trim().length > 0).length,
    },
  };
}

function normalizeLiteParseJson(raw) {
  if (!raw || typeof raw !== "object") {
    throw new AppError("LiteParse output is not a JSON object", "E_PARSE");
  }
  const rawPages = Array.isArray(raw.pages)
    ? raw.pages
    : raw.json && Array.isArray(raw.json.pages)
      ? raw.json.pages
      : null;
  if (!rawPages) {
    throw new AppError("LiteParse output does not contain pages[]", "E_PARSE");
  }
  const pages = rawPages.map((page, index) => normalizePage(page, index));
  return {
    pages,
    text: String(raw.text ?? pages.map((page) => page.text).join("\n\n")),
  };
}

function collectLetterStats(text) {
  const compact = text.replace(/\s+/g, "");
  const total = compact.length;
  if (total === 0) {
    return {
      total,
      replacementChars: 0,
      punctuationRuns: 0,
      shortTokenRatio: 0,
      suspiciousRatio: 0,
    };
  }

  const replacementChars = (compact.match(/\uFFFD/g) || []).length;
  const punctuationRuns = (compact.match(/[|\\/_~^*+=]{2,}/g) || []).join("").length;
  const tokens = text
    .split(/\s+/)
    .map((token) => token.trim())
    .filter(Boolean);
  const shortTokens = tokens.filter((token) => token.length <= 2).length;
  const nonWordHeavyTokens = tokens.filter((token) => {
    const nonWord = (token.match(/[^A-Za-z0-9\u00C0-\u024F]/g) || []).length;
    return token.length > 0 && nonWord / token.length > 0.5;
  }).length;
  const shortTokenRatio = tokens.length ? shortTokens / tokens.length : 0;
  const weirdTokenRatio = tokens.length ? nonWordHeavyTokens / tokens.length : 0;
  const suspiciousRatio = clamp(
    replacementChars / total + punctuationRuns / total + shortTokenRatio * 0.35 + weirdTokenRatio * 0.25
  );
  return {
    total,
    replacementChars,
    punctuationRuns,
    shortTokenRatio,
    suspiciousRatio,
  };
}

function computeFragmentation(pages, totalChars, totalTextItems) {
  let totalItemChars = 0;
  let tinyItems = 0;
  for (const page of pages) {
    for (const item of page.textItems) {
      const len = item.text.length;
      totalItemChars += len;
      if (len <= 2) {
        tinyItems += 1;
      }
    }
  }
  const avgItemChars = totalTextItems > 0 ? totalItemChars / totalTextItems : 0;
  const itemsPerThousandChars = totalTextItems / Math.max(1, totalChars / 1000);
  const tinyItemRatio = totalTextItems > 0 ? tinyItems / totalTextItems : 0;
  const score = clamp(
    (itemsPerThousandChars / 180) * 0.45 + (1 - clamp(avgItemChars / 6)) * 0.35 + tinyItemRatio * 0.2
  );
  return {
    score,
    avgItemChars,
    itemsPerThousandChars,
    tinyItemRatio,
  };
}

function detectTableLoss(pages, threshold) {
  let candidatePages = 0;
  let flattenedPages = 0;
  const affectedPages = [];

  for (const page of pages) {
    const items = page.textItems.filter((item) => item.text && Number.isFinite(item.x) && Number.isFinite(item.y));
    if (items.length < 16) {
      continue;
    }

    const rows = new Map();
    for (const item of items) {
      const yBucket = Math.round(item.y / 4) * 4;
      if (!rows.has(yBucket)) {
        rows.set(yBucket, []);
      }
      rows.get(yBucket).push(item);
    }

    const denseRows = [...rows.values()].filter((row) => row.length >= 3);
    if (denseRows.length < 4) {
      continue;
    }

    const colFrequency = new Map();
    for (const row of denseRows) {
      const uniqueCols = new Set(
        row
          .map((item) => Math.round(item.x / 20) * 20)
          .sort((a, b) => a - b)
      );
      for (const col of uniqueCols) {
        colFrequency.set(col, (colFrequency.get(col) || 0) + 1);
      }
    }
    const stableColumns = [...colFrequency.values()].filter((count) => count >= 3).length;
    if (stableColumns < 3) {
      continue;
    }

    candidatePages += 1;
    const nonEmptyLines = String(page.text || "")
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean);
    const structuredLines = nonEmptyLines.filter((line) => /\|/.test(line) || /\t/.test(line) || / {2,}/.test(line))
      .length;
    const flattened = structuredLines < Math.max(2, Math.floor(denseRows.length * 0.25));
    if (flattened) {
      flattenedPages += 1;
      affectedPages.push(page.page);
    }
  }

  const score = candidatePages > 0 ? flattenedPages / candidatePages : 0;
  return {
    triggered: candidatePages > 0 && score >= threshold,
    score,
    candidatePages,
    flattenedPages,
    affectedPages,
  };
}

function buildQuality(pages, thresholds) {
  const totalChars = pages.reduce((sum, page) => sum + page.text.length, 0);
  const totalTextItems = pages.reduce((sum, page) => sum + page.textItems.length, 0);
  const nonEmptyPages = pages.filter((page) => page.text.trim().length > 0).length;
  const avgCharsPerPage = pages.length > 0 ? totalChars / pages.length : 0;
  const fullText = pages.map((page) => page.text).join("\n");

  const fragmentation = computeFragmentation(pages, totalChars, totalTextItems);
  const artifactStats = collectLetterStats(fullText);
  const tableLoss = detectTableLoss(pages, thresholds.tableLoss);

  const lowTextTriggered = totalChars < thresholds.minTextChars;
  const fragmentationTriggered = fragmentation.score >= thresholds.fragmentation;
  const artifactTriggered = artifactStats.suspiciousRatio >= thresholds.ocrArtifact;

  const criteria = {
    lowText: {
      triggered: lowTextTriggered,
      observed: totalChars,
      threshold: thresholds.minTextChars,
      detail: `chars=${totalChars}`,
    },
    strongFragmentation: {
      triggered: fragmentationTriggered,
      observed: round(fragmentation.score),
      threshold: thresholds.fragmentation,
      detail: `itemsPerKChars=${round(fragmentation.itemsPerThousandChars)}, avgItemChars=${round(
        fragmentation.avgItemChars
      )}, tinyItemRatio=${round(fragmentation.tinyItemRatio)}`,
    },
    ocrArtifacts: {
      triggered: artifactTriggered,
      observed: round(artifactStats.suspiciousRatio),
      threshold: thresholds.ocrArtifact,
      detail: `replacementChars=${artifactStats.replacementChars}, punctuationRuns=${artifactStats.punctuationRuns}, shortTokenRatio=${round(
        artifactStats.shortTokenRatio
      )}`,
    },
    tableLoss: {
      triggered: tableLoss.triggered,
      observed: round(tableLoss.score),
      threshold: thresholds.tableLoss,
      detail: `candidatePages=${tableLoss.candidatePages}, flattenedPages=${tableLoss.flattenedPages}`,
      affectedPages: tableLoss.affectedPages,
    },
  };

  const reasons = Object.entries(criteria)
    .filter(([, value]) => value.triggered)
    .map(([key, value]) => `${key}: ${value.detail}`);

  let scoreBase = 0.58;
  if (totalChars >= 1600) {
    scoreBase = 0.9;
  } else if (totalChars >= 900) {
    scoreBase = 0.8;
  } else if (totalChars >= thresholds.minTextChars) {
    scoreBase = 0.68;
  }

  let penalty = 0;
  if (lowTextTriggered) {
    penalty += 0.35;
  }
  if (fragmentationTriggered) {
    penalty += 0.25;
  }
  if (artifactTriggered) {
    penalty += 0.2;
  }
  if (tableLoss.triggered) {
    penalty += 0.2;
  }
  const score = clamp(scoreBase - penalty);

  let parseQuality = "low";
  if (score >= 0.82) {
    parseQuality = "high";
  } else if (score >= 0.55) {
    parseQuality = "medium";
  }

  const fallbackRecommended = reasons.length > 0;
  if (fallbackRecommended && parseQuality === "high") {
    parseQuality = "medium";
  }

  return {
    parseQuality,
    score: round(score),
    fallbackRecommended,
    reasons,
    criteria,
    extractionStats: {
      pageCount: pages.length,
      nonEmptyPages,
      textCharCount: totalChars,
      textItemCount: totalTextItems,
      averageCharsPerPage: round(avgCharsPerPage),
    },
  };
}

function runLiteParse(opts) {
  const command = opts.liteparseBin || "lit";
  const args = ["parse", opts.inputFile, "--format", "json", "--output", opts.tmpOutputFile];
  if (opts.configPath) {
    args.push("--config", opts.configPath);
  }
  if (opts.noOcr) {
    args.push("--no-ocr");
  }
  if (opts.ocrLanguage) {
    args.push("--ocr-language", opts.ocrLanguage);
  }
  if (opts.ocrServerUrl) {
    args.push("--ocr-server-url", opts.ocrServerUrl);
  }
  if (opts.targetPages) {
    args.push("--target-pages", opts.targetPages);
  }
  if (opts.maxPages !== undefined) {
    args.push("--max-pages", String(opts.maxPages));
  }
  if (opts.dpi !== undefined) {
    args.push("--dpi", String(opts.dpi));
  }
  if (opts.numWorkers !== undefined) {
    args.push("--num-workers", String(opts.numWorkers));
  }
  if (opts.preserveSmallText) {
    args.push("--preserve-small-text");
  }
  if (opts.noPreciseBbox) {
    args.push("--no-precise-bbox");
  }
  if (opts.quiet) {
    args.push("--quiet");
  }

  const spawnOptions = {
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  };

  const result =
    process.platform === "win32"
      ? spawnSync(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", command, ...args], spawnOptions)
      : spawnSync(command, args, spawnOptions);

  if (result.error) {
    if (result.error.code === "ENOENT") {
      throw new AppError(`LiteParse binary not found: ${command}`, "E_BIN");
    }
    throw new AppError(`Failed to execute LiteParse: ${result.error.message}`, "E_BIN");
  }

  if (result.status !== 0) {
    const stderr = String(result.stderr || "").trim();
    const stdout = String(result.stdout || "").trim();
    const detail = stderr || stdout || "<no output>";
    throw new AppError(`LiteParse failed with exit code ${result.status}: ${detail}`, "E_LITEPARSE");
  }

  return {
    command,
    args,
    stdout: String(result.stdout || ""),
    stderr: String(result.stderr || ""),
  };
}

function readJson(filePath, label) {
  let raw = "";
  try {
    raw = fs.readFileSync(filePath, "utf8");
  } catch (error) {
    throw new AppError(`Unable to read ${label}: ${error.message}`, "E_IO");
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    throw new AppError(`Invalid JSON in ${label}: ${error.message}`, "E_PARSE");
  }
}

function writeJson(filePath, data) {
  ensureDirectoryFor(filePath);
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
}

function buildFinalDocument(opts, normalized, quality, commandInfo) {
  const createdAt = opts.createdAt || new Date().toISOString();
  const docId = opts.docId || generateDocId(opts.inputFile);
  return {
    schemaVersion: "1.0",
    createdAt,
    docId,
    source: opts.source,
    filePath: path.resolve(opts.inputFile),
    parser: opts.parser,
    command: {
      bin: commandInfo.command,
      args: commandInfo.args,
      configFile: opts.configPath ? path.resolve(opts.configPath) : null,
      stdoutBytes: Buffer.byteLength(commandInfo.stdout || "", "utf8"),
      stderrBytes: Buffer.byteLength(commandInfo.stderr || "", "utf8"),
    },
    extraction: quality.extractionStats,
    quality: {
      parseQuality: quality.parseQuality,
      score: quality.score,
      fallbackRecommended: quality.fallbackRecommended,
      reasons: quality.reasons,
      criteria: quality.criteria,
    },
    pages: normalized.pages,
  };
}

function main() {
  try {
    const options = parseArgs(process.argv.slice(2));
    if (options.help) {
      printHelp();
      return;
    }

    const inputFile = options["input-file"];
    const outputFile = options["output-file"];
    ensureReadableFile(inputFile, "--input-file");
    if (!outputFile || typeof outputFile !== "string") {
      throw new AppError("--output-file is required", "E_ARGS");
    }

    const configPath = options.config ? String(options.config) : "";
    if (configPath) {
      ensureReadableFile(configPath, "--config");
    }

    const thresholds = {
      minTextChars: options["min-text-chars"] ? asInt(options["min-text-chars"], "--min-text-chars", 1) : 220,
      fragmentation: options["fragmentation-threshold"]
        ? asFloat(options["fragmentation-threshold"], "--fragmentation-threshold", 0, 1)
        : 0.62,
      ocrArtifact: options["ocr-artifact-threshold"]
        ? asFloat(options["ocr-artifact-threshold"], "--ocr-artifact-threshold", 0, 1)
        : 0.34,
      tableLoss: options["table-loss-threshold"]
        ? asFloat(options["table-loss-threshold"], "--table-loss-threshold", 0, 1)
        : 0.45,
    };

    const nowIso = options["created-at"] ? String(options["created-at"]) : new Date().toISOString();
    const tmpOutputFile = path.join(
      os.tmpdir(),
      `liteparse-export-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}.json`
    );

    const runtimeOptions = {
      inputFile: path.resolve(inputFile),
      outputFile: path.resolve(outputFile),
      tmpOutputFile,
      configPath: configPath ? path.resolve(configPath) : "",
      liteparseBin: String(options["liteparse-bin"] || "lit"),
      ocrLanguage: options["ocr-language"] ? String(options["ocr-language"]) : "",
      ocrServerUrl: options["ocr-server-url"] ? String(options["ocr-server-url"]) : "",
      targetPages: options["target-pages"] ? String(options["target-pages"]) : "",
      maxPages: options["max-pages"] !== undefined ? asInt(options["max-pages"], "--max-pages", 1) : undefined,
      dpi: options.dpi !== undefined ? asInt(options.dpi, "--dpi", 1) : undefined,
      numWorkers: options["num-workers"] !== undefined ? asInt(options["num-workers"], "--num-workers", 1) : undefined,
      noOcr: options["no-ocr"] === true,
      preserveSmallText: options["preserve-small-text"] === true,
      noPreciseBbox: options["no-precise-bbox"] === true,
      quiet: options.quiet === true,
      source: String(options.source || "scanservjs-manual-cli"),
      parser: String(options.parser || "liteparse-cli"),
      docId: options["doc-id"] ? String(options["doc-id"]) : "",
      createdAt: nowIso,
    };

    let commandInfo;
    try {
      commandInfo = runLiteParse(runtimeOptions);
      const rawLiteParseJson = readJson(tmpOutputFile, "LiteParse output");
      const normalized = normalizeLiteParseJson(rawLiteParseJson);
      const quality = buildQuality(normalized.pages, thresholds);
      const finalDocument = buildFinalDocument(runtimeOptions, normalized, quality, commandInfo);
      writeJson(runtimeOptions.outputFile, finalDocument);
      process.stdout.write(
        JSON.stringify(
          {
            ok: true,
            docId: finalDocument.docId,
            outputFile: runtimeOptions.outputFile,
            parseQuality: finalDocument.quality.parseQuality,
            fallbackRecommended: finalDocument.quality.fallbackRecommended,
            pageCount: finalDocument.extraction.pageCount,
            chunkableTextChars: finalDocument.extraction.textCharCount,
          },
          null,
          2
        ) + "\n"
      );
    } finally {
      if (fs.existsSync(tmpOutputFile)) {
        fs.rmSync(tmpOutputFile, { force: true });
      }
    }
  } catch (error) {
    const isAppError = error instanceof AppError;
    const code = isAppError ? error.code : "E_UNEXPECTED";
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(JSON.stringify({ ok: false, code, message }, null, 2) + "\n");
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}
