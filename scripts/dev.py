"""One command for development: API on 127.0.0.1:8000 + Vite dev server on http://localhost:5173.

    python scripts/dev.py            (or `make dev`)

Installs the frontend dependencies on first use (`npm ci`), then runs both servers until Ctrl+C.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def main() -> int:
    npm = shutil.which("npm")
    if npm is None:
        print("error: npm was not found on PATH (Node.js 22+ is required for the frontend)", file=sys.stderr)
        return 2
    if not (FRONTEND / "node_modules").is_dir():
        print("installing frontend dependencies (npm ci) ...", flush=True)
        if subprocess.run([npm, "ci"], cwd=FRONTEND, check=False).returncode != 0:
            print("error: npm ci failed", file=sys.stderr)
            return 1
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    api = subprocess.Popen([sys.executable, "-m", "glassbox.cli", "serve"], cwd=ROOT, creationflags=flags)
    web = subprocess.Popen([npm, "run", "dev", "--", "--host", "127.0.0.1"], cwd=FRONTEND, creationflags=flags)
    print(
        "\nGlassBox is starting: UI http://localhost:5173  |  API http://127.0.0.1:8000/api/health  |  Ctrl+C stops both\n",
        flush=True,
    )
    try:
        while api.poll() is None and web.poll() is None:
            time.sleep(0.5)
        print("one of the servers exited; shutting the other one down", file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in (api, web):
            if proc.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
                else:
                    proc.send_signal(signal.SIGTERM)
        for proc in (api, web):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
