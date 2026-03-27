#!/bin/bash
# Fix the YOUR_USERNAME placeholder in the live GitHub repo README
# Run from anywhere. Requires git auth for ilikemath9999 account.

set -e

REPO="https://github.com/ilikemath9999/bankruptcy-discharge-screener.git"
TMPDIR=$(mktemp -d)

echo "Cloning repo to $TMPDIR..."
git clone "$REPO" "$TMPDIR/repo"
cd "$TMPDIR/repo"

echo "Fixing README.md..."
sed -i 's|https://github.com/YOUR_USERNAME/1328f-screen.git|https://github.com/ilikemath9999/bankruptcy-discharge-screener.git|g' README.md
sed -i 's|cd 1328f-screen|cd bankruptcy-discharge-screener|g' README.md

if git diff --quiet; then
    echo "No changes needed — README already correct."
    rm -rf "$TMPDIR"
    exit 0
fi

echo "Changes:"
git diff

git add README.md
git commit -m "Fix clone URL in README"
git push origin main

echo "Done. Cleaning up..."
rm -rf "$TMPDIR"
echo "README fixed on remote."
