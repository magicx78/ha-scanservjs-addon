#!/usr/bin/env python3
"""scanservjs sorter engine with review-gated Paperless upload."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
from pypdf import PdfReader, PdfWriter

try:
    import anthropic  # type: ignore
except Exception:  # pragma: no cover
    anthropic = None

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None


FINGERPRINT_PROMPT = """Analysiere diesen Seitentext einer PDF-Seite und extrahiere NUR folgendes JSON.
Wenn etwas fehlt: null setzen.
Keine Markdown-Backticks.

{
  "absender": "string|null",
  "empfaenger": "string|null",
  "datum": "YYYY-MM-DD|null",
  "referenz": "string|null",
  "betreff": "string|null",
  "seite_nummer": "number|null",
  "seite_gesamt": "number|null",
  "document_type": "Versicherung|Bank|Finanzamt|Arzt|Sonstiges",
  "beginnt_mitten_im_satz": "boolean",
  "endet_ohne_abschluss": "boolean",
  "confidence": "number between 0 and 1"
}

Seitentext:
"""

DOC_TYPE_MAP = {
    "versicherung": "Versicherung",
    "bank": "Bank",
    "finanzamt": "Finanzamt",
    "arzt": "Arzt",
    "sonstiges": "Sonstiges",
}


@dataclass
class Settings:
    sorter_enable: bool
    threshold: float
    provider: str
    model: str
    paperless_url: str
    paperless_token: str
    inbox_dir: Path
    review_dir: Path
    processed_dir: Path
    state_dir: Path
    ocr_lang: str


class SorterError(RuntimeError):
    pass


class ProviderClient:
    def fingerprint(self, text: str) -> dict[str, Any]:
        raise NotImplementedError


class AnthropicClient(ProviderClient):
    def __init__(self, model: str):
        if anthropic is None:
            raise SorterError("anthropic package not installed")
        self.client = anthropic.Anthropic()
        self.model = model

    def fingerprint(self, text: str) -> dict[str, Any]:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            messages=[{"role": "user", "content": FINGERPRINT_PROMPT + text[:5000]}],
        )
        raw = msg.content[0].text.strip()
        return json.loads(raw)


class OpenAIClient(ProviderClient):
    def __init__(self, model: str):
        if OpenAI is None:
            raise SorterError("openai package not installed")
        self.client = OpenAI()
        self.model = model

    def fingerprint(self, text: str) -> dict[str, Any]:
        rsp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": FINGERPRINT_PROMPT + text[:5000]},
            ],
        )
        raw = rsp.choices[0].message.content or "{}"
        return json.loads(raw)


def normalize_doc_type(value: Optional[str]) -> str:
    if not value:
        return "Sonstiges"
    v = value.strip().lower()
    return DOC_TYPE_MAP.get(v, "Sonstiges")


def read_settings() -> Settings:
    sorter_enable = os.getenv("SORTER_ENABLE", "false").lower() == "true"
    threshold = float(os.getenv("SORTER_CONFIDENCE_THRESHOLD", "75")) / 100.0
    provider = os.getenv("SORTER_PROVIDER", "anthropic").lower()
    model = os.getenv("SORTER_MODEL", "claude-sonnet-4-20250514")
    paperless_url = os.getenv("PAPERLESS_URL", "").strip()
    paperless_token = os.getenv("PAPERLESS_TOKEN", "").strip()

    inbox_dir = Path(os.getenv("SORTER_INBOX_DIR", "/data/output"))
    review_dir = Path(os.getenv("SORTER_REVIEW_DIR", "/data/output"))
    processed_dir = Path(os.getenv("SORTER_PROCESSED_DIR", "/data/processed"))
    state_dir = Path(os.getenv("SORTER_STATE_DIR", "/data/sorter-state"))
    ocr_lang = os.getenv("OCR_LANG", "deu+eng")

    return Settings(
        sorter_enable=sorter_enable,
        threshold=threshold,
        provider=provider,
        model=model,
        paperless_url=paperless_url,
        paperless_token=paperless_token,
        inbox_dir=inbox_dir,
        review_dir=review_dir,
        processed_dir=processed_dir,
        state_dir=state_dir,
        ocr_lang=ocr_lang,
    )


def get_provider_client(settings: Settings) -> ProviderClient:
    if settings.provider == "anthropic":
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise SorterError("ANTHROPIC_API_KEY missing")
        return AnthropicClient(settings.model)
    if settings.provider == "openai":
        if not os.getenv("OPENAI_API_KEY"):
            raise SorterError("OPENAI_API_KEY missing")
        return OpenAIClient(settings.model)
    raise SorterError(f"Unsupported SORTER_PROVIDER={settings.provider}")


def load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"processed_sources": [], "reviews": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def sanitize_filename(text: str) -> str:
    out = re.sub(r"[^\w\- ]", "", text or "")
    out = re.sub(r"\s+", "_", out).strip("_")
    return out[:80] or "Dokument"


def extract_text(page) -> str:
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


def ocr_page_to_text(pdf_path: Path, page_idx: int, ocr_lang: str) -> str:
    with tempfile.TemporaryDirectory(prefix="sorter_ocr_") as tmp:
        ppm_prefix = Path(tmp) / "page"
        ppm_path = Path(tmp) / "page-1.ppm"
        txt_base = Path(tmp) / "ocr"
        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    str(page_idx + 1),
                    "-singlefile",
                    "-r",
                    "300",
                    str(pdf_path),
                    str(ppm_prefix),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["tesseract", str(ppm_path), str(txt_base), "-l", ocr_lang],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            txt_file = Path(f"{txt_base}.txt")
            if txt_file.exists():
                return txt_file.read_text(encoding="utf-8", errors="ignore")
            return ""
        except Exception:
            return ""


def parse_fingerprint(data: dict[str, Any]) -> dict[str, Any]:
    fp = {
        "absender": data.get("absender"),
        "empfaenger": data.get("empfaenger"),
        "datum": data.get("datum"),
        "referenz": data.get("referenz"),
        "betreff": data.get("betreff"),
        "seite_nummer": data.get("seite_nummer"),
        "seite_gesamt": data.get("seite_gesamt"),
        "document_type": normalize_doc_type(data.get("document_type")),
        "beginnt_mitten_im_satz": bool(data.get("beginnt_mitten_im_satz", False)),
        "endet_ohne_abschluss": bool(data.get("endet_ohne_abschluss", False)),
        "confidence": float(data.get("confidence", 0.0) or 0.0),
    }
    return fp


def normalize_string(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    for suffix in [" ag", " gmbh", " se", " kg", " e.v.", " ev", " gbr"]:
        s = s.replace(suffix, "")
    return re.sub(r"\s+", " ", s).strip()


def normalize_ref(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"[^A-Za-z0-9\-]", "", s).upper()


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


def title_similarity(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 0.0
    a = a.lower()
    b = b.lower()
    m = max(len(a), len(b))
    if m == 0:
        return 0.0
    return 1.0 - (levenshtein(a, b) / m)


def pair_score(p1: dict[str, Any], p2: dict[str, Any]) -> float:
    score = 0.0
    r1, r2 = normalize_ref(p1.get("referenz")), normalize_ref(p2.get("referenz"))
    if r1 and r2 and r1 == r2 and len(r1) >= 5:
        score += 0.6

    s1, g1 = p1.get("seite_nummer"), p1.get("seite_gesamt")
    s2, g2 = p2.get("seite_nummer"), p2.get("seite_gesamt")
    if g1 and g2 and g1 == g2 and g1 > 1:
        if s1 and s2 and abs(int(s1) - int(s2)) == 1:
            score += 0.6
        elif s1 and s2:
            score += 0.3

    a1, a2 = normalize_string(p1.get("absender")), normalize_string(p2.get("absender"))
    d1, d2 = p1.get("datum"), p2.get("datum")
    if a1 and a2 and a1 == a2 and len(a1) > 3:
        score += 0.35 if d1 and d2 and d1 == d2 else 0.1

    sim = title_similarity(p1.get("betreff"), p2.get("betreff"))
    if sim >= 0.8:
        score += 0.25
    elif sim >= 0.6:
        score += 0.1

    if p1.get("endet_ohne_abschluss") and p2.get("beginnt_mitten_im_satz"):
        score += 0.15

    t1 = p1.get("document_type", "Sonstiges")
    t2 = p2.get("document_type", "Sonstiges")
    if t1 != "Sonstiges" and t2 != "Sonstiges" and t1 != t2:
        score *= 0.3

    return min(score, 1.0)


def group_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(pages)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    scores: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            sc = pair_score(pages[i], pages[j])
            same_file = pages[i]["source_file"] == pages[j]["source_file"]
            adjacent = pages[j]["source_page_index"] == pages[i]["source_page_index"] + 1
            if same_file and adjacent:
                sc = max(sc, 0.2)
            if sc >= 0.5:
                union(i, j)
                scores[(i, j)] = sc

    groups_map: dict[int, list[int]] = {}
    for i in range(n):
        groups_map.setdefault(find(i), []).append(i)

    output: list[dict[str, Any]] = []
    for idx, members in enumerate(groups_map.values(), 1):
        member_pages = [pages[m] for m in members]

        pair_scores = []
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = min(members[i], members[j]), max(members[i], members[j])
                if (a, b) in scores:
                    pair_scores.append(scores[(a, b)])

        confidence = min(pair_scores) if pair_scores else (1.0 if len(members) == 1 else 0.5)

        member_pages.sort(
            key=lambda p: (
                int(p.get("seite_nummer") or 999),
                p.get("datum") or "0000-00-00",
                p["source_file"],
                p["source_page_index"],
            )
        )

        best = max(member_pages, key=lambda p: sum(1 for k in ["absender", "datum", "betreff", "referenz"] if p.get(k)))

        output.append(
            {
                "group_id": f"GRP_{idx:03d}",
                "confidence": round(float(confidence), 2),
                "needs_review": bool(confidence < 0.75),
                "document_type": best.get("document_type", "Sonstiges"),
                "absender": best.get("absender"),
                "datum": best.get("datum"),
                "betreff": best.get("betreff"),
                "referenz": best.get("referenz"),
                "pages": [
                    {
                        "source_file": p["source_file"],
                        "source_page_index": p["source_page_index"],
                        "source_page_human": p["source_page_human"],
                    }
                    for p in member_pages
                ],
            }
        )

    output.sort(key=lambda g: (g.get("datum") or "0000-00-00", g.get("document_type") or "Sonstiges"))
    return output


class PaperlessClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Token {token}"}
        self._cache: dict[tuple[str, str], int] = {}

    def _get_or_create(self, endpoint: str, name: Optional[str]) -> Optional[int]:
        if not name:
            return None
        name = name.strip()[:128]
        key = (endpoint, name.lower())
        if key in self._cache:
            return self._cache[key]

        resp = requests.get(
            f"{self.base_url}/api/{endpoint}/",
            headers=self.headers,
            params={"name__iexact": name},
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            item_id = int(results[0]["id"])
        else:
            created = requests.post(
                f"{self.base_url}/api/{endpoint}/",
                headers=self.headers,
                json={"name": name},
                timeout=20,
            )
            created.raise_for_status()
            item_id = int(created.json()["id"])
        self._cache[key] = item_id
        return item_id

    def upload(self, pdf_path: Path, meta: dict[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = {"title": build_title(meta)[:128]}
        if meta.get("datum"):
            data["created"] = meta["datum"]

        dt = self._get_or_create("document_types", meta.get("document_type"))
        if dt:
            data["document_type"] = dt

        correspondent = self._get_or_create("correspondents", meta.get("absender"))
        if correspondent:
            data["correspondent"] = correspondent

        tags = meta.get("tags", [])
        if tags:
            tag_ids = []
            for tag in tags:
                tid = self._get_or_create("tags", tag)
                if tid:
                    tag_ids.append(tid)
            if tag_ids:
                data["tags"] = tag_ids

        with pdf_path.open("rb") as f:
            files = {"document": (pdf_path.name, f, "application/pdf")}
            resp = requests.post(
                f"{self.base_url}/api/documents/post_document/",
                headers=self.headers,
                files=files,
                data=data,
                timeout=180,
            )
            resp.raise_for_status()
            return resp.json()


def build_title(meta: dict[str, Any]) -> str:
    datum = meta.get("datum") or "ohne-datum"
    absender = (meta.get("absender") or "Unbekannt").strip()
    betreff = (meta.get("betreff") or meta.get("referenz") or meta.get("document_type") or "Dokument").strip()
    return f"{datum} {absender} - {betreff}"[:128]


def build_tags(meta: dict[str, Any], manual_review: bool) -> list[str]:
    doc_type = (meta.get("document_type") or "Sonstiges").strip()
    datum = (meta.get("datum") or "")
    year = "unknown"
    month = "unknown"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", datum):
        year = datum[:4]
        month = datum[:7]
    tags = [
        f"doctype:{doc_type}",
        f"year:{year}",
        f"month:{month}",
        f"review:{'manual' if manual_review else 'auto'}",
    ]
    return tags


def assemble_group_pdf(group: dict[str, Any], out_path: Path) -> None:
    writer = PdfWriter()
    cache: dict[str, PdfReader] = {}
    for p in group["pages"]:
        src = p["source_file"]
        idx = int(p["source_page_index"])
        if src not in cache:
            cache[src] = PdfReader(src)
        writer.add_page(cache[src].pages[idx])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        writer.write(f)


def fingerprint_pages(client: ProviderClient, settings: Settings, sources: list[Path]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for src in sources:
        reader = PdfReader(str(src))
        for page_idx, page in enumerate(reader.pages):
            text = extract_text(page)
            ocr_used = False
            if len(text.strip()) < 20:
                ocr = ocr_page_to_text(src, page_idx, settings.ocr_lang)
                if len(ocr.strip()) > len(text.strip()):
                    text = ocr
                    ocr_used = True
            if not text.strip():
                fp = {
                    "document_type": "Sonstiges",
                    "confidence": 0.0,
                    "absender": None,
                    "empfaenger": None,
                    "datum": None,
                    "referenz": None,
                    "betreff": None,
                    "seite_nummer": None,
                    "seite_gesamt": None,
                    "beginnt_mitten_im_satz": False,
                    "endet_ohne_abschluss": False,
                }
            else:
                try:
                    fp = parse_fingerprint(client.fingerprint(text))
                except Exception:
                    fp = {
                        "document_type": "Sonstiges",
                        "confidence": 0.0,
                        "absender": None,
                        "empfaenger": None,
                        "datum": None,
                        "referenz": None,
                        "betreff": None,
                        "seite_nummer": None,
                        "seite_gesamt": None,
                        "beginnt_mitten_im_satz": False,
                        "endet_ohne_abschluss": False,
                    }
            pages.append(
                {
                    "source_file": str(src),
                    "source_page_index": page_idx,
                    "source_page_human": page_idx + 1,
                    "ocr_used": ocr_used,
                    **fp,
                }
            )
    return pages


def resolve_sources(settings: Settings, state: dict[str, Any]) -> list[Path]:
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    processed = set(state.get("processed_sources", []))
    files = []
    supported_ext = {".pdf", ".tif", ".tiff", ".jpg", ".jpeg", ".png"}
    for p in sorted(settings.inbox_dir.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in supported_ext:
            continue
        name = p.name
        if name.startswith("REVIEW_"):
            continue
        if name in processed:
            continue
        files.append(p)
    return files


def ensure_pdf_input(source: Path, pdf_dir: Path) -> Path:
    if source.suffix.lower() == ".pdf":
        return source

    pdf_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = pdf_dir / f"{source.stem}.pdf"
    # convert supports tiff/jpg/png and can output multi-page PDF for multipage TIFF.
    subprocess.run(
        ["convert", str(source), str(out_pdf)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return out_pdf


def make_review_filename(group: dict[str, Any]) -> str:
    conf_pct = int(float(group.get("confidence", 0.0)) * 100)
    subject = sanitize_filename(group.get("betreff") or group.get("absender") or group.get("group_id"))
    return f"REVIEW_{group['group_id']}_C{conf_pct:02d}_{subject}.pdf"


def run_sort(settings: Settings) -> dict[str, Any]:
    if not settings.sorter_enable:
        return {"status": "disabled"}

    settings.review_dir.mkdir(parents=True, exist_ok=True)
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    settings.state_dir.mkdir(parents=True, exist_ok=True)

    state_path = settings.state_dir / "state.json"
    lock_path = settings.state_dir / "sorter.lock"
    lock_path.touch(exist_ok=True)

    with lock_path.open("r", encoding="utf-8") as lf:
        try:
            import fcntl

            fcntl.flock(lf, fcntl.LOCK_EX)
        except Exception as exc:
            raise SorterError(f"Unable to lock sorter state: {exc}")

        state = load_state(state_path)
        sources = resolve_sources(settings, state)
        if not sources:
            return {"status": "noop", "message": "no unprocessed pdf sources"}

        client = get_provider_client(settings)
        normalized_pdf_dir = settings.state_dir / "normalized-inputs"
        source_pairs: list[tuple[Path, Path]] = []
        for src in sources:
            source_pairs.append((src, ensure_pdf_input(src, normalized_pdf_dir)))

        pages = fingerprint_pages(client, settings, [p for _, p in source_pairs])
        groups = group_pages(pages)
        paperless = PaperlessClient(settings.paperless_url, settings.paperless_token)

        result = {"uploaded": 0, "review": 0, "failed": 0, "groups": len(groups)}
        now = datetime.utcnow().isoformat() + "Z"
        for group in groups:
            fname = sanitize_filename(group.get("betreff") or group.get("absender") or group["group_id"])
            assembled_name = f"{group['group_id']}_{fname}.pdf"
            assembled_path = settings.state_dir / "assembled" / assembled_name
            assemble_group_pdf(group, assembled_path)

            auto_ok = float(group.get("confidence", 0.0)) >= settings.threshold
            meta = {
                "group_id": group["group_id"],
                "confidence": float(group.get("confidence", 0.0)),
                "needs_review": not auto_ok,
                "title": build_title(group),
                "created": now,
                "document_type": group.get("document_type") or "Sonstiges",
                "correspondent": group.get("absender"),
                "absender": group.get("absender"),
                "datum": group.get("datum"),
                "betreff": group.get("betreff"),
                "source_pages": group.get("pages", []),
            }

            if auto_ok:
                meta["tags"] = build_tags(group, manual_review=False)
                try:
                    paperless.upload(assembled_path, meta)
                    result["uploaded"] += 1
                except Exception as exc:
                    result["failed"] += 1
                    # degrade to manual review artifact
                    review_name = make_review_filename(group)
                    review_pdf = settings.review_dir / review_name
                    shutil.copy2(assembled_path, review_pdf)
                    sidecar = review_pdf.with_suffix(".json")
                    meta["needs_review"] = True
                    meta["state"] = "upload_error"
                    meta["error"] = str(exc)
                    meta["tags"] = build_tags(group, manual_review=True)
                    sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                    state.setdefault("reviews", {})[review_pdf.name] = str(sidecar)
            else:
                review_name = make_review_filename(group)
                review_pdf = settings.review_dir / review_name
                shutil.copy2(assembled_path, review_pdf)
                sidecar = review_pdf.with_suffix(".json")
                meta["state"] = "pending_review"
                meta["tags"] = build_tags(group, manual_review=True)
                sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                state.setdefault("reviews", {})[review_pdf.name] = str(sidecar)
                result["review"] += 1

        processed = set(state.get("processed_sources", []))
        source_archive = settings.processed_dir / "sources"
        source_archive.mkdir(parents=True, exist_ok=True)
        for src, _pdf in source_pairs:
            processed.add(src.name)
            try:
                shutil.move(str(src), str(source_archive / src.name))
            except Exception:
                pass
        state["processed_sources"] = sorted(processed)
        save_state(state_path, state)
        return {"status": "ok", **result}


def approve_review(settings: Settings, review_pdf: Path) -> dict[str, Any]:
    sidecar = review_pdf.with_suffix(".json")
    if not sidecar.exists():
        raise SorterError(f"Missing sidecar for review file: {review_pdf}")

    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["tags"] = build_tags(meta, manual_review=True)
    paperless = PaperlessClient(settings.paperless_url, settings.paperless_token)
    paperless.upload(review_pdf, meta)

    approved_dir = settings.processed_dir / "review-approved"
    approved_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(review_pdf), str(approved_dir / review_pdf.name))
    shutil.move(str(sidecar), str(approved_dir / sidecar.name))

    state_path = settings.state_dir / "state.json"
    state = load_state(state_path)
    state.setdefault("reviews", {}).pop(review_pdf.name, None)
    save_state(state_path, state)
    return {"status": "approved", "file": review_pdf.name}


def reject_review(settings: Settings, review_pdf: Path) -> dict[str, Any]:
    sidecar = review_pdf.with_suffix(".json")
    rejected_dir = settings.processed_dir / "review-rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    if review_pdf.exists():
        shutil.move(str(review_pdf), str(rejected_dir / review_pdf.name))
    if sidecar.exists():
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        meta["state"] = "rejected"
        sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.move(str(sidecar), str(rejected_dir / sidecar.name))

    state_path = settings.state_dir / "state.json"
    state = load_state(state_path)
    state.setdefault("reviews", {}).pop(review_pdf.name, None)
    save_state(state_path, state)
    return {"status": "rejected", "file": review_pdf.name}


def main() -> None:
    parser = argparse.ArgumentParser(description="scanservjs paperless sorter")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")

    a = sub.add_parser("approve")
    a.add_argument("--review-file", required=True)

    r = sub.add_parser("reject")
    r.add_argument("--review-file", required=True)

    args = parser.parse_args()
    settings = read_settings()

    if args.cmd == "run":
        if not settings.paperless_url or not settings.paperless_token:
            raise SorterError("PAPERLESS_URL/PAPERLESS_TOKEN are required")
        print(json.dumps(run_sort(settings), ensure_ascii=False))
    elif args.cmd == "approve":
        if not settings.paperless_url or not settings.paperless_token:
            raise SorterError("PAPERLESS_URL/PAPERLESS_TOKEN are required")
        print(json.dumps(approve_review(settings, Path(args.review_file)), ensure_ascii=False))
    elif args.cmd == "reject":
        print(json.dumps(reject_review(settings, Path(args.review_file)), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        raise
