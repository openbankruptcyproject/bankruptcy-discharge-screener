#!/bin/bash
# Scan all tracked + staged files for sensitive terms before pushing.
# Exit 1 if any match found. Wire into .git/hooks/pre-push for automatic protection.
#
# BLOCKLIST FORMAT (.sensitive_terms):
#   plain-term        -> substring match (original behavior)
#   WB:term           -> word-boundary match (fixes "Fink" substring-matching "Finkle")
#   CTX:term          -> word-boundary AND must co-occur on same line with a context
#                        token from the TOKEN: lines below. Use for surnames shared
#                        with unrelated public-figure judges.
#   TOKEN:string      -> context validation token. NOT blocked itself. Used only to
#                        decide whether a CTX: match is a real attorney/case reference
#                        or a false-positive surname collision with a public figure.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BLOCKLIST="$SCRIPT_DIR/.sensitive_terms"
FOUND=0

if [ ! -f "$BLOCKLIST" ]; then
    echo "ERROR: Blocklist not found at $BLOCKLIST"
    exit 1
fi

# Generic attorney/legal context words (safe to hard-code — not sensitive)
GENERIC_CTX='attorney|counsel|law firm| Esq\.? | P\.C\. | LLP |retainer|filed by|represented by|Doc\. |MFRS|adversary proceeding|bar complaint'

SUBSTR_PATTERNS=""
WB_PATTERNS=""
CTX_PATTERNS=""
TOKEN_PATTERNS=""

escape_regex() {
    printf '%s' "$1" | sed 's/[.[\*^$()+?{|]/\\&/g'
}

while IFS= read -r line; do
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "${line// }" ]] && continue

    if [[ "$line" == WB:* ]]; then
        term="${line#WB:}"
        escaped=$(escape_regex "$term")
        pat="\\b${escaped}\\b"
        if [ -z "$WB_PATTERNS" ]; then WB_PATTERNS="$pat"; else WB_PATTERNS="$WB_PATTERNS|$pat"; fi
    elif [[ "$line" == CTX:* ]]; then
        term="${line#CTX:}"
        escaped=$(escape_regex "$term")
        pat="\\b${escaped}\\b"
        if [ -z "$CTX_PATTERNS" ]; then CTX_PATTERNS="$pat"; else CTX_PATTERNS="$CTX_PATTERNS|$pat"; fi
    elif [[ "$line" == TOKEN:* ]]; then
        term="${line#TOKEN:}"
        escaped=$(escape_regex "$term")
        if [ -z "$TOKEN_PATTERNS" ]; then TOKEN_PATTERNS="$escaped"; else TOKEN_PATTERNS="$TOKEN_PATTERNS|$escaped"; fi
    else
        escaped=$(escape_regex "$line")
        if [ -z "$SUBSTR_PATTERNS" ]; then SUBSTR_PATTERNS="$escaped"; else SUBSTR_PATTERNS="$SUBSTR_PATTERNS|$escaped"; fi
    fi
done < "$BLOCKLIST"

# Context tokens used to validate CTX: matches = plain SUBSTR blocklist entries
# (anything that's a hard-block term) + explicit TOKEN: lines + generic legal-context words
CTX_VALIDATORS=""
if [ -n "$SUBSTR_PATTERNS" ]; then CTX_VALIDATORS="$SUBSTR_PATTERNS"; fi
if [ -n "$TOKEN_PATTERNS" ]; then
    if [ -z "$CTX_VALIDATORS" ]; then CTX_VALIDATORS="$TOKEN_PATTERNS"; else CTX_VALIDATORS="$CTX_VALIDATORS|$TOKEN_PATTERNS"; fi
fi
if [ -z "$CTX_VALIDATORS" ]; then CTX_VALIDATORS="$GENERIC_CTX"; else CTX_VALIDATORS="$CTX_VALIDATORS|$GENERIC_CTX"; fi
ALL_CTX="$CTX_VALIDATORS"

echo "Scanning public repo for sensitive terms..."
echo "============================================"

while IFS= read -r -d '' file; do
    [[ "$file" == *".sensitive_terms"* ]] && continue
    [[ "$file" == *".sensitive_allowlist"* ]] && continue
    [[ "$file" == *"scan_before_push"* ]] && continue
    [[ "$file" == *".git/"* ]] && continue

    if file "$file" | grep -qE 'executable|binary|image|PDF|data'; then
        continue
    fi

    file_matches=""

    if [ -n "$SUBSTR_PATTERNS" ]; then
        m=$(grep -inE "$SUBSTR_PATTERNS" "$file" 2>/dev/null)
        [ -n "$m" ] && file_matches+="$m"$'\n'
    fi

    if [ -n "$WB_PATTERNS" ]; then
        m=$(grep -inE "$WB_PATTERNS" "$file" 2>/dev/null)
        [ -n "$m" ] && file_matches+="$m"$'\n'
    fi

    # Context patterns: match the surname AND require a context token on same line
    if [ -n "$CTX_PATTERNS" ]; then
        candidate_lines=$(grep -inE "$CTX_PATTERNS" "$file" 2>/dev/null)
        if [ -n "$candidate_lines" ]; then
            m=$(echo "$candidate_lines" | grep -iE "$ALL_CTX")
            [ -n "$m" ] && file_matches+="$m"$'\n'
        fi
    fi

    if [ -n "$file_matches" ]; then
        echo ""
        echo "BLOCKED: $file"
        echo "$file_matches" | head -5
        FOUND=1
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
echo ""
echo "Scanning for fact-accuracy issues..."

ANALYZED=$(grep -rin "analyz.*4\.9 million\|analyz.*4,895" "$SCRIPT_DIR" --include="*.html" --include="*.md" 2>/dev/null | grep -v ".git/" | grep -v "scan_before_push")
if [ -n "$ANALYZED" ]; then
    echo ""
    echo "WARNING: 'analyzed 4.9 million' found (should be 'screened'):"
    echo "$ANALYZED" | head -5
    FOUND=1
fi

UNQUALIFIED_264=$(grep -rin "264 case\|264 barred\|264 violation" "$SCRIPT_DIR" --include="*.html" --include="*.md" 2>/dev/null | grep -v ".git/" | grep -v "scan_before_push" | grep -vi "sample\|verified.*district\|multi-district\|7-district")
if [ -n "$UNQUALIFIED_264" ]; then
    echo ""
    echo "WARNING: '264 cases' without scope qualifier (needs 'sample'/'multi-district'):"
    echo "$UNQUALIFIED_264" | head -5
    FOUND=1
fi

UNQUALIFIED_114=$(grep -rinE "\b114\b.*discharg|\b114\b.*granted" "$SCRIPT_DIR" --include="*.html" --include="*.md" 2>/dev/null | grep -v ".git/" | grep -v "scan_before_push" | grep -v "ld+json" | grep -v "application/ld" | grep -vi "sample\|verified.*district\|multi-district\|7-district\|Courts Granted|section-1141\|section-114 \|§1141\|section 1141")
if [ -n "$UNQUALIFIED_114" ]; then
    echo ""
    echo "WARNING: '114 discharged' without scope qualifier:"
    echo "$UNQUALIFIED_114" | head -5
    FOUND=1
fi

NATIONAL_CLAIM=$(grep -rin "national analysis.*264\|nationwide.*264\|across.*94.*district.*264" "$SCRIPT_DIR" --include="*.html" --include="*.md" 2>/dev/null | grep -v ".git/" | grep -v "scan_before_push" | grep -vi "sample\|verified.*district\|multi-district\|7-district")
if [ -n "$NATIONAL_CLAIM" ]; then
    echo ""
    echo "WARNING: findings presented as national when scope is a sample:"
    echo "$NATIONAL_CLAIM" | head -5
    FOUND=1
fi

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

BAD_COAUTHOR=$(git log origin/main..HEAD --format="%B" 2>/dev/null | grep -i "Co-Authored-By" | grep -iv "ilikemath9999")
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
