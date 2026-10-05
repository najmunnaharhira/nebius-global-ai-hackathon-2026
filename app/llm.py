"""Nebius Token Factory client and the three Nemotron-powered steps.

Model routing (all through the Token Factory OpenAI-compatible API):
  * Page reading   -> Nemotron 3 Nano Omni   (images of deeds; fast, multimodal)
  * Text cleanup   -> Nemotron 3 Nano        (pasted / typed deed text)
  * Chain review   -> Nemotron 3 Ultra       (heavy reasoning over the whole case)
  * Checklist      -> Nemotron 3 Super       (structured bilingual output)

Every model ID can be changed with an environment variable, so a newer model
can be swapped in without code changes.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any

import httpx

from .models import ChecklistItem, Document, Flag, TraceStep

BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1").rstrip("/")
MODEL_VISION = os.getenv("DALIL_MODEL_VISION", "nvidia/Nemotron-3-Nano-Omni")
MODEL_FAST = os.getenv("DALIL_MODEL_FAST", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
MODEL_REASON = os.getenv("DALIL_MODEL_REASON", "nvidia/Nemotron-3-Ultra-550b-a55b")
MODEL_CHECKLIST = os.getenv("DALIL_MODEL_CHECKLIST", "nvidia/nemotron-3-super-120b-a12b")
TIMEOUT = float(os.getenv("DALIL_TIMEOUT", "120"))


def api_key() -> str | None:
    return os.getenv("NEBIUS_API_KEY") or None


def is_live() -> bool:
    return api_key() is not None


class LLMError(RuntimeError):
    pass


def _strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def parse_json(text: str) -> Any:
    """Parse the first JSON object in a model reply (tolerates code fences and preambles)."""
    text = _strip_thinking(text)
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start == -1:
        raise LLMError("Model reply contained no JSON object")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise LLMError("Model reply had an unterminated JSON object")


def chat(model: str, messages: list[dict], max_tokens: int = 2048, temperature: float = 0.1) -> tuple[str, int]:
    """Call Token Factory chat completions. Returns (content, latency_ms)."""
    key = api_key()
    if not key:
        raise LLMError("NEBIUS_API_KEY is not set")
    t0 = time.perf_counter()
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
    latency = int((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        raise LLMError(f"Token Factory returned {r.status_code}: {r.text[:300]}")
    content = r.json()["choices"][0]["message"].get("content") or ""
    return content, latency


# ---------------------------------------------------------------- extraction

EXTRACT_SCHEMA = """Return ONLY a JSON object with these keys (use null when a value is not on the page):
{
  "doc_type": "khatian" | "deed" | "mutation",
  "title": short description,
  "date": "YYYY-MM-DD" (registration date for a deed, record/order date otherwise),
  "mouza": string, "khatian_no": string, "deed_no": string, "registry_office": string,
  "owners": [{"name": str, "father": str|null, "share": number|null}]   // khatian owners or new owners in a mutation; share as a fraction (8 annas = 0.5)
  "sellers": [{"name": str, "father": str|null}],                         // deeds only
  "buyers":  [{"name": str, "father": str|null}],                         // deeds only
  "parcels": [{"dag": str, "area_decimal": number}],                      // area converted to decimals (1 katha = 1.65 decimals, 1 bigha = 33 decimals, 1 acre = 100 decimals)
  "notes": anything unusual or illegible
}
Write names in the script used on the document. Convert Bangla digits to ASCII digits. Never invent values."""

EXTRACT_SYSTEM = (
    "You read Bangladeshi land documents (dalil / sale deeds, khatian / record of rights, "
    "and mutation / namjari papers) and extract structured fields for a buyer's pre-check. "
    + EXTRACT_SCHEMA
)


def _to_document(data: dict, doc_id: str, source: str, model: str) -> Document:
    data = {k: v for k, v in data.items() if v is not None}
    for key in ("owners", "sellers", "buyers", "parcels"):
        data[key] = [x for x in data.get(key) or [] if isinstance(x, dict)]
    for p in data["parcels"]:
        p["dag"] = str(p.get("dag", "")).strip()
        try:
            p["area_decimal"] = float(p.get("area_decimal") or 0)
        except (TypeError, ValueError):
            p["area_decimal"] = 0.0
    if data.get("doc_type") not in ("khatian", "deed", "mutation"):
        data["doc_type"] = "deed"
    return Document(id=doc_id, source_file=source, extracted_by=model, **{
        k: v for k, v in data.items() if k in Document.model_fields and k not in ("id", "source_file", "extracted_by")
    })


def extract_from_image(image_bytes: bytes, mime: str, doc_id: str, filename: str) -> tuple[Document, TraceStep]:
    b64 = base64.b64encode(image_bytes).decode()
    content, ms = chat(
        MODEL_VISION,
        [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract the fields from this document page."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ],
        max_tokens=1500,
    )
    doc = _to_document(parse_json(content), doc_id, filename, MODEL_VISION)
    return doc, TraceStep(step=f"Read page: {filename}", model=MODEL_VISION, status="ok", latency_ms=ms)


def extract_from_text(text: str, doc_id: str, filename: str) -> tuple[Document, TraceStep]:
    content, ms = chat(
        MODEL_FAST,
        [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": f"Document text:\n\n{text[:20000]}"},
        ],
        max_tokens=1500,
    )
    doc = _to_document(parse_json(content), doc_id, filename, MODEL_FAST)
    return doc, TraceStep(step=f"Read text: {filename}", model=MODEL_FAST, status="ok", latency_ms=ms)


# ---------------------------------------------------------------- reasoning

REVIEW_SYSTEM = """You are a careful land-title analyst helping a buyer in Bangladesh do a pre-check before a purchase.
You get (1) the structured documents of a case, (2) red flags already found by a deterministic rules engine,
and (3) the ownership holdings the engine computed. Your job:
- Explain each existing flag in plain language for a non-lawyer buyer (1-2 sentences, say why it matters).
- Look for additional concerns the rules may have missed (e.g. inconsistent father's names, suspicious gaps in time,
  shares that don't add up, a deed by a person who should have been deceased). Only raise concerns grounded in the data.
- Write a short overall summary in English and the same summary in Bangla.
Never give a final legal verdict. Return ONLY JSON:
{"summary_en": str, "summary_bn": str,
 "explanations": {"<flag id>": str, ...},
 "additional_flags": [{"severity": "high"|"medium"|"low", "title": str, "detail": str}]}"""


def review_chain(documents: list[Document], flags: list[Flag], holdings: list) -> tuple[dict, TraceStep]:
    payload = {
        "documents": [d.model_dump(exclude_none=True) for d in documents],
        "flags": [f.model_dump(exclude_none=True) for f in flags],
        "holdings": [h.model_dump() for h in holdings],
    }
    content, ms = chat(
        MODEL_REASON,
        [
            {"role": "system", "content": REVIEW_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        max_tokens=4096,
    )
    data = parse_json(content)
    return data, TraceStep(step="Review ownership chain", model=MODEL_REASON, status="ok", latency_ms=ms)


CHECKLIST_SYSTEM = """You turn a land pre-check into a practical to-do list for a buyer in Bangladesh.
You get the red flags and a draft checklist (English + Bangla). Merge duplicates, make each item specific to
this case (names, dag numbers, deed numbers), order by urgency, and keep it under 12 items.
Keep every Bangla item natural and accurate. Return ONLY JSON:
{"items": [{"en": str, "bn": str, "priority": "must"|"should", "related_flag": str|null}]}"""


def refine_checklist(flags: list[Flag], draft: list[ChecklistItem]) -> tuple[list[ChecklistItem], TraceStep]:
    payload = {
        "flags": [f.model_dump(exclude_none=True) for f in flags],
        "draft": [i.model_dump(exclude_none=True) for i in draft],
    }
    content, ms = chat(
        MODEL_CHECKLIST,
        [
            {"role": "system", "content": CHECKLIST_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        max_tokens=3000,
    )
    items = [ChecklistItem(**i) for i in parse_json(content).get("items", []) if i.get("en") and i.get("bn")]
    if not items:
        raise LLMError("Checklist model returned no items")
    return items, TraceStep(step="Write bilingual checklist", model=MODEL_CHECKLIST, status="ok", latency_ms=ms)
