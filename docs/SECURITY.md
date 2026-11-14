# Security

## Threat model (honest version)

**The `subprocess` sandbox is NOT a security boundary.** It protects against runaway resource use and accidents
(step / output / time limits, an audit hook, a scrubbed environment, deleted temp directories). It does **not** protect
against malicious code: a determined program can escape an in-process audit hook. Run only code you would run on your own
machine anyway.

## Defaults and the remote guard

- The server binds `127.0.0.1` only.
- `GLASSBOX_ALLOW_REMOTE=true` is refused at startup unless `SANDBOX_MODE=docker` (checked by both `glassbox serve` and
  `create_app`; covered by tests).
- WebSocket connections carry an `Origin` check against `GLASSBOX_CORS_ORIGINS` (CORS does not cover WebSockets).

## Layers

1. **Process**: new session / process group, cwd = per-run temp dir, environment built from scratch (only
   `PYTHONHASHSEED`, `PYTHONDONTWRITEBYTECODE`, `LANG`, `SYSTEMROOT` on Windows). API keys and the parent environment
   never reach the child (tested).
2. **Runner limits**: `max_steps` 20,000, output 256 KB, 64 KB per event, 50 MB total; POSIX `rlimit`
   (CPU / AS / FSIZE / NOFILE); wall-clock watchdog kills the whole tree.
3. **Audit hook**: blocks `socket.connect` (and DNS), `subprocess.Popen`, `os.system`, `os.exec*`, spawns/forks, ctypes
   loads and writes outside the working directory. Network is opt-in per run (`allow_network`).
4. **Docker mode** (`SANDBOX_MODE=docker`): same runner and protocol inside a container with
   `--network none --read-only --tmpfs /tmp --memory 512m --cpus 1 --pids-limit 64 --cap-drop ALL
   --security-opt no-new-privileges --user 65534:65534`. Build the image with `make docker-runner`.
   **Status: written and unit-tested at the command-line level only; not run end to end on the development machine.**
5. **API hardening**: sources <= 200 KB, <= 20 files, no `..` or absolute paths, 4 concurrent runs (429 beyond that),
   CORS only for configured origins, LRU(20) + TTL run store, temp directories deleted after every run.

## What-If values

Parsed with `ast.literal_eval` only, in the API **and** again in the runner. `eval` is never used.
Anything that is not a plain literal (for example `__import__('os')`) is rejected with HTTP 422.

## LLM safety

- User code, program output and trace digests are sent as DATA inside nonce-delimited blocks; the system prompt tells the
  model to ignore instructions found inside them; look-alike delimiters inside the data are defused.
- LLM output is never applied automatically: JSON schema -> edit engine (`ast.parse` of every changed file) -> number check
  (no unmeasured performance claims) -> sandboxed verification -> the user's click.
- Keys are never logged (only the last 4 characters), never put in URLs, and never given to the runner.
- Source code is sent to a provider only when the user clicks an LLM button.

## Reporting

Please report vulnerabilities privately to the maintainers rather than in a public issue.
