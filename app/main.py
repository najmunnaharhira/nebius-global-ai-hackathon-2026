"""Dalil API: upload land papers, rebuild the ownership chain, flag risks."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import llm
from .chain import analyze_chain
from .checklist import build_checklist
from .models import AnalysisResult, CaseInput, Flag, TraceStep

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
STATIC = ROOT / "static"

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_BYTES = 8 * 1024 * 1024

app = FastAPI(title="Dalil", description="AI land-deed pre-check for Bangladesh")


@app.get("/api/status")
def status():
    return {
        "live": llm.is_live(),
        "models": {
            "vision": llm.MODEL_VISION,
            "fast": llm.MODEL_FAST,
            "reasoning": llm.MODEL_REASON,
            "checklist": llm.MODEL_CHECKLIST,
        },
        "base_url": llm.BASE_URL,
    }


@app.get("/api/samples")
def list_samples():
    out = []
    for p in sorted(SAMPLES.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        out.append({"id": p.stem, "name": data.get("name", p.stem), "description": data.get("description", "")})
    return out


@app.get("/api/samples/{sample_id}")
def get_sample(sample_id: str):
    path = SAMPLES / f"{sample_id}.json"
    if not path.resolve().is_relative_to(SAMPLES.resolve()) or not path.exists():
        raise HTTPException(404, "Sample not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/extract")
async def extract(files: list[UploadFile] = File(...)):
    if not llm.is_live():
        raise HTTPException(
            503,
            "Reading uploads needs a Nebius Token Factory key (NEBIUS_API_KEY). "
            "You can still try the sample cases.",
        )
    documents, trace = [], []
    for f in files:
        data = await f.read()
        if len(data) > MAX_BYTES:
            trace.append(TraceStep(step=f"Read: {f.filename}", status="error", note="File is larger than 8 MB"))
            continue
        doc_id = f"D{uuid.uuid4().hex[:6]}"
        try:
            if (f.content_type or "") in IMAGE_TYPES:
                doc, step = llm.extract_from_image(data, f.content_type, doc_id, f.filename or doc_id)
            elif (f.content_type or "").startswith("text/") or (f.filename or "").endswith(".txt"):
                doc, step = llm.extract_from_text(data.decode("utf-8", "replace"), doc_id, f.filename or doc_id)
            else:
                trace.append(TraceStep(step=f"Read: {f.filename}", status="error",
                                       note="Upload a JPG/PNG/WebP photo or a .txt file"))
                continue
            documents.append(doc)
            trace.append(step)
        except Exception as e:  # keep going with the other pages
            trace.append(TraceStep(step=f"Read: {f.filename}", status="error", note=str(e)[:200]))
    return {"documents": [d.model_dump() for d in documents], "trace": [t.model_dump() for t in trace]}


def _fallback_summary(risk: str, flags: list[Flag]) -> tuple[str, str]:
    high = sum(f.severity == "high" for f in flags)
    if not flags:
        return (
            "The documents form a complete, consistent ownership chain. Still complete the checklist before paying.",
            "দলিলগুলো থেকে মালিকানার ধারাবাহিকতা সম্পূর্ণ ও সামঞ্জস্যপূর্ণ দেখা যাচ্ছে। তবুও টাকা দেওয়ার আগে তালিকার সব যাচাই সম্পন্ন করুন।",
        )
    return (
        f"Dalil found {len(flags)} issue(s), {high} of them serious. Overall risk: {risk}. "
        "Resolve the flagged items before paying any advance.",
        f"দলিল {len(flags)}টি সমস্যা পেয়েছে, যার {high}টি গুরুতর। সামগ্রিক ঝুঁকি: "
        f"{ {'high': 'উচ্চ', 'medium': 'মাঝারি', 'low': 'কম'}[risk] }। কোনো বায়না দেওয়ার আগে চিহ্নিত বিষয়গুলোর সমাধান করুন।",
    )


@app.post("/api/analyze", response_model=AnalysisResult)
def analyze(case: CaseInput):
    if not case.documents:
        raise HTTPException(400, "Add at least one document")

    engine = analyze_chain(case.documents, case.proposed)
    flags = engine.flags
    holdings = engine.holdings_list()
    trace = [TraceStep(step="Rebuild chain and run red-flag rules", status="rules",
                       note=f"{len(flags)} flag(s) from deterministic checks")]

    summary_en, summary_bn = _fallback_summary(engine.risk(), flags)

    if llm.is_live():
        try:
            review, step = llm.review_chain(case.documents, flags, holdings)
            trace.append(step)
            summary_en = review.get("summary_en") or summary_en
            summary_bn = review.get("summary_bn") or summary_bn
            explanations = review.get("explanations") or {}
            for f in flags:
                f.explanation = explanations.get(f.id)
            for extra in review.get("additional_flags") or []:
                sev = extra.get("severity") if extra.get("severity") in ("high", "medium", "low") else "medium"
                flags.append(Flag(id=f"F{len(flags) + 1}", code="AI_REVIEW", severity=sev,
                                  title=str(extra.get("title", "Additional concern"))[:120],
                                  detail=str(extra.get("detail", ""))[:600]))
        except Exception as e:
            trace.append(TraceStep(step="Review ownership chain", model=llm.MODEL_REASON, status="error",
                                   note=str(e)[:200]))
    else:
        trace.append(TraceStep(step="Review ownership chain", model=llm.MODEL_REASON, status="skipped",
                               note="No NEBIUS_API_KEY set"))

    checklist = build_checklist(flags)
    if llm.is_live():
        try:
            checklist, step = llm.refine_checklist(flags, checklist)
            trace.append(step)
        except Exception as e:
            trace.append(TraceStep(step="Write bilingual checklist", model=llm.MODEL_CHECKLIST, status="error",
                                   note=f"Used template checklist: {str(e)[:150]}"))
    else:
        trace.append(TraceStep(step="Write bilingual checklist", model=llm.MODEL_CHECKLIST, status="skipped",
                               note="Used template checklist"))

    sev = {f.severity for f in flags}
    risk = "high" if "high" in sev else "medium" if "medium" in sev else "low"
    return AnalysisResult(
        risk=risk, flags=flags, timeline=engine.timeline, holdings=holdings,
        checklist=checklist, summary_en=summary_en, summary_bn=summary_bn, trace=trace,
    )


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
