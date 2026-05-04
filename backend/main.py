"""FastAPI backend.

Endpoints
---------
POST  /api/upload                     -> parse file, create session
GET   /api/skills                     -> list available journal skills
POST  /api/sessions/{sid}/predict_journal -> rank candidate journals
POST  /api/sessions/{sid}/comprehend  -> ComprehensionAgent
POST  /api/sessions/{sid}/comprehension/confirm -> user confirms / corrects
POST  /api/sessions/{sid}/plan        -> PlannerAgent
POST  /api/sessions/{sid}/plan/approve -> user approves plan
POST  /api/sessions/{sid}/edit/{tid}  -> EditorAgent for one TODO
POST  /api/sessions/{sid}/auto_grammar -> GrammarAutoFixer batch run
POST  /api/sessions/{sid}/decide      -> accept/reject/modify a suggestion
POST  /api/sessions/{sid}/compact     -> SummarizerAgent
POST  /api/sessions/{sid}/review_report -> ReviewReporter (full report)
POST  /api/sessions/{sid}/ai_detect   -> AIDetector (stateless, no-mem)
GET   /api/sessions/{sid}             -> full session JSON
GET   /api/sessions/{sid}/source      -> raw source text (for preview)
GET   /api/sessions/{sid}/export      -> ?format=latex|docx download
GET   /api/logs                       -> recent server log lines (snapshot)
GET   /api/logs/stream                -> SSE: live log lines
GET   /api/sessions/{sid}/progress    -> SSE: progress events for this session

Concurrency model
-----------------
Long-running LLM calls are wrapped in `asyncio.to_thread` so they don't
block the event loop. SSE streams emit progress events via per-session
asyncio.Queue.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from paper_agent.agents import (
    ComprehensionAgent,
    EditorAgent,
    PlannerAgent,
    SummarizerAgent,
)
from paper_agent.agents.tool_agent import ToolAgent, ToolAgentResult
from paper_agent.agents.schema import ComprehensionCard, Plan, TodoItem
from paper_agent.export import DocxExporter, LaTeXExporter
from paper_agent.llm import LLMClient, LLMConfig, ModelTier
from paper_agent.parsers import LaTeXParser, WordParser
from paper_agent.services import (
    AIDetector,
    GrammarAutoFixer,
    JournalPredictor,
    ReviewReporter,
)
from paper_agent.session import Session
from paper_agent.skills import SkillLoader
from paper_agent import runtime_config

from .store import STORE, get_log_handler, read_log_history


_LOGGER = logging.getLogger("paper_agent.api")
_log = get_log_handler()  # initialize logging early

UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="Paper-Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Per-session SSE progress queues (populated by long-running endpoints).
PROGRESS_QUEUES: dict[str, asyncio.Queue] = {}


def _q_for(sid: str) -> asyncio.Queue:
    q = PROGRESS_QUEUES.get(sid)
    if q is None:
        q = asyncio.Queue(maxsize=200)
        PROGRESS_QUEUES[sid] = q
    return q


def _emit(sid: str, kind: str, **payload) -> None:
    q = PROGRESS_QUEUES.get(sid)
    if q is None:
        return
    try:
        q.put_nowait(json.dumps({"kind": kind, "ts": time.time(), **payload}))
    except asyncio.QueueFull:
        pass


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _llm() -> LLMClient:
    return LLMClient(LLMConfig())


def _need_session(sid: str) -> Session:
    s = STORE.get(sid)
    if s is None:
        raise HTTPException(404, f"session {sid} not found")
    return s


def _need_skill(key: str):
    try:
        return SkillLoader().load(key)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------

class ConfirmComprehensionBody(BaseModel):
    user_corrections: str = ""


class ApprovePlanBody(BaseModel):
    edited_plan: Optional[dict] = None  # if user tweaked todos client-side


class DecideBody(BaseModel):
    suggestion_id: str
    decision: str                       # accepted|rejected|modified
    modified_after: Optional[str] = None


class EditBody(BaseModel):
    language: str = "en"
    tier: str = "smart"                 # fast|smart|deep
    model: Optional[str] = None         # explicit model id from /api/models
    use_tools: bool = True              # True = ToolAgent (ReAct), False = EditorAgent (batch)


class PlanBody(BaseModel):
    tier: str = "deep"
    model: Optional[str] = None


class ReportBody(BaseModel):
    language: str = "en"
    tier: str = "deep"
    model: Optional[str] = None


class ComprehendBody(BaseModel):
    tier: str = "smart"
    model: Optional[str] = None


class PredictBody(BaseModel):
    candidates: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"ok": True, "version": "0.1.0"}


# ---------------------------------------------------------------------------
# Runtime configuration -- editable from the Web UI / Settings page
# ---------------------------------------------------------------------------

class ConfigPatch(BaseModel):
    api_key: Optional[str] = None       # empty = leave unchanged; "__clear__" = reset
    base_url: Optional[str] = None
    fast_model: Optional[str] = None
    smart_model: Optional[str] = None
    deep_model: Optional[str] = None


@app.get("/api/config")
async def get_config():
    """Return the effective LLM config (api_key masked)."""
    return runtime_config.merged().to_public_dict()


@app.post("/api/config")
async def update_config(body: ConfigPatch):
    """Update the persisted LLM config. Empty fields are left unchanged."""
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    runtime_config.update(patch)
    _LOGGER.info(
        "config updated: keys=%s",
        sorted(k for k, v in patch.items() if k != "api_key" or v),
    )
    return runtime_config.merged().to_public_dict()


@app.post("/api/config/test")
async def test_config():
    """Smoke-test the current config by listing models from the upstream."""
    client = LLMClient(LLMConfig())  # uses fresh runtime_config

    def _go():
        return client.list_models()

    try:
        ids = await asyncio.to_thread(_go)
        return {"ok": True, "model_count": len(ids), "sample": ids[:5]}
    except Exception as e:  # pragma: no cover -- depends on network
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Models -- auto-discovered from the OpenAI-compatible endpoint
# ---------------------------------------------------------------------------

@app.get("/api/models")
async def list_models():
    """Return the list of model ids the upstream LLM endpoint advertises.

    Falls back to the configured presets if `/v1/models` is unavailable.
    Also returns the current default tier->model mapping so the UI can
    show "FAST = X / SMART = Y / DEEP = Z".
    """
    client = _llm()

    def _go():
        return client.list_models()

    ids = await asyncio.to_thread(_go)

    def _safe_preset(tier: ModelTier) -> str:
        try:
            return client.model_for(tier)
        except RuntimeError:
            return ""

    return {
        "models": ids,
        "presets": {
            "fast":  _safe_preset(ModelTier.FAST),
            "smart": _safe_preset(ModelTier.SMART),
            "deep":  _safe_preset(ModelTier.DEEP),
        },
    }


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

@app.get("/api/skills")
async def list_skills():
    loader = SkillLoader()
    out = []
    for key in loader.list_skills():
        s = loader.load(key)
        jrn = s.raw.get("journal", {})
        out.append(_skill_summary(s, jrn))
    return {"skills": out}


@app.get("/api/skills/{key}")
async def get_skill(key: str):
    loader = SkillLoader()
    try:
        s = loader.load(key)
    except FileNotFoundError:
        raise HTTPException(404, f"skill '{key}' not found")
    jrn = s.raw.get("journal", {})
    return {
        **_skill_summary(s, jrn),
        "structure_rules":  s.structure_rules,
        "content_rules":    s.content_rules,
        "compliance_rules": s.compliance_rules,
        "language_rules":   s.language_rules,
        "declarations":     s.raw.get("checklist", {}).get("declarations_required", []),
        "reference_style":  s.raw.get("format", {}).get("reference_style", ""),
        "reference_format": s.raw.get("format", {}).get("reference_format", ""),
        "submission_url":   s.raw.get("submission", {}).get("url", ""),
        "figures_notes":    s.raw.get("figures", {}).get("notes", ""),
        "sections_notes":   s.raw.get("sections", {}).get("notes", ""),
    }


class CreateSkillBody(BaseModel):
    key: str          # filename stem, e.g. "my_journal"
    yaml_content: str # full YAML text


@app.post("/api/skills")
async def create_skill(body: CreateSkillBody):
    """Save a user-defined journal skill as a YAML file."""
    import re as _re
    import yaml as _yaml
    # Validate key
    if not _re.match(r'^[a-z0-9_]+$', body.key):
        raise HTTPException(400, "key must be lowercase letters, digits and underscores only")
    # Validate YAML parseable
    try:
        _yaml.safe_load(body.yaml_content)
    except Exception as e:
        raise HTTPException(400, f"Invalid YAML: {e}")
    from paper_agent.skills.loader import SkillLoader
    from pathlib import Path as _Path
    here = _Path(__file__).resolve().parents[1]
    out_dir = here / "skills" / "journals"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{body.key}.yaml"
    out_path.write_text(body.yaml_content, encoding="utf-8")
    # Reload to verify
    loader = SkillLoader()
    s = loader.load(body.key)
    jrn = s.raw.get("journal", {})
    return {"ok": True, "skill": _skill_summary(s, jrn)}


def _skill_summary(s, jrn: dict) -> dict:
    return {
        "key":              s.key,
        "name":             s.name,
        "publisher":        jrn.get("publisher", ""),
        "url":              jrn.get("url", ""),
        "impact_factor":    jrn.get("impact_factor"),
        "open_access":      jrn.get("open_access", False),
        "disciplines":      list(jrn.get("discipline", [])),
        "scope":            s.raw.get("scope", {}).get("description", ""),
        "scope_keywords":   list(s.raw.get("scope", {}).get("keywords", [])),
        "required_sections": s.required_sections(),
        "article_types":    [
            {
                "type":         t.get("type", ""),
                "word_limit":   t.get("word_limit"),
                "abstract_limit": t.get("abstract_limit"),
                "figures_max":  t.get("figures_max"),
                "tables_max":   t.get("tables_max"),
                "references_max": t.get("references_max"),
                "pages_max":    t.get("pages_max"),
                "notes":        t.get("notes", ""),
            }
            for t in s.article_types()
        ],
    }


# ---------------------------------------------------------------------------
# Sessions list (scans disk so it survives server restarts)
# ---------------------------------------------------------------------------

@app.get("/api/sessions")
async def list_sessions():
    """Return lightweight summaries for every session found on disk."""
    from paper_agent.session import SESSION_DIR
    items = []
    for p in sorted(SESSION_DIR.glob("sess-*.json"),
                    key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            suggs = d.get("suggestions", {})
            n_total = len(suggs)
            n_accepted = sum(1 for s in suggs.values() if s.get("status") == "accepted")
            n_pending  = sum(1 for s in suggs.values() if s.get("status") == "pending")
            items.append({
                "id":           d["id"],
                "journal_key":  d.get("journal_key", ""),
                "source_type":  d.get("source_type", ""),
                "created_at":   d.get("created_at", 0),
                "plan_approved":d.get("plan_approved", False),
                "n_suggestions":n_total,
                "n_accepted":   n_accepted,
                "n_pending":    n_pending,
            })
        except Exception:
            continue
    return {"sessions": items}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    journal_key: str = Form(""),
):
    """Save uploaded file, parse it, create a session.

    `journal_key` may be empty if the user wants the agent to auto-pick
    via /api/sessions/{sid}/predict_journal.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".tex", ".docx"}:
        raise HTTPException(400, "only .tex and .docx are supported")

    sess_id_seed = f"sess-{int(time.time()*1000)}"
    out_path = UPLOAD_DIR / f"{sess_id_seed}{suffix}"
    with out_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    src_type = "latex" if suffix == ".tex" else "docx"
    if src_type == "latex":
        text = out_path.read_text(encoding="utf-8", errors="replace")
        tree = LaTeXParser().parse(text)
    else:
        tree = WordParser().parse_file(str(out_path))

    sess = Session.new(journal_key or "", str(out_path), src_type)
    STORE.put(sess, tree)
    _LOGGER.info("uploaded %s as session %s (%d sections, %d paragraphs)",
                 file.filename, sess.id, len(list(tree.toc())),
                 sum(1 for _ in tree.all_paragraphs()))
    return {
        "session_id": sess.id,
        "source_type": src_type,
        "stats": tree.stats(),
        "toc": tree.toc(),
        "title": tree.title,
    }


# ---------------------------------------------------------------------------
# Phase 0 -- Comprehension
# ---------------------------------------------------------------------------

@app.post("/api/sessions/{sid}/comprehend")
async def comprehend(sid: str, body: ComprehendBody = ComprehendBody()):
    sess = _need_session(sid)
    tree = STORE.tree(sid)
    tier = _TIER.get(body.tier, ModelTier.SMART)
    if tree is None:
        raise HTTPException(500, "tree not loaded")
    _emit(sid, "stage_started", stage="comprehension")

    def _go():
        return ComprehensionAgent(_llm()).run(tree, tier=tier, model=body.model)

    card: ComprehensionCard = await asyncio.to_thread(_go)
    sess.comprehension = card
    sess.log("comprehension_generated", title=card.title, confidence=card.confidence)
    STORE.save(sid)
    _emit(sid, "stage_done", stage="comprehension")
    return {"comprehension": card.to_dict()}


@app.post("/api/sessions/{sid}/comprehension/confirm")
async def confirm_comprehension(sid: str, body: ConfirmComprehensionBody):
    sess = _need_session(sid)
    if sess.comprehension is None:
        raise HTTPException(400, "run /comprehend first")
    sess.comprehension_confirmed = True
    sess.user_corrections = body.user_corrections or ""
    sess.log("comprehension_confirmed", corrections=sess.user_corrections[:200])
    STORE.save(sid)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Journal prediction
# ---------------------------------------------------------------------------

@app.post("/api/sessions/{sid}/predict_journal")
async def predict_journal(sid: str, body: PredictBody):
    sess = _need_session(sid)
    tree = STORE.tree(sid)
    _emit(sid, "stage_started", stage="predict_journal")

    def _go():
        return JournalPredictor(_llm()).rank(
            tree, comprehension=sess.comprehension, candidates=body.candidates
        )

    ranking = await asyncio.to_thread(_go)
    sess.log("journal_ranked", top_pick=ranking.top_pick)
    STORE.save(sid)
    _emit(sid, "stage_done", stage="predict_journal", top_pick=ranking.top_pick)
    return ranking.to_dict()


# ---------------------------------------------------------------------------
# Phase 1 -- Plan
# ---------------------------------------------------------------------------

@app.post("/api/sessions/{sid}/plan")
async def make_plan(sid: str, body: PlanBody = PlanBody()):
    sess = _need_session(sid)
    if not sess.comprehension_confirmed:
        raise HTTPException(400, "confirm comprehension first")
    if not sess.journal_key:
        raise HTTPException(400, "no journal_key set; pick a journal or run predict_journal")
    skill = _need_skill(sess.journal_key)
    tree = STORE.tree(sid)
    _emit(sid, "stage_started", stage="plan")

    tier = _TIER.get(body.tier, ModelTier.DEEP)

    def _go():
        return PlannerAgent(_llm()).run(
            tree, skill, sess.comprehension, sess.user_corrections,
            tier=tier, model=body.model,
        )

    plan: Plan = await asyncio.to_thread(_go)
    sess.plan = plan
    sess.log("plan_generated", n_todos=len(plan.todos), risks=len(plan.risks))
    STORE.save(sid)
    _emit(sid, "stage_done", stage="plan", n_todos=len(plan.todos))
    return {"plan": plan.to_dict()}


@app.post("/api/sessions/{sid}/plan/approve")
async def approve_plan(sid: str, body: ApprovePlanBody):
    sess = _need_session(sid)
    if sess.plan is None:
        raise HTTPException(400, "run /plan first")
    if body.edited_plan is not None:
        sess.plan = Plan.from_dict(body.edited_plan)
    sess.plan_approved = True
    sess.log("plan_approved", n_todos=len(sess.plan.todos))
    STORE.save(sid)
    return {"ok": True, "plan": sess.plan.to_dict()}


# ---------------------------------------------------------------------------
# Phase 2 -- Editor (per-TODO)
# ---------------------------------------------------------------------------

_TIER = {"fast": ModelTier.FAST, "smart": ModelTier.SMART, "deep": ModelTier.DEEP}


@app.post("/api/sessions/{sid}/edit/{todo_id}")
async def run_editor(sid: str, todo_id: str, body: EditBody):
    sess = _need_session(sid)
    if sess.plan is None:
        raise HTTPException(400, "no plan")
    todo = sess.todo(todo_id)
    if todo is None:
        raise HTTPException(404, f"todo {todo_id} not found")
    skill = _need_skill(sess.journal_key)
    tree = STORE.tree(sid)
    tier = _TIER.get(body.tier, ModelTier.SMART)
    _emit(
        sid, "stage_started", stage="edit",
        todo_id=todo_id, todo_title=todo.title,
        model=body.model or "(tier default)", use_tools=body.use_tools,
    )

    if body.use_tools:
        def on_tool_call(tc):
            _emit(
                sid, "tool_call",
                todo_id=todo_id,
                tool=tc.tool,
                args=tc.args,
                summary=tc.result_summary,
                result=tc.result,
                error=tc.error,
            )

        def _go_tool():
            return ToolAgent(_llm()).run(
                todo, tree, skill,
                compact_memory=sess.memory.compact_summary,
                tier=tier,
                language=body.language,
                model=body.model,
                on_tool_call=on_tool_call,
            )

        result: ToolAgentResult = await asyncio.to_thread(_go_tool)
        sess.tool_log.extend(result.tool_calls)
        sess.add_suggestions(result.suggestions)
        sess.set_todo_status(todo_id, "in_progress", notes=result.notes[:200])
        STORE.save(sid)
        _emit(sid, "stage_done", stage="edit", todo_id=todo_id,
              n_suggestions=len(result.suggestions), n_tool_calls=len(result.tool_calls))
        asyncio.create_task(_auto_compact(sid))
        return {
            "todo_id": result.todo_id,
            "suggestions": [s.to_dict() for s in result.suggestions],
            "tool_calls": [t.to_dict() for t in result.tool_calls],
            "notes": result.notes,
        }
    else:
        def on_batch(batch_idx: int, batch_total: int, paragraphs_done: int, sugs):
            _emit(
                sid, "edit_batch",
                todo_id=todo_id, batch_idx=batch_idx,
                batch_total=batch_total, paragraphs_done=paragraphs_done,
                new_suggestions=len(sugs),
            )

        plan_summary = sess.plan.overall_strategy if sess.plan else ""
        def _go_batch():
            return EditorAgent(_llm()).run(
                todo, tree, skill,
                compact_memory=sess.memory.compact_summary,
                plan_summary=plan_summary,
                tier=tier, language=body.language, model=body.model,
                on_batch=on_batch,
            )

        batch_result = await asyncio.to_thread(_go_batch)
        sess.add_suggestions(batch_result.suggestions)
        sess.set_todo_status(todo_id, "in_progress", notes=" ".join(batch_result.notes)[:200])
        STORE.save(sid)
        _emit(sid, "stage_done", stage="edit", todo_id=todo_id,
              n_suggestions=len(batch_result.suggestions))
        asyncio.create_task(_auto_compact(sid))
        return {
            "todo_id": batch_result.todo_id,
            "suggestions": [s.to_dict() for s in batch_result.suggestions],
            "notes": batch_result.notes,
        }


@app.post("/api/sessions/{sid}/auto_grammar")
async def auto_grammar(sid: str, body: EditBody):
    sess = _need_session(sid)
    if not sess.journal_key:
        raise HTTPException(400, "set journal first")
    skill = _need_skill(sess.journal_key)
    tree = STORE.tree(sid)
    tier = _TIER.get(body.tier, ModelTier.FAST)
    _emit(sid, "stage_started", stage="auto_grammar")

    def _go():
        return GrammarAutoFixer(_llm()).run(
            tree, skill,
            compact_memory=sess.memory.compact_summary,
            language=body.language,
            tier=tier,
        )

    result = await asyncio.to_thread(_go)
    sess.add_suggestions(result.suggestions)
    sess.log("auto_grammar_run", n=len(result.suggestions))
    STORE.save(sid)
    _emit(sid, "stage_done", stage="auto_grammar", n=len(result.suggestions))
    return {"suggestions": [s.to_dict() for s in result.suggestions]}


@app.post("/api/sessions/{sid}/decide")
async def decide(sid: str, body: DecideBody):
    sess = _need_session(sid)
    if body.decision not in {"accepted", "rejected", "modified"}:
        raise HTTPException(400, "decision must be accepted|rejected|modified")
    if body.suggestion_id not in sess.suggestions:
        raise HTTPException(404, "suggestion not found")
    sess.set_suggestion_status(body.suggestion_id, body.decision, body.modified_after)
    STORE.save(sid)
    return {"ok": True}


async def _auto_compact(sid: str) -> None:
    """Fire-and-forget compact triggered automatically after each edit."""
    try:
        sess = _need_session(sid)
        _emit(sid, "stage_started", stage="compact")
        def _go():
            return SummarizerAgent(_llm()).compact(sess)
        result = await asyncio.to_thread(_go)
        if isinstance(result, tuple):
            _, n_new = result
        else:
            n_new = 0
        sess.log("compact", entries=n_new)
        STORE.save(sid)
        _emit(sid, "stage_done", stage="compact", entries=n_new)
    except Exception:
        pass


@app.post("/api/sessions/{sid}/compact")
async def compact(sid: str):
    sess = _need_session(sid)
    _emit(sid, "stage_started", stage="compact")

    def _go():
        return SummarizerAgent(_llm()).compact(sess)

    result = await asyncio.to_thread(_go)
    mem, n_new = result if isinstance(result, tuple) else (result, 0)
    sess.log("compact", entries=n_new)
    STORE.save(sid)
    _emit(sid, "stage_done", stage="compact", entries=n_new)
    return {"memory": mem.to_dict()}


# ---------------------------------------------------------------------------
# Review report + AI detection
# ---------------------------------------------------------------------------

@app.post("/api/sessions/{sid}/review_report")
async def review_report(sid: str, body: ReportBody):
    sess = _need_session(sid)
    if not sess.journal_key:
        raise HTTPException(400, "set journal first")
    skill = _need_skill(sess.journal_key)
    tree = STORE.tree(sid)
    tier = _TIER.get(body.tier, ModelTier.DEEP)
    _emit(sid, "stage_started", stage="review_report")

    def _go():
        return ReviewReporter(_llm()).report(
            tree, skill, sess.comprehension, language=body.language, tier=tier
        )

    rep = await asyncio.to_thread(_go)
    sess.review_report = rep.to_dict()
    sess.log(
        "review_report_generated",
        recommendation=rep.recommendation,
        overall=rep.scores.get("overall"),
        n_experiments=len(rep.experiments_to_strengthen),
    )
    STORE.save(sid)
    _emit(sid, "stage_done", stage="review_report")
    return rep.to_dict()


@app.post("/api/sessions/{sid}/ai_detect")
async def ai_detect(sid: str, body: ReportBody):
    """AI-rate detection. Result is persisted to session for display; not used by agents."""
    sess = _need_session(sid)
    tree = STORE.tree(sid)
    tier = _TIER.get(body.tier, ModelTier.SMART)
    _emit(sid, "stage_started", stage="ai_detect")

    def _go():
        return AIDetector(_llm()).detect(tree, tier=tier, language=body.language)

    result = await asyncio.to_thread(_go)
    sess.ai_detection = result.to_dict()
    STORE.save(sid)
    _emit(sid, "stage_done", stage="ai_detect", score=result.ai_likelihood)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Session inspection
# ---------------------------------------------------------------------------

@app.get("/api/sessions/{sid}")
async def get_session(sid: str):
    sess = _need_session(sid)
    return sess.to_dict()


@app.get("/api/sessions/{sid}/source")
async def get_source(sid: str):
    sess = _need_session(sid)
    tree = STORE.tree(sid)
    return {
        "source_type": sess.source_type,
        "title": tree.title,
        "abstract": tree.abstract.text if tree.abstract else "",
        "toc": tree.toc(),
        "source_text": tree.source_text if sess.source_type == "latex" else "",
    }


@app.get("/api/sessions/{sid}/structure")
async def get_structure(sid: str):
    """Return parsed document structure for user verification before planning."""
    _need_session(sid)
    tree = STORE.tree(sid)

    section_rows = []
    for s in tree.sections:
        for sub in s.walk():
            all_paras = list(sub.all_paragraphs())
            n_words = sum(len(p.text.split()) for p in all_paras)
            section_rows.append({
                "id":       sub.id,
                "level":    sub.level,
                "title":    sub.title,
                "n_paras":  len(all_paras),
                "n_words":  n_words,
            })

    abstract_words = len(tree.abstract.text.split()) if tree.abstract else 0
    return {
        "title":         tree.title,
        "source_type":   tree.source_type,
        "has_abstract":  tree.abstract is not None,
        "abstract_words": abstract_words,
        "n_references":  len(tree.references),
        "sections":      section_rows,
        "stats":         tree.stats(),
    }


@app.get("/api/sessions/{sid}/preview")
async def get_preview(sid: str):
    """Structured preview for in-browser rendering.

    Returns the document as a flat list of blocks (sections + paragraphs)
    with the cleaned `text` (LaTeX commands stripped, math kept as `$...$`)
    plus per-paragraph metadata so the UI can attach suggestion markers.
    For DOCX inputs, the UI may also fetch /raw to render with mammoth.js.
    """
    sess = _need_session(sid)
    tree = STORE.tree(sid)
    blocks: list[dict] = []
    if tree.abstract is not None:
        blocks.append({
            "kind": "abstract",
            "id": tree.abstract.id,
            "text": tree.abstract.text,
            "raw": tree.abstract.raw_source,
        })
    for sec in tree.sections:
        for sub in sec.walk():
            blocks.append({
                "kind": "heading",
                "id": sub.id,
                "level": sub.level,
                "title": sub.title,
            })
            for p in sub.paragraphs:
                blocks.append({
                    "kind": "paragraph",
                    "id": p.id,
                    "section_id": sub.id,
                    "text": p.text,
                    "raw": p.raw_source,
                })
    return {
        "title": tree.title,
        "source_type": sess.source_type,
        "blocks": blocks,
        "stats": tree.stats(),
    }


@app.get("/api/sessions/{sid}/raw")
async def get_raw(sid: str):
    """Serve the original uploaded file (for DOCX -> mammoth.js render)."""
    sess = _need_session(sid)
    p = Path(sess.source_path)
    if not p.exists():
        raise HTTPException(404, "uploaded file is missing")
    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if sess.source_type == "docx"
        else "text/plain"
    )
    return FileResponse(p, media_type=media, filename=p.name)


class SetJournalBody(BaseModel):
    journal_key: str


@app.post("/api/sessions/{sid}/set_journal")
async def set_journal(sid: str, body: SetJournalBody):
    sess = _need_session(sid)
    _need_skill(body.journal_key)  # validates it exists
    sess.journal_key = body.journal_key
    sess.log("journal_set", journal_key=body.journal_key)
    STORE.save(sid)
    return {"ok": True, "journal_key": body.journal_key}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@app.get("/api/sessions/{sid}/export")
async def export(
    sid: str,
    format: str = "latex",            # "latex" | "docx"
    author: str = "Paper-Agent AI",
):
    sess = _need_session(sid)
    tree = STORE.tree(sid)
    suggestions = list(sess.suggestions.values())
    out_dir = Path(__file__).resolve().parents[1] / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)

    if format == "latex":
        if sess.source_type != "latex":
            raise HTTPException(400, "session was uploaded as docx; use format=docx")
        out_path = out_dir / f"{sess.id}.tex"
        summary = LaTeXExporter().export(tree, suggestions, str(out_path))
        media = "application/x-latex"
    elif format == "docx":
        if sess.source_type != "docx":
            raise HTTPException(400, "session was uploaded as latex; use format=latex")
        out_path = out_dir / f"{sess.id}.docx"
        summary = DocxExporter().export(
            tree, suggestions, sess.source_path, str(out_path), author=author
        )
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        raise HTTPException(400, "format must be latex or docx")

    # Page-limit warning: if skill has any article type with pages_max, warn.
    page_warnings: list[str] = []
    if sess.journal_key:
        try:
            sk = _need_skill(sess.journal_key)
            for at in sk.article_types():
                pm = at.get("pages_max")
                if pm:
                    page_warnings.append(
                        f"{at.get('type','?')} article type has a {pm}-page limit. "
                        f"Since the exported file has not been compiled, please verify "
                        f"manually that the rendered PDF does not exceed {pm} pages."
                    )
        except Exception:
            pass

    return JSONResponse(
        {
            "summary": summary.to_dict(),
            "page_warnings": page_warnings,
            "download_url": f"/api/sessions/{sid}/export/file?format={format}",
        }
    )


@app.get("/api/sessions/{sid}/export/file")
async def export_file(sid: str, format: str = "latex"):
    out_dir = Path(__file__).resolve().parents[1] / "exports"
    out_path = out_dir / f"{sid}.{ 'tex' if format=='latex' else 'docx' }"
    if not out_path.exists():
        raise HTTPException(404, "export not found; call /export first")
    filename = out_path.name
    return FileResponse(out_path, filename=filename)


# ---------------------------------------------------------------------------
# Logs + progress (SSE)
# ---------------------------------------------------------------------------

@app.get("/api/logs")
async def get_logs():
    """Most recent in-memory snapshot (last 500 lines)."""
    return {"lines": _log.snapshot()}


@app.get("/api/logs/history")
async def log_history(limit: int = 1000, offset: int = 0):
    """Persistent on-disk log history, supports paging back through rotations."""
    return {"lines": read_log_history(limit=limit, offset=offset)}


@app.get("/api/logs/stream")
async def stream_logs():
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _log.subscribers.add(q)

    async def gen():
        # send recent backlog first
        for line in _log.snapshot()[-50:]:
            yield {"event": "log", "data": line}
        try:
            while True:
                line = await q.get()
                yield {"event": "log", "data": line}
        finally:
            _log.subscribers.discard(q)

    return EventSourceResponse(gen())


# ---------------------------------------------------------------------------
# Static frontend (Next.js `output: 'export'` bundle)
#
# Defined BEFORE /api/sessions/{sid}/progress so that route keeps priority.
# Actually FastAPI matches declared routes in order, but we put StaticFiles
# mount at the very bottom of the module (after all /api/* routes) so any
# unknown path falls through to the SPA. The /sessions/{sid}/ catch-all
# below rewrites runtime session IDs to the pre-rendered placeholder slug.
# ---------------------------------------------------------------------------
_UI_DIR = Path(__file__).resolve().parents[1] / "typescript" / "out"


@app.get("/api/sessions/{sid}/progress")
async def stream_progress(sid: str):
    _need_session(sid)
    q = _q_for(sid)

    async def gen():
        # opening event
        yield {"event": "ready", "data": json.dumps({"session_id": sid})}
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15.0)
                yield {"event": "progress", "data": msg}
            except asyncio.TimeoutError:
                # heartbeat to keep proxies happy
                yield {"event": "ping", "data": "{}"}

    return EventSourceResponse(gen())


# ---------------------------------------------------------------------------
# Static frontend (Next.js `output: 'export'` bundle)
#
# Mounted LAST so every /api/* route above keeps priority. Unknown paths
# fall through to the static bundle; `/sessions/<runtime-sid>/` is routed
# to the pre-rendered `_` placeholder which reads the real sid client-side.
# ---------------------------------------------------------------------------
_UI_DIR = Path(__file__).resolve().parents[1] / "typescript" / "out"

if _UI_DIR.is_dir():
    _PLACEHOLDER_HTML = _UI_DIR / "sessions" / "_" / "index.html"

    @app.get("/sessions/{sid}", include_in_schema=False)
    @app.get("/sessions/{sid}/", include_in_schema=False)
    async def _session_spa_fallback(sid: str):
        """Serve the pre-rendered placeholder for any runtime session id.

        The client component reads the real `sid` from the URL via
        `useParams()`, so one HTML shell handles every session.
        """
        if sid == "_":
            # The literal placeholder route is served by StaticFiles below.
            raise HTTPException(404)
        if not _PLACEHOLDER_HTML.is_file():
            raise HTTPException(500, "frontend bundle missing; run `npm run build` in typescript/")
        return FileResponse(_PLACEHOLDER_HTML, media_type="text/html")

    # Mount the Next static export at the root. `html=True` makes
    # StaticFiles serve `index.html` for directory requests (matches
    # `trailingSlash: true` in next.config.mjs) and return 404 for
    # unknown files so /api/* still routes through FastAPI above.
    app.mount("/", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
else:
    _LOGGER.warning(
        "Frontend bundle not found at %s; run `npm run build` in typescript/ "
        "to enable the web UI. /api/* endpoints still work.",
        _UI_DIR,
    )
