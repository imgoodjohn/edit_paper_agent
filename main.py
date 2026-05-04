#!/usr/bin/env python3
"""
Paper Agent – unified launcher.

Checks node_modules, builds the Next.js static export if needed, then
starts the FastAPI backend which serves both the API and the frontend.

Usage
-----
    python main.py [--port 8765] [--host 127.0.0.1] [--rebuild] [--no-build] [--reload]

Flags
-----
    --port      Backend port (default 8765)
    --host      Bind address  (default 127.0.0.1)
    --rebuild   Force Next.js rebuild even when out/ already exists
    --no-build  Skip all frontend steps (useful if already built)
    --reload    Enable uvicorn auto-reload (development mode)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT    = Path(__file__).resolve().parent
TS_DIR  = ROOT / "typescript"
MODULES = TS_DIR / "node_modules"
OUT_DIR = TS_DIR / "out"          # Next.js `output: 'export'` target


# ── helpers ──────────────────────────────────────────────────────────────────

def _npm() -> list[str]:
    """Return the npm executable list for the current OS."""
    candidates = (["npm.cmd", "npm"] if sys.platform == "win32" else ["npm"])
    for name in (candidates if isinstance(candidates, list) else [candidates]):
        found = shutil.which(name)
        if found:
            return [found]
    return ["npm.cmd" if sys.platform == "win32" else "npm"]


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        sys.exit(f"\n✗  Command failed (exit {result.returncode})")


# ── frontend preparation ──────────────────────────────────────────────────────

def prepare_frontend(rebuild: bool = False) -> None:
    print("\n── Frontend ──────────────────────────────────────────────")

    if not MODULES.exists():
        print("  node_modules not found — running npm install …")
        _run([*_npm(), "install"], cwd=TS_DIR)
    else:
        print("  ✓ node_modules present")

    if rebuild or not OUT_DIR.exists():
        print("  Building Next.js static export (npm run build) …")
        _run([*_npm(), "run", "build"], cwd=TS_DIR)
    else:
        print("  ✓ Static export present (out/)")

    print()


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Paper Agent – start the full stack with one command",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--port",     type=int, default=8765,        metavar="PORT")
    ap.add_argument("--host",               default="127.0.0.1", metavar="HOST")
    ap.add_argument("--rebuild",  action="store_true", help="Force Next.js rebuild")
    ap.add_argument("--no-build", action="store_true", help="Skip frontend build")
    ap.add_argument("--reload",   action="store_true", help="Uvicorn hot-reload (dev)")
    args = ap.parse_args()

    print("╔══════════════════════════════════════╗")
    print("║          Paper Agent                 ║")
    print("╚══════════════════════════════════════╝")

    if not args.no_build:
        prepare_frontend(rebuild=args.rebuild)

    url = f"http://{args.host}:{args.port}"
    print("── Backend ───────────────────────────────────────────────")
    print(f"  Binding  →  {url}")
    print(f"  Open     →  {url}/")
    print("  Stop     →  Ctrl-C\n")

    uvicorn = shutil.which("uvicorn")
    cmd: list[str] = (
        [uvicorn] if uvicorn else [sys.executable, "-m", "uvicorn"]
    ) + ["backend.main:app", "--host", args.host, "--port", str(args.port)]
    if args.reload:
        cmd.append("--reload")

    try:
        subprocess.run(cmd, cwd=ROOT)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
