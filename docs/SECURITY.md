# Security

**The `subprocess` sandbox is NOT a security boundary.** It protects against runaway resource use and accidents
(step/output/time limits, an audit hook, a scrubbed environment); it does not protect against malicious code.

- The server binds `127.0.0.1` only.
- `GLASSBOX_ALLOW_REMOTE=true` is refused at startup unless `SANDBOX_MODE=docker`
  (`glassbox serve` and `create_app` both check it).
- `SANDBOX_MODE=docker` runs the same runner in a container with `--network none --read-only --tmpfs /tmp
  --memory 512m --cpus 1 --pids-limit 64 --cap-drop ALL --security-opt no-new-privileges --user 65534:65534`
  (build the image with `make docker-runner`). Treat remote exposure as unsupported until you have verified that
  setup on your own host.
- API hardening: sources <= 200 KB, <= 20 files, no `..`/absolute paths, 4 concurrent runs, CORS (and WebSocket
  `Origin`) limited to configured origins, temp directories deleted after each run.
