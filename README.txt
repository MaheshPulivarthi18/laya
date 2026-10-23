Evidence for aayushch/laya PR #59 (fixes #7): labelled parallel runtime download progress
=========================================================================================

Tested: 2026-10-23, macOS 26.5.2, Apple M4
Code:   branch fix/label-parallel-runtime-progress, commit a2f01c1a2c89391e251eba98d156e5384dc387c3 (the PR head)
How:    `npx @tauri-apps/cli dev` in ui/, with HOME pointed at an empty temporary
        directory so first-run setup started from scratch (~/.laya did not exist).

This machine already has Homebrew Python 3.13 and Node 24, which laya finds and
reuses, so normally only uv would download. To exercise the parallel case, the
runtime check was forced to treat Python, Node and uv as missing via an env var
(09-local-test-only-force-download.patch). That patch is local only and NOT part
of the PR; the download and progress code that ran is the PR's.

Result: Node.js 22.22.3, uv 0.7.12 and Python 3.12.13 downloaded in parallel
(07-app-log-runtimes.txt: installed at 16:28:21, :23, :25 UTC). The "Preparing
runtimes" line named each download, and every counter only increased:
  Node 3 -> 46 MB of 47, uv 0 -> 14 MB of 15, Python 5 -> 23 MB of 23.
While downloads overlapped the line alternated between them
(05: three consecutive frames ~0.25 s apart: Node 21 -> uv 2 -> Node 23).

Files
  01-03  full app window while Node / uv / Python download
  04     runtimes done ("Python 3.12.13 ready")
  05     three consecutive frames side by side (interleaving)
  06     animated GIF of the whole "Preparing runtimes" step (setup panel)
  07     app log lines for the runtime step
  08     every captured frame: local capture time (IST) and the progress text on screen
  09     the local-only test patch

Captured with macOS screencapture of the laya window only (198 frames, ~0.27 s apart).
Progress text in 08 was read from the frames with macOS Vision text recognition.
Not tested: the packaged release app, Windows, Linux.
