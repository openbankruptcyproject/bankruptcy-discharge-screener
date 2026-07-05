#!/usr/bin/env python3
"""publish.py — one-command publish pipeline for the public-tools repo.

Codifies the 94-page publish saga into a single guarded run:

  1. scan_before_push.sh          (blocklist + fact-accuracy + identity leaks)
  2. gh auth switch ilikemath9999 (anonymous publishing identity)
  3. git push                     (GIT_TERMINAL_PROMPT=0, --progress)
  4. gh auth switch danbrown20    (ALWAYS restored — try/finally)
  5. poll GitHub Pages build to 'built'
  6. probe live URLs with a Mozilla UA for expected markers
  7. one-line verdict + timestamped log file (outside the public tree)

Flags:
  --dry         stop before the push (scan + what-would-push preview)
  --probe-only  skip scan/push, just poll + probe the live site

The real push stays a Dan-triggered invocation: run without flags only
when Dan says publish.
"""

import argparse
import datetime
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(os.path.dirname(HERE), "logs", "publish")
PUBLISH_ACCOUNT = "ilikemath9999"
DAILY_ACCOUNT = "danbrown20"
PAGES_REPO = "openbankruptcyproject/bankruptcy-discharge-screener"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/127.0"

# (url, expected marker) — the live-site canaries
DEFAULT_PROBES = [
    ("https://1328f.com/", "G-FTWLM223G7"),  # homepage has no #site-nav; GA4 is the stable canary
    ("https://1328f.com/districts/ksbk.html", "G-FTWLM223G7"),
    ("https://1328f.com/districts/debk.html", "id=\"site-nav\""),
]

LOG_LINES = []


def log(line):
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    LOG_LINES.append(f"[{stamp}] {line}")
    print(line, flush=True)


def run(cmd, env=None, timeout=300, cwd=HERE):
    merged = {**os.environ, **(env or {})}
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, cwd=cwd, env=merged)


def gh_active_account():
    r = run(["gh", "api", "user", "-q", ".login"])
    return r.stdout.strip() if r.returncode == 0 else None


def gh_switch(account):
    r = run(["gh", "auth", "switch", "--user", account])
    if r.returncode != 0:
        raise RuntimeError(f"gh auth switch {account} failed: {r.stderr.strip()[:200]}")
    log(f"gh auth -> {account}")


def find_bash():
    """Git Bash, explicitly — plain 'bash' resolves to the WSL stub on
    this box (no distro installed) and dies with execvpe(/bin/bash)."""
    candidates = [
        os.environ.get("GIT_BASH"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return "bash"


def step_scan():
    log("STEP scan_before_push.sh")
    # the scan shells `file` once per tracked file — allow a long leash
    r = run([find_bash(), os.path.join(HERE, "scan_before_push.sh")], timeout=1800)
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        log(f"  scan: {line}")
    if r.returncode != 0:
        log("SCAN FAILED — publish aborted")
        return False
    return True


def step_push():
    log("STEP git push")
    # git's default credential helper here is Git Credential Manager, which
    # pops a GUI dialog GIT_TERMINAL_PROMPT can't suppress and ignores the gh
    # account switch. Route auth through gh so the push lands headlessly as
    # the active (publish) account (leading empty helper resets the inherited
    # manager helper first). The pre-push hook re-runs scan_before_push.sh —
    # kept intentionally as the enforcement gate — so allow a long leash like
    # step_scan rather than skipping it.
    r = run(["git",
             "-c", "credential.helper=",
             "-c", "credential.helper=!gh auth git-credential",
             "push", "--progress", "origin", "HEAD"],
            env={"GIT_TERMINAL_PROMPT": "0"}, timeout=1800)
    for line in ((r.stderr or "") + (r.stdout or "")).strip().splitlines()[-5:]:
        log(f"  push: {line}")
    if r.returncode != 0:
        log("PUSH FAILED")
        return False
    return True


def step_pages_poll(timeout_s=420):
    log("STEP poll Pages build")
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        r = run(["gh", "api", f"repos/{PAGES_REPO}/pages/builds/latest", "-q", ".status"])
        status = r.stdout.strip() if r.returncode == 0 else f"api-error:{r.stderr.strip()[:80]}"
        if status != last:
            log(f"  pages: {status}")
            last = status
        if status == "built":
            return True
        if status == "errored":
            return False
        time.sleep(10)
    log("  pages: poll timed out")
    return False


def step_probe(probes):
    log("STEP probe live URLs")
    ok = True
    for url, marker in probes:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
            hit = marker in body
            log(f"  {'OK  ' if hit else 'MISS'} {url} ({'found' if hit else 'missing'}: {marker})")
            ok = ok and hit
        except Exception as exc:
            log(f"  FAIL {url} ({exc})")
            ok = False
    return ok


def write_log(verdict):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, datetime.datetime.now().strftime("publish_%Y%m%d_%H%M%S.log"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG_LINES) + f"\n\nVERDICT: {verdict}\n")
    print(f"\nlog: {path}")


def main():
    ap = argparse.ArgumentParser(description="guarded publish pipeline")
    ap.add_argument("--dry", action="store_true", help="stop before the push")
    ap.add_argument("--probe-only", action="store_true", help="just poll+probe the live site")
    args = ap.parse_args()

    if args.probe_only:
        built = step_pages_poll(timeout_s=30)
        probed = step_probe(DEFAULT_PROBES)
        verdict = f"PROBE-ONLY: pages={'built' if built else 'not-built'} probes={'ok' if probed else 'FAIL'}"
        log(verdict)
        write_log(verdict)
        return 0 if probed else 1

    if not step_scan():
        write_log("ABORTED at scan")
        return 1

    r = run(["git", "status", "--short", "--branch"])
    for line in r.stdout.strip().splitlines()[:8]:
        log(f"  status: {line}")
    ahead = run(["git", "rev-list", "--count", "@{u}..HEAD"]).stdout.strip() or "?"
    log(f"  commits to push: {ahead}")

    if args.dry:
        verdict = f"DRY RUN: scan clean, {ahead} commit(s) would push (no auth switch, no push)"
        log(verdict)
        write_log(verdict)
        return 0

    original = gh_active_account() or DAILY_ACCOUNT
    pushed = built = probed = False
    try:
        gh_switch(PUBLISH_ACCOUNT)
        pushed = step_push()
    finally:
        # the identity ALWAYS comes back, push or no push
        try:
            gh_switch(DAILY_ACCOUNT if original != PUBLISH_ACCOUNT else DAILY_ACCOUNT)
        except Exception as exc:
            log(f"WARNING: could not restore gh account: {exc}")

    if pushed:
        built = step_pages_poll()
        probed = step_probe(DEFAULT_PROBES)

    verdict = (f"{'PUBLISHED' if (pushed and built and probed) else 'INCOMPLETE'}: "
               f"push={'ok' if pushed else 'FAIL'} pages={'built' if built else 'FAIL'} "
               f"probes={'ok' if probed else 'FAIL'}")
    log(verdict)
    write_log(verdict)
    return 0 if (pushed and built and probed) else 1


if __name__ == "__main__":
    sys.exit(main())
