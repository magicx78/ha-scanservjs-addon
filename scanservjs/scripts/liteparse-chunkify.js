#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

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
      "LiteParse chunkify helper for scanservjs PoC",
      "",
      "Usage:",
      "  node liteparse-chunkify.js --input-file <export.json> --output-file <chunks.jsonl> [options]",
      "",
      "Required:",
      "  --input-file <path>            Export JSON from liteparse-export.js",
      "  --output-file <path>           Target chunk file (.jsonl or .json)",
      "",
      "Optional:",
      "  --output-mode <jsonl|json>     Defaults by output file extension",
      "  --summary-file <path>          Write chunk summary JSON",
      "  --chunk-size <n>               Target chunk size (default: 900)",
      "  --chunk-overlap <n>            Overlap between chunks (default: 180)",
      "  --min-chunk-size <n>           Ignore chunks smaller than this (default: 120)",
      "  --max-text-item-refs <n>       Max textItemRefs per chunk (default: 40)",
      "  --source <label>               Override source label",
      "  --parser <name>                Override parser label",
      "  --parse-quality <value>        Override parseQuality",
      "  --created-at <iso-date>        Override createdAt",
      "  -h, --help                     Show this help",
      "",
      "Chunk schema:",
      "  id, docId, source, filePath, page, text, chunkIndex, parser, parseQuality, createdAt",
      "  optional bbox, optional textItemRefs",
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

function ensureReadableFile(filePath, flagName) {
  if (!filePath) {
    throw new AppError(`${flagName} is required`, "E_ARGS");
  }
  if (!fs.existsSync(filePath)) {
    throw new AppError(`${flagName} not found: ${filePath}`, "E_PATH");
  }
  const stat = fs.statSync(filePath);
  if (!stat.isFile()) {
    throw new AppError(`${flagName} is not a file: ${filePath}`, "E_PATH");
  }
}

function ensureOutputDir(filePath) {
  fs.mkdirSync(path.dirname(path.resolve(filePath)), { recursive: true });
}

function normalizeWhitespace(text) {
  return String(text || "")
    .replace(/\r/g, "")
    .replace(/\t/g, " ")
    .replace(/[ ]{2,}/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function splitIntoChunks(text, chunkSize, overlap, minChunkSize) {
  const normalized = normalizeWhitespace(text);
  if (!normalized) {
    return [];
  }
  if (normalized.length <= chunkSize) {
    return normalized.length >= minChunkSize ? [normalized] : [normalized];
  }

  const chunks = [];
  let start = 0;

  while (start < normalized.length) {
    let end = Math.min(normalized.length, start + chunkSize);
    if (end < normalized.length) {
      const candidateNewline = normalized.lastIndexOf("\n", end);
      const candidateSpace = normalized.lastIndexOf(" ", end);
      const pivot = Math.max(candidateNewline, candidateSpace);
      if (pivot > start + Math.floor(chunkSize * 0.55)) {
        end = pivot;
      }
    }

    const chunk = normalized.slice(start, end).trim();
    if (chunk.length >= minChunkSize || end >= normalized.length) {
      chunks.push(chunk);
    }

    if (end >= normalized.length) {
      break;
    }
    const nextStart = Math.max(0, end - overlap);
    if (nextStart <= start) {
      start = end;
    } else {
      start = nextStart;
    }
  }

  return chunks;
}

function normalizeComparable(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/[^\p{L}\p{N}\s.,;:/\-()]/gu, "")
    .trim();
}

function collectTextItemRefs(chunkText, textItems, maxRefs) {
  if (!Array.isArray(textItems) || textItems.length === 0) {
    return [];
  }
  const chunkComparable = normalizeComparable(chunkText);
  if (!chunkComparable) {
    return [];
  }
  const refs = [];
  const seen = new Set();

  for (const item of textItems) {
    const itemText = normalizeComparable(item.text);
    if (!itemText || itemText.length < 2) {
      continue;
    }
    if (chunkComparable.includes(itemText)) {
      const ref = Number.isFinite(Number(item.index)) ? Number(item.index) : null;
      if (ref !== null && !seen.has(ref)) {
        seen.add(ref);
        refs.push(ref);
      }
      if (refs.length >= maxRefs) {
        break;
      }
    }
  }

  return refs;
}

function toNumberOrNull(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function buildBbox(textItems, refs) {
  if (!Array.isArray(refs) || refs.length === 0) {
    return null;
  }
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  let found = false;

  const byIndex = new Map();
  for (const item of textItems || []) {
    if (Number.isFinite(Number(item.index))) {
      byIndex.set(Number(item.index), item);
    }
  }

  for (const ref of refs) {
    const item = byIndex.get(ref);
    if (!item) {
      continue;
    }
    const x = toNumberOrNull(item.x);
    const y = toNumberOrNull(item.y);
    const width = toNumberOrNull(item.width);
    const height = toNumberOrNull(item.height);
    if (x === null || y === null || width === null || height === null) {
      continue;
    }
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x + width);
    maxY = Math.max(maxY, y + height);
    found = true;
  }

  if (!found) {
    return null;
  }

  return {
    x: Number(minX.toFixed(3)),
    y: Number(minY.toFixed(3)),
    width: Number((maxX - minX).toFixed(3)),
    height: Number((maxY - minY).toFixed(3)),
  };
}

function readExportJson(filePath) {
  let raw = "";
  try {
    raw = fs.readFileSync(filePath, "utf8");
  } catch (error) {
    throw new AppError(`Unable to read --input-file: ${error.message}`, "E_IO");
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    throw new AppError(`Invalid JSON in --input-file: ${error.message}`, "E_PARSE");
  }
}

function toPageNumber(pageCandidate, fallbackIndex) {
  const page = Number(pageCandidate);
  if (Number.isFinite(page) && page > 0) {
    return page;
  }
  return fallbackIndex + 1;
}

function pageTextFromItems(textItems) {
  if (!Array.isArray(textItems) || textItems.length === 0) {
    return "";
  }
  const ordered = [...textItems].sort((a, b) => {
    const yA = Number.isFinite(Number(a.y)) ? Number(a.y) : Number.POSITIVE_INFINITY;
    const yB = Number.isFinite(Number(b.y)) ? Number(b.y) : Number.POSITIVE_INFINITY;
    if (Math.abs(yA - yB) > 2) {
      return yA - yB;
    }
    const xA = Number.isFinite(Number(a.x)) ? Number(a.x) : Number.POSITIVE_INFINITY;
    const xB = Number.isFinite(Number(b.x)) ? Number(b.x) : Number.POSITIVE_INFINITY;
    return xA - xB;
  });
  return normalizeWhitespace(ordered.map((item) => String(item.text || "")).join(" "));
}

function buildChunkId(docId, page, chunkIndex, text) {
  const hash = crypto
    .createHash("sha1")
    .update(`${docId}|${page}|${chunkIndex}|${text.slice(0, 220)}`)
    .digest("hex")
    .slice(0, 16);
  return `${docId}:p${page}:c${chunkIndex}:${hash}`;
}

function writeOutputFile(filePath, mode, chunks) {
  ensureOutputDir(filePath);
  if (mode === "json") {
    fs.writeFileSync(filePath, JSON.stringify(chunks, null, 2));
    return;
  }
  const lines = chunks.map((chunk) => JSON.stringify(chunk));
  fs.writeFileSync(filePath, `${lines.join("\n")}${lines.length > 0 ? "\n" : ""}`);
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
    if (!outputFile) {
      throw new AppError("--output-file is required", "E_ARGS");
    }

    const chunkSize = options["chunk-size"] ? asInt(options["chunk-size"], "--chunk-size", 64) : 900;
    const chunkOverlap = options["chunk-overlap"] ? asInt(options["chunk-overlap"], "--chunk-overlap", 0) : 180;
    const minChunkSize = options["min-chunk-size"] ? asInt(options["min-chunk-size"], "--min-chunk-size", 1) : 120;
    const maxTextItemRefs = options["max-text-item-refs"]
      ? asInt(options["max-text-item-refs"], "--max-text-item-refs", 1)
      : 40;
    if (chunkOverlap >= chunkSize) {
      throw new AppError("--chunk-overlap must be smaller than --chunk-size", "E_ARGS");
    }

    const input = readExportJson(inputFile);
    if (!Array.isArray(input.pages)) {
      throw new AppError("Export JSON must contain pages[]", "E_PARSE");
    }

    const outputMode =
      options["output-mode"] || (String(outputFile).toLowerCase().endsWith(".json") ? "json" : "jsonl");
    if (outputMode !== "json" && outputMode !== "jsonl") {
      throw new AppError("--output-mode must be 'json' or 'jsonl'", "E_ARGS");
    }

    const docId = String(input.docId || "unknown-doc");
    const source = String(options.source || input.source || "scanservjs-manual-cli");
    const filePath = String(input.filePath || "");
    const parser = String(options.parser || input.parser || "liteparse-cli");
    const parseQuality = String(options["parse-quality"] || (input.quality && input.quality.parseQuality) || "unknown");
    const createdAt = String(options["created-at"] || input.createdAt || new Date().toISOString());

    const chunks = [];
    let chunkIndexGlobal = 0;
    const perPageStats = [];

    for (let pageIdx = 0; pageIdx < input.pages.length; pageIdx += 1) {
      const pageData = input.pages[pageIdx] || {};
      const page = toPageNumber(pageData.page ?? pageData.pageNum, pageIdx);
      const textItems = Array.isArray(pageData.textItems) ? pageData.textItems : [];
      let pageText = normalizeWhitespace(pageData.text || "");
      if (!pageText) {
        pageText = pageTextFromItems(textItems);
      }

      const pageChunks = splitIntoChunks(pageText, chunkSize, chunkOverlap, minChunkSize);
      perPageStats.push({
        page,
        textChars: pageText.length,
        chunkCount: pageChunks.length,
      });

      for (let localChunkIndex = 0; localChunkIndex < pageChunks.length; localChunkIndex += 1) {
        const text = pageChunks[localChunkIndex];
        const refs = collectTextItemRefs(text, textItems, maxTextItemRefs);
        const bbox = buildBbox(textItems, refs);
        const chunk = {
          id: buildChunkId(docId, page, chunkIndexGlobal, text),
          docId,
          source,
          filePath,
          page,
          text,
          chunkIndex: chunkIndexGlobal,
          parser,
          parseQuality,
          createdAt,
        };
        if (bbox) {
          chunk.bbox = bbox;
        }
        if (refs.length > 0) {
          chunk.textItemRefs = refs;
        }
        chunks.push(chunk);
        chunkIndexGlobal += 1;
      }
    }

    writeOutputFile(outputFile, outputMode, chunks);

    const summary = {
      ok: true,
      inputFile: path.resolve(inputFile),
      outputFile: path.resolve(outputFile),
      outputMode,
      docId,
      chunkCount: chunks.length,
      pageCount: input.pages.length,
      parser,
      parseQuality,
      perPageStats,
    };

    if (options["summary-file"]) {
      ensureOutputDir(options["summary-file"]);
      fs.writeFileSync(options["summary-file"], JSON.stringify(summary, null, 2));
    }

    process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
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
