# Paper Agent

Multi-agent manuscript reviewer and editor. One command starts everything —
no separate frontend server required.

## Layout

```
main.py           Unified launcher (auto-install → build → serve)
paper_agent/      Python package (parsers, agents, services, export)
backend/          FastAPI app (REST + SSE + serves compiled frontend)
typescript/       Next.js source (compiled to typescript/out/ at build time)
skills/journals/  Journal skill YAMLs (Nature, Science, IEEE TPAMI, ...)
sessions/         Per-session JSON state (auto-created)
uploads/          Uploaded manuscripts (auto-created)
exports/          Generated .tex / .docx (auto-created)
tests/            pytest suite
```

## Quick start

```bash
# 1. Install Python dependencies once
pip install -r requirements.txt

# 2. Start everything (installs npm packages + builds frontend on first run)
python main.py
```

Open **http://127.0.0.1:8765** in your browser.

The launcher:
1. Checks `typescript/node_modules` — runs `npm install` if missing
2. Checks `typescript/out/` — runs `npm run build` if missing
3. Starts FastAPI which serves both `/api/*` and the compiled frontend

Subsequent starts skip npm/build steps automatically (use `--rebuild` to force).

### Launcher flags

```
python main.py --port 8765      # change port (default 8765)
python main.py --host 0.0.0.0   # expose on LAN
python main.py --rebuild        # force Next.js rebuild
python main.py --no-build       # skip all frontend steps
python main.py --reload         # uvicorn hot-reload (dev mode)
```

## Pipeline

```
upload (.tex / .docx)
  → ComprehensionAgent   confirm or correct the AI's reading of your paper
  → [optional] JournalPredictor  auto-rank target journals
  → PlannerAgent         approve a TODO list; tasks needing human action flagged
  → EditorAgent          per-TODO; PR-style accept / reject / modify suggestions
      └─ SummarizerAgent auto-compacts decision log after every edit (background)
  → [optional] GrammarAutoFixer  batch language pass
  → [optional] ReviewReporter    full review report + scores + compliance check
  → [optional] AIDetector        stateless AI-likelihood score (not stored)
  → Export
       LaTeX  accepted edits only, plain replacement, no \replaced wrapper
       DOCX   pending → Word track-changes; accepted/modified applied directly
```

## Configuring models

Set env vars (or use the Settings page in the UI):

```
PAPER_AGENT_API_KEY      your-key
PAPER_AGENT_BASE_URL     https://api.openai.com/v1
PAPER_AGENT_FAST_MODEL   gpt-4o-mini
PAPER_AGENT_SMART_MODEL  gpt-4o
PAPER_AGENT_DEEP_MODEL   o3
```

The UI lets you override the model tier per call and switch the output
language between English and Chinese.

## Journal word / page limits

When a journal is selected the session header automatically shows live
word-count compliance against the skill YAML (e.g. `Abstract 148/200w`,
`14 pp max`). Values turn red if the limit is exceeded.

## Auto-compact memory

After every editor run the system automatically summarises the decision
log into a compact memory block (prose summary + rejected patterns +
consistency rules). This keeps the context window small without any
manual action. The decision log panel shows each compaction event.

## Hard safety rules

Every prompt enforces:

* No changes to numeric results, p-values, accuracies, percentages, or dataset sizes.
* No additions, deletions, or renumbering of citations.
* No modification of `\ref / \eqref / \label` keys.
* No fabricated experiments, methods, or claims.

`paper_agent.guardrails.NumberGuard` forces `flag_for_user` if any digit,
`[N]`, or `\cite{}` token differs between `before` and `after`.

## Tests

```bash
python -m pytest tests/ -v
```

## API reference

```
GET  /api/health
GET  /api/models                                # upstream model list
GET  /api/skills
POST /api/upload                                multipart: file, journal_key
POST /api/sessions/{sid}/set_journal            { journal_key }
POST /api/sessions/{sid}/comprehend
POST /api/sessions/{sid}/comprehension/confirm  { user_corrections }
POST /api/sessions/{sid}/predict_journal
POST /api/sessions/{sid}/plan
POST /api/sessions/{sid}/plan/approve           { edited_plan? }
POST /api/sessions/{sid}/edit/{todo_id}         { language, tier, use_tools }
POST /api/sessions/{sid}/auto_grammar           { language, tier }
POST /api/sessions/{sid}/decide                 { suggestion_id, decision, modified_after? }
POST /api/sessions/{sid}/compact                (manual; auto-triggered after each edit)
POST /api/sessions/{sid}/review_report          { language, tier }
POST /api/sessions/{sid}/ai_detect              { language, tier }   # stateless
GET  /api/sessions/{sid}
GET  /api/sessions/{sid}/structure              # word counts, section stats
GET  /api/sessions/{sid}/preview                # blocks for KaTeX/mammoth render
GET  /api/sessions/{sid}/raw                    # original .tex / .docx
GET  /api/sessions/{sid}/export?format=latex|docx&author=...
GET  /api/sessions/{sid}/export/file?format=latex|docx
GET  /api/logs
GET  /api/logs/history?limit=&offset=
GET  /api/logs/stream                           (SSE)
GET  /api/sessions/{sid}/progress               (SSE)
```

## Web UI routes

```
/            Upload
/sessions    Sessions list
/sessions/[sid]  Revision workflow + live preview
/logs        Live log tail + history
/settings    Model config + language
```
