#!/bin/bash
# Scan all tracked + staged files for sensitive terms before pushing.
# Exit 1 if any match found. Wire into .git/hooks/pre-push for automatic protection.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BLOCKLIST="$SCRIPT_DIR/.sensitive_terms"
FOUND=0

if [ ! -f "$BLOCKLIST" ]; then
    echo "ERROR: Blocklist not found at $BLOCKLIST"
    exit 1
fi

# Build grep pattern from blocklist (skip comments and blank lines)
PATTERNS=""
while IFS= read -r line; do
    # Skip comments and empty lines
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "${line// }" ]] && continue
    # Escape special regex chars
    escaped=$(printf '%s' "$line" | sed 's/[.[\*^$()+?{|]/\\&/g')
    if [ -z "$PATTERNS" ]; then
        PATTERNS="$escaped"
    else
        PATTERNS="$PATTERNS|$escaped"
    fi
done < "$BLOCKLIST"

if [ -z "$PATTERNS" ]; then
    echo "WARNING: No patterns loaded from blocklist."
    exit 0
fi

echo "Scanning public repo for sensitive terms..."
echo "============================================"

# Scan all files (not .git, not binary, not blocklist itself)
while IFS= read -r -d '' file; do
    # Skip the blocklist itself and this script
    [[ "$file" == *".sensitive_terms"* ]] && continue
    [[ "$file" == *"scan_before_push"* ]] && continue
    [[ "$file" == *".git/"* ]] && continue

    # Skip binary files
    if file "$file" | grep -qE 'executable|binary|image|PDF|data'; then
        continue
    fi

    matches=$(grep -inE "$PATTERNS" "$file" 2>/dev/null)
    if [ -n "$matches" ]; then
        echo ""
        echo "BLOCKED: $file"
        echo "$matches" | head -5
        FOUND=1
    fi
done < <(find "$SCRIPT_DIR" -type f -not -path '*/.git/*' -print0)

echo ""
if [ $FOUND -eq 1 ]; then
    echo "============================================"
    echo "PUSH BLOCKED — sensitive terms found above."
    echo "Fix the files and try again."
    exit 1
else
    echo "All clear. No sensitive terms found."
    exit 0
fi
