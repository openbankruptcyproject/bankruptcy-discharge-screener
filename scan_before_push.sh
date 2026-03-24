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

# ── LOAD ALLOWLIST ──
# .sensitive_allowlist lets specific files bypass specific blocklist terms.
# Format: filepath_glob|term  (one per line, # comments, blank lines ok)
ALLOWLIST="$SCRIPT_DIR/.sensitive_allowlist"
declare -a ALLOW_GLOBS=()
declare -a ALLOW_TERMS=()
if [ -f "$ALLOWLIST" ]; then
    while IFS= read -r aline; do
        [[ "$aline" =~ ^#.*$ ]] && continue
        [[ -z "${aline// }" ]] && continue
        agglob="${aline%%|*}"
        aterm="${aline##*|}"
        ALLOW_GLOBS+=("$agglob")
        ALLOW_TERMS+=("$aterm")
    done < "$ALLOWLIST"
fi

# is_allowlisted <relative_path> <matched_line>
# Returns 0 (true) if the match should be suppressed.
is_allowlisted() {
    local relpath="$1"
    local matchline="$2"
    local i
    for i in "${!ALLOW_GLOBS[@]}"; do
        # Check if file matches the glob
        # shellcheck disable=SC2254
        case "$relpath" in
            ${ALLOW_GLOBS[$i]})
                # Check if the matched line contains the allowlisted term (case-insensitive)
                if echo "$matchline" | grep -qi "${ALLOW_TERMS[$i]}"; then
                    return 0
                fi
                ;;
        esac
    done
    return 1
}

echo "Scanning public repo for sensitive terms..."
echo "============================================"

# Scan all files (not .git, not binary, not blocklist itself)
while IFS= read -r -d '' file; do
    # Skip the blocklist itself, allowlist, and this script
    [[ "$file" == *".sensitive_terms"* ]] && continue
    [[ "$file" == *".sensitive_allowlist"* ]] && continue
    [[ "$file" == *"scan_before_push"* ]] && continue
    [[ "$file" == *".git/"* ]] && continue

    # Skip binary files
    if file "$file" | grep -qE 'executable|binary|image|PDF|data'; then
        continue
    fi

    # Compute path relative to SCRIPT_DIR for allowlist matching
    relpath="${file#$SCRIPT_DIR/}"

    matches=$(grep -inE "$PATTERNS" "$file" 2>/dev/null)
    if [ -n "$matches" ]; then
        # Filter out allowlisted matches
        filtered=""
        while IFS= read -r mline; do
            if ! is_allowlisted "$relpath" "$mline"; then
                filtered="$filtered$mline"$'\n'
            fi
        done <<< "$matches"
        # Remove trailing newline and check if anything remains
        filtered="${filtered%$'\n'}"
        if [ -n "$filtered" ]; then
            echo ""
            echo "BLOCKED: $file"
            echo "$filtered" | head -5
            FOUND=1
        fi
    fi
done < <(find "$SCRIPT_DIR" -type f -not -path '*/.git/*' -print0)

echo ""
if [ $FOUND -eq 1 ]; then
    echo "============================================"
    echo "PUSH BLOCKED — sensitive terms found above."
    echo "Fix the files and try again."
    exit 1
fi

# ── FACT ACCURACY CHECK ──
# Catch inflated claims that misrepresent scope of analysis
echo ""
echo "Scanning for fact-accuracy issues..."

# "analyzed 4.9 million" — we SCREENED, not analyzed
ANALYZED=$(grep -rin "analyz.*4\.9 million\|analyz.*4,895" "$SCRIPT_DIR" --include="*.html" --include="*.md" 2>/dev/null | grep -v ".git/" | grep -v "scan_before_push")
if [ -n "$ANALYZED" ]; then
    echo ""
    echo "WARNING: 'analyzed 4.9 million' found (should be 'screened'):"
    echo "$ANALYZED" | head -5
    FOUND=1
fi

# "264 cases" without scope qualifier
UNQUALIFIED_264=$(grep -rin "264 case\|264 barred\|264 violation" "$SCRIPT_DIR" --include="*.html" --include="*.md" 2>/dev/null | grep -v ".git/" | grep -v "scan_before_push" | grep -vi "sample\|verified.*district\|multi-district\|7-district")
if [ -n "$UNQUALIFIED_264" ]; then
    echo ""
    echo "WARNING: '264 cases' without scope qualifier (needs 'sample'/'multi-district'):"
    echo "$UNQUALIFIED_264" | head -5
    FOUND=1
fi

# "114 discharged" without scope qualifier
UNQUALIFIED_114=$(grep -rin "114.*discharg\|114.*granted" "$SCRIPT_DIR" --include="*.html" --include="*.md" 2>/dev/null | grep -v ".git/" | grep -v "scan_before_push" | grep -vi "sample\|verified.*district\|multi-district\|7-district\|1141")
if [ -n "$UNQUALIFIED_114" ]; then
    echo ""
    echo "WARNING: '114 discharged' without scope qualifier:"
    echo "$UNQUALIFIED_114" | head -5
    FOUND=1
fi

# "national analysis" when it's actually a sample
NATIONAL_CLAIM=$(grep -rin "national analysis.*264\|nationwide.*264\|across.*94.*district.*264" "$SCRIPT_DIR" --include="*.html" --include="*.md" 2>/dev/null | grep -v ".git/" | grep -v "scan_before_push" | grep -vi "verified.*sample\|multi-district")
if [ -n "$NATIONAL_CLAIM" ]; then
    echo ""
    echo "WARNING: '264' presented as national finding:"
    echo "$NATIONAL_CLAIM" | head -5
    FOUND=1
fi

# Check git metadata: author/committer identities
echo "Scanning git history for identity leaks..."
BAD_AUTHORS=$(git log --all --format="%an <%ae>" | sort -u | grep -iv "ilikemath9999")
if [ -n "$BAD_AUTHORS" ]; then
    echo ""
    echo "BLOCKED: Non-anonymous author(s) found in git history:"
    echo "$BAD_AUTHORS"
    echo ""
    echo "Run: git filter-branch --env-filter to fix."
    FOUND=1
fi

# Check commit messages for Co-Authored-By leaks
BAD_COAUTHOR=$(git log --all --format="%B" | grep -i "Co-Authored-By" | grep -iv "ilikemath9999")
if [ -n "$BAD_COAUTHOR" ]; then
    echo ""
    echo "BLOCKED: Co-Authored-By leak in commit messages:"
    echo "$BAD_COAUTHOR"
    FOUND=1
fi

if [ $FOUND -eq 1 ]; then
    echo "============================================"
    echo "PUSH BLOCKED — issues found above."
    exit 1
else
    echo "All clear. No sensitive terms found."
    exit 0
fi
