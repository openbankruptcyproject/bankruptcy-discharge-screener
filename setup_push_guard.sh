#!/bin/bash
# Run this after re-initializing the public repo git.
# Installs a pre-push hook that scans for sensitive terms.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_DIR="$SCRIPT_DIR/.git/hooks"

if [ ! -d "$HOOK_DIR" ]; then
    echo "ERROR: .git/hooks not found. Initialize the repo first."
    exit 1
fi

cat > "$HOOK_DIR/pre-push" << 'EOF'
#!/bin/bash
# Pre-push hook: scan for sensitive terms before allowing push
REPO_ROOT="$(git rev-parse --show-toplevel)"
bash "$REPO_ROOT/scan_before_push.sh"
EOF

chmod +x "$HOOK_DIR/pre-push"
echo "Pre-push hook installed at $HOOK_DIR/pre-push"
echo "Every push will now be scanned against .sensitive_terms"
