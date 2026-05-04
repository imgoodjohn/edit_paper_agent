#!/usr/bin/env python3
"""Full pipeline smoke test.

Usage:
    python scripts/test_pipeline.py [--base-url http://127.0.0.1:8000] [--tex path/to/file.tex]
    python scripts/test_pipeline.py --session sess-xxx   # re-use existing session

Steps exercised (mirrors the frontend workflow):
    1. Upload / reuse session
    2. Comprehend
    3. Confirm comprehension
    4. Predict journal ranking
    5. Set journal (top pick)
    6. Generate plan
    7. Approve plan
    8. Run editor on first todo (use_tools=False for speed)
    9. Decide on first suggestion (accept)
   10. Review report
   11. AI detection
   12. Export (latex)
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
import time
from pathlib import Path

import httpx

# ─── helpers ──────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
DIM    = "\033[2m"


def _hdr(title: str) -> None:
    bar = "─" * 70
    print(f"\n{BOLD}{CYAN}{bar}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{bar}{RESET}")


def _ok(label: str, detail: str = "") -> None:
    suffix = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {GREEN}✓{RESET}  {label}{suffix}")


def _warn(label: str, detail: str = "") -> None:
    suffix = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {YELLOW}⚠{RESET}  {label}{suffix}")


def _err(label: str, detail: str = "") -> None:
    suffix = f"\n     {RED}{detail}{RESET}" if detail else ""
    print(f"  {RED}✗{RESET}  {label}{suffix}")


def _dump(obj: object, indent: int = 4, max_list: int = 3) -> None:
    """Pretty-print a dict/list with truncated long lists."""
    def _trim(v: object) -> object:
        if isinstance(v, list) and len(v) > max_list:
            return v[:max_list] + [f"… +{len(v) - max_list} more"]
        if isinstance(v, dict):
            return {k: _trim(val) for k, val in v.items()}
        return v
    print(textwrap.indent(json.dumps(_trim(obj), indent=2, ensure_ascii=False), " " * indent))


def _post(client: httpx.Client, path: str, **kw) -> dict:
    t0 = time.time()
    r = client.post(path, **kw)
    elapsed = time.time() - t0
    if not r.is_success:
        raise RuntimeError(f"POST {path} → {r.status_code}\n{r.text[:2000]}")
    print(f"  {DIM}POST {path}  [{elapsed:.1f}s]{RESET}")
    return r.json()


def _get(client: httpx.Client, path: str, **kw) -> dict:
    t0 = time.time()
    r = client.get(path, **kw)
    elapsed = time.time() - t0
    if not r.is_success:
        raise RuntimeError(f"GET {path} → {r.status_code}\n{r.text[:800]}")
    print(f"  {DIM}GET  {path}  [{elapsed:.1f}s]{RESET}")
    return r.json()


# ─── pipeline steps ───────────────────────────────────────────────────────────

def step_upload(client: httpx.Client, tex_path: Path) -> str:
    _hdr("STEP 1 – Upload")
    with tex_path.open("rb") as fh:
        r = client.post(
            "/api/upload",
            files={"file": (tex_path.name, fh, "text/x-tex")},
            data={"journal_key": ""},
            timeout=60,
        )
    if not r.is_success:
        raise RuntimeError(f"Upload failed: {r.status_code}\n{r.text[:600]}")
    data = r.json()
    sid = data["session_id"]
    _ok("Uploaded", f"session={sid}  source_type={data['source_type']}")
    _ok("Stats", "  ".join(f"{k}={v}" for k, v in data.get("stats", {}).items()))
    _ok("Title", data.get("title", "?"))
    toc = data.get("toc", [])
    _ok(f"TOC sections", f"{len(toc)} entries")
    for e in toc[:6]:
        print(f"     {DIM}[{e['level']}] {e['title']}{RESET}")
    if len(toc) > 6:
        print(f"     {DIM}… +{len(toc)-6} more{RESET}")
    return sid


def step_comprehend(client: httpx.Client, sid: str, model: str) -> dict:
    _hdr("STEP 2 – Comprehend")
    payload = {"tier": "smart"}
    if model:
        payload["model"] = model
    data = _post(client, f"/api/sessions/{sid}/comprehend", json=payload, timeout=300)
    card = data.get("comprehension", {})
    _ok("Title",    card.get("title", "?"))
    _ok("Summary",  card.get("one_line_summary", "?"))
    _ok("Field",    f"{card.get('field','?')} / {card.get('subfield','?')}")
    _ok("Problem",  card.get("problem", "?")[:120])
    _ok("Contributions", f"{len(card.get('contributions',[]))} items")
    for c in card.get("contributions", [])[:3]:
        print(f"     {DIM}• {c[:100]}{RESET}")
    _ok("Key claims",    f"{len(card.get('key_claims',[]))} items")
    _ok("Confidence",    card.get("confidence", "?"))
    return card


def step_confirm(client: httpx.Client, sid: str) -> None:
    _hdr("STEP 3 – Confirm comprehension")
    _post(client, f"/api/sessions/{sid}/comprehension/confirm",
          json={"user_corrections": ""}, timeout=30)
    _ok("Confirmed (no corrections)")


def step_predict_journal(client: httpx.Client, sid: str) -> str:
    _hdr("STEP 4 – Predict journal ranking")
    data = _post(client, f"/api/sessions/{sid}/predict_journal",
                 json={}, timeout=300)
    _ok("Rationale", data.get("rationale", "")[:120])
    ranked = data.get("ranked", [])
    _ok(f"Ranked {len(ranked)} journals")
    for r in ranked[:5]:
        score = r.get("score", "?")
        name  = r.get("journal_name", r.get("journal_key", "?"))
        concerns = r.get("concerns", [])
        print(f"     {DIM}#{ranked.index(r)+1}  [{score}]  {name}"
              f"{'  ⚠ '+concerns[0][:50] if concerns else ''}{RESET}")
    top = data.get("top_pick", ranked[0]["journal_key"] if ranked else "")
    _ok("Top pick", top)
    return top


def step_set_journal(client: httpx.Client, sid: str, journal_key: str) -> None:
    _hdr("STEP 5 – Set journal")
    data = _post(client, f"/api/sessions/{sid}/set_journal",
                 json={"journal_key": journal_key}, timeout=30)
    _ok("Journal set", data.get("journal_key", journal_key))


def step_plan(client: httpx.Client, sid: str, model: str) -> list[dict]:
    _hdr("STEP 6 – Generate plan")
    payload = {"tier": "deep"}
    if model:
        payload["model"] = model
    data = _post(client, f"/api/sessions/{sid}/plan", json=payload, timeout=600)
    plan = data.get("plan", {})
    _ok("Overall strategy", plan.get("overall_strategy", "?")[:120])
    todos = plan.get("todos", [])
    _ok(f"TODOs: {len(todos)}")
    for td in todos:
        pri = td.get("priority", "?")
        cat = td.get("category", "?")
        print(f"     {DIM}[{pri}/{cat}] {td['id']}  {td['title'][:70]}{RESET}")
    risks = plan.get("risks", [])
    if risks:
        _warn(f"Risks: {len(risks)}")
        for r in risks[:2]:
            print(f"     {DIM}• {r[:100]}{RESET}")
    return todos


def step_approve(client: httpx.Client, sid: str) -> None:
    _hdr("STEP 7 – Approve plan")
    _post(client, f"/api/sessions/{sid}/plan/approve",
          json={"edited_plan": None}, timeout=30)
    _ok("Plan approved")


def step_edit_todo(client: httpx.Client, sid: str, todo: dict, model: str) -> list[dict]:
    tid   = todo["id"]
    title = todo["title"]
    _hdr(f"STEP 8 – Run editor  [{tid}] {title[:60]}")
    payload = {"language": "en", "tier": "smart", "use_tools": False}
    if model:
        payload["model"] = model
    data = _post(client, f"/api/sessions/{sid}/edit/{tid}", json=payload, timeout=600)
    suggestions = data.get("suggestions", [])
    _ok(f"Suggestions: {len(suggestions)}")
    for s in suggestions[:5]:
        flag = "🚩" if s.get("flag_for_user") else "  "
        sev  = s.get("severity", "?")
        cat  = s.get("category", "?")
        print(f"     {flag} [{sev}/{cat}] {s['id']}")
        print(f"       {DIM}before: {s.get('before','')[:80]}{RESET}")
        print(f"       {DIM}after:  {s.get('after','')[:80]}{RESET}")
        print(f"       {DIM}why:    {s.get('rationale','')[:100]}{RESET}")
    notes = data.get("notes", [])
    if notes:
        _ok(f"Notes: {len(notes)}")
        for n in notes[:3]:
            print(f"     {DIM}• {n}{RESET}")
    return suggestions


def step_decide(client: httpx.Client, sid: str, suggestion_id: str) -> None:
    _hdr(f"STEP 9 – Accept suggestion  {suggestion_id}")
    _post(client, f"/api/sessions/{sid}/decide",
          json={"suggestion_id": suggestion_id, "decision": "accepted"}, timeout=30)
    _ok("Accepted", suggestion_id)


def step_review_report(client: httpx.Client, sid: str, model: str) -> None:
    _hdr("STEP 10 – Review report")
    payload = {"language": "en", "tier": "deep"}
    if model:
        payload["model"] = model
    data = _post(client, f"/api/sessions/{sid}/review_report", json=payload, timeout=600)
    _ok("Summary",        data.get("summary", "?")[:150])
    _ok("Recommendation", data.get("recommendation", "?"))
    _ok("Strengths",      f"{len(data.get('strengths',[]))}")
    _ok("Weaknesses",     f"{len(data.get('weaknesses',[]))}")
    scores = data.get("scores", {})
    if scores:
        _ok("Scores", "  ".join(f"{k}={v}" for k, v in scores.items()))
    compliance = data.get("compliance_check", [])
    _ok(f"Compliance checks: {len(compliance)}")
    for c in compliance[:4]:
        status = c.get("status", "?")
        rule   = c.get("rule", "?")[:60]
        note   = c.get("note", "")[:60]
        marker = GREEN if status == "pass" else RED
        print(f"     {marker}[{status}]{RESET}  {rule}  {DIM}{note}{RESET}")
    letter = data.get("decision_letter_draft", "")
    if letter:
        _ok("Decision letter draft", f"{len(letter)} chars")
        print(textwrap.indent(textwrap.shorten(letter, 300, placeholder=" …"), "     "))


def step_ai_detect(client: httpx.Client, sid: str) -> None:
    _hdr("STEP 11 – AI detection")
    data = _post(client, f"/api/sessions/{sid}/ai_detect",
                 json={"language": "en", "tier": "smart"}, timeout=300)
    likelihood = data.get("ai_likelihood", "?")
    verdict    = data.get("verdict", "?")
    col = RED if isinstance(likelihood, int) and likelihood > 60 else \
          YELLOW if isinstance(likelihood, int) and likelihood > 30 else GREEN
    _ok("Likelihood", f"{col}{likelihood}%{RESET}  verdict={verdict}")
    _ok("Top signals", f"{len(data.get('top_signals',[]))}")
    for s in data.get("top_signals", [])[:3]:
        print(f"     {DIM}• {s}{RESET}")
    _ok("Advice", data.get("advice", "?")[:120])


def step_export(client: httpx.Client, sid: str) -> None:
    _hdr("STEP 12 – Export (latex)")
    data = _post(
        client,
        f"/api/sessions/{sid}/export",
        params={"format": "latex", "author": "Test Script"},
        timeout=120,
    )
    summary = data.get("summary", {})
    _ok("Export summary",
        f"accepted={summary.get('accepted',0)}  "
        f"modified={summary.get('modified',0)}  "
        f"pending={summary.get('pending',0)}  "
        f"rejected={summary.get('rejected',0)}  "
        f"skipped={summary.get('skipped_not_found',0)}")
    _ok("Written to", summary.get("written_path", "?"))
    _ok("Download URL", data.get("download_url", "?"))
    warns = data.get("page_warnings", [])
    if warns:
        _warn(f"Page warnings: {len(warns)}")
        for w in warns[:3]:
            print(f"     {DIM}⚠ {w}{RESET}")


# ─── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Paper-Agent full pipeline test")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--tex",     default="uploads/sess-1777788852214.tex",
                    help="Path to .tex file to upload (relative to project root)")
    ap.add_argument("--session", default="",
                    help="Re-use existing session ID (skip upload)")
    ap.add_argument("--journal", default="",
                    help="Force a specific journal key (skip predict step)")
    ap.add_argument("--model",   default="",
                    help="Override model for all LLM calls")
    ap.add_argument("--skip-edit", action="store_true",
                    help="Skip editor step (faster smoke test)")
    ap.add_argument("--skip-report", action="store_true",
                    help="Skip review report + AI detect")
    ap.add_argument("--skip-export", action="store_true",
                    help="Skip export step")
    args = ap.parse_args()

    client = httpx.Client(
        base_url=args.base_url,
        timeout=httpx.Timeout(600.0, connect=10.0),
        trust_env=False,   # bypass Windows system proxy (IDE intercepts localhost)
    )

    t_start = time.time()
    errors: list[str] = []

    try:
        # ── health check ──────────────────────────────────────────────────
        _hdr("HEALTH CHECK")
        health = _get(client, "/api/health")
        _ok("Backend", f"ok={health.get('ok')}  version={health.get('version','?')}")

        cfg = _get(client, "/api/config")
        _ok("Config",
            f"base_url={cfg.get('base_url','?')}  "
            f"smart={cfg.get('smart_model','?')}  "
            f"deep={cfg.get('deep_model','?')}")

        models = _get(client, "/api/models")
        _ok("Models discovered", f"{len(models.get('models', []))}")
        for m in models.get("models", [])[:5]:
            print(f"     {DIM}• {m}{RESET}")

        skills = _get(client, "/api/skills")
        skill_list = skills.get("skills", [])
        _ok("Skills loaded", f"{len(skill_list)}")
        for s in skill_list[:4]:
            print(f"     {DIM}• {s['key']}  {s['name']}{RESET}")

        # ── step 1: upload / reuse ────────────────────────────────────────
        if args.session:
            sid = args.session
            _hdr("STEP 1 – Reuse existing session")
            sess = _get(client, f"/api/sessions/{sid}")
            _ok("Session", f"id={sid}  journal={sess.get('journal_key','—')}")
        else:
            tex_path = Path(args.tex)
            if not tex_path.is_absolute():
                # relative to project root (parent of scripts/)
                tex_path = Path(__file__).resolve().parent.parent / tex_path
            if not tex_path.exists():
                raise FileNotFoundError(f"LaTeX file not found: {tex_path}")
            sid = step_upload(client, tex_path)

        # ── step 2–3: comprehend + confirm ────────────────────────────────
        step_comprehend(client, sid, args.model)
        step_confirm(client, sid)

        # ── step 4–5: journal ─────────────────────────────────────────────
        if args.journal:
            journal_key = args.journal
            _hdr("STEP 4+5 – Using provided journal")
            _ok("Journal", journal_key)
        else:
            try:
                journal_key = step_predict_journal(client, sid)
            except Exception as exc:
                _warn("predict_journal failed, falling back to first available skill",
                      str(exc))
                journal_key = skill_list[0]["key"] if skill_list else ""
        step_set_journal(client, sid, journal_key)

        # ── step 6–7: plan ────────────────────────────────────────────────
        todos = step_plan(client, sid, args.model)
        step_approve(client, sid)

        # ── step 8–9: edit first todo ─────────────────────────────────────
        if not args.skip_edit and todos:
            first_todo = todos[0]
            suggestions = step_edit_todo(client, sid, first_todo, args.model)
            if suggestions:
                step_decide(client, sid, suggestions[0]["id"])
            else:
                _warn("No suggestions produced — skipping decide step")
        elif args.skip_edit:
            _hdr("STEP 8–9 – Skipped (--skip-edit)")
            _warn("Editor step skipped")

        # ── step 10–11: review + AI detect ────────────────────────────────
        if not args.skip_report:
            step_review_report(client, sid, args.model)
            step_ai_detect(client, sid)
        else:
            _hdr("STEP 10–11 – Skipped (--skip-report)")
            _warn("Report / AI-detect steps skipped")

        # ── step 12: export ────────────────────────────────────────────────
        if not args.skip_export:
            step_export(client, sid)
        else:
            _hdr("STEP 12 – Skipped (--skip-export)")
            _warn("Export step skipped")

    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted by user.{RESET}")
        sys.exit(1)
    except Exception as exc:
        errors.append(str(exc))
        _err("FATAL", str(exc))
        import traceback
        traceback.print_exc()

    # ── summary ───────────────────────────────────────────────────────────
    elapsed = time.time() - t_start
    _hdr("SUMMARY")
    if errors:
        _err(f"Completed with {len(errors)} error(s)  [{elapsed:.1f}s total]")
        for e in errors:
            print(f"     {RED}{e}{RESET}")
        sys.exit(1)
    else:
        _ok(f"All steps passed  [{elapsed:.1f}s total]")


if __name__ == "__main__":
    main()
