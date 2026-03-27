#!/bin/bash
# Push updated public-tools files to the public GitHub repo.
# Run from D:\Bankruptcy\public-tools\
#
# What it does:
#   1. Clones the public repo into a temp directory
#   2. Copies the public files (not the private ones)
#   3. Commits and pushes
#   4. Cleans up the temp clone

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_URL="https://github.com/ilikemath9999/bankruptcy-discharge-screener.git"
TEMP_DIR="$(mktemp -d)"

echo "=== Cloning public repo into $TEMP_DIR ==="
git clone "$REPO_URL" "$TEMP_DIR/repo"
cd "$TEMP_DIR/repo"

echo "=== Copying updated files ==="

# Root files
cp "$SCRIPT_DIR/README.md" .
cp "$SCRIPT_DIR/.gitignore" .
cp "$SCRIPT_DIR/screen_1328f.py" .
cp "$SCRIPT_DIR/screen_discharge_bars.py" .
cp "$SCRIPT_DIR/practice_report.py" .
cp "$SCRIPT_DIR/rss_monitor.py" .
cp "$SCRIPT_DIR/rss_config.example.json" .
cp "$SCRIPT_DIR/LICENSE" .
cp "$SCRIPT_DIR/index.html" .
cp "$SCRIPT_DIR/districts.json" .

# Docs
mkdir -p docs
cp "$SCRIPT_DIR/docs/pacer_csv_guide.md" docs/
cp "$SCRIPT_DIR/docs/volunteer_guide.md" docs/
cp "$SCRIPT_DIR/docs/submission_template.md" docs/

# Leaderboard
cp "$SCRIPT_DIR/LEADERBOARD.md" .

# Examples
mkdir -p examples
cp "$SCRIPT_DIR/examples/sample_output.txt" examples/

# Tests
mkdir -p tests
cp "$SCRIPT_DIR/tests/__init__.py" tests/
cp "$SCRIPT_DIR/tests/test_screen_1328f.py" tests/

echo ""
echo "=== Changes to commit ==="
git status
git diff --stat

echo ""
echo "Review the changes above. Press Enter to commit and push, or Ctrl+C to abort."
read -r

git add -A
git commit -m "Add crowdsource verification project

- data/unverified_cases.csv: 467 flagged 1328(f) cases for volunteer verification
- docs/volunteer_guide.md: step-by-step guide for verifying a case on PACER
- docs/submission_template.md: Google Form field reference for submissions
- README.md: added Crowdsource Verification section"

git push origin main

echo ""
echo "=== Done. Cleaning up temp directory ==="
rm -rf "$TEMP_DIR"
echo "Pushed successfully."
