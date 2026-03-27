#!/usr/bin/env python3
"""
Export 1328(f) flagged cases to a public CSV for crowdsource verification.

Strips debtor names (privacy). Keeps case numbers, dates, attorneys, courts
— all public record from PACER.

Usage:
    python export_unverified_cases.py
"""

import csv
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(SCRIPT_DIR, "..", "pacer", "scripts", "1328f_screen_results.json")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "data", "unverified_cases.csv")

FIELDS = [
    "case_number",
    "court",
    "date_filed",
    "prior_case_number",
    "prior_court",
    "prior_chapter",
    "prior_date_discharged",
    "gap_days",
    "bar_type",
    "disposition",
    "attorney",
    "status",
    "verified_by",
    "notes",
]


def normalize_case_number(raw):
    """Convert PACER internal format to readable case number.
    e.g. '4:2023bk40068' -> '23-40068' (strip division prefix and 'bk')
    """
    if not raw:
        return raw
    # Remove division prefix (e.g. "4:" or "2:")
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    # Remove 'bk' in the middle
    raw = raw.replace("bk", "-")
    # Shorten year: 2023 -> 23
    if len(raw) > 4 and raw[:4].isdigit():
        raw = raw[2:]
    return raw


def main():
    with open(INPUT_FILE) as f:
        data = json.load(f)

    rows = []
    seen = set()  # deduplicate by (ch13_case, prior_case) pair

    for bar_type, hits in [("f1", data.get("f1_hits", [])), ("f2", data.get("f2_hits", []))]:
        for hit in hits:
            key = (hit["ch13_case"], hit["prior_case"])
            if key in seen:
                continue
            seen.add(key)

            # Determine disposition
            if hit.get("ch13_discharged"):
                disposition = "discharged"
            elif hit.get("ch13_dismissed"):
                disposition = "dismissed"
            else:
                disposition = "pending"

            # Attorney on the Ch.13 case
            attorneys = hit.get("ch13_all_attys", [])
            attorney = "; ".join(attorneys) if attorneys else ""

            rows.append({
                "case_number": normalize_case_number(hit["ch13_case"]),
                "court": hit.get("ch13_court", ""),
                "date_filed": hit.get("ch13_filed", ""),
                "prior_case_number": normalize_case_number(hit["prior_case"]),
                "prior_court": hit.get("prior_court", ""),
                "prior_chapter": hit.get("prior_chapter", ""),
                "prior_date_discharged": hit.get("prior_discharge", ""),
                "gap_days": hit.get("gap_days", ""),
                "bar_type": bar_type,
                "disposition": disposition,
                "attorney": attorney,
                "status": "UNVERIFIED",
                "verified_by": "",
                "notes": "",
            })

    # Sort by gap_days ascending (most egregious first)
    rows.sort(key=lambda r: int(r["gap_days"]) if r["gap_days"] else 9999)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} cases to {OUTPUT_FILE}")
    print(f"  f1 (4-year bar): {sum(1 for r in rows if r['bar_type'] == 'f1')}")
    print(f"  f2 (2-year bar): {sum(1 for r in rows if r['bar_type'] == 'f2')}")

    # Sanity check: no debtor names
    with open(OUTPUT_FILE) as f:
        content = f.read()
    header = content.split("\n")[0]
    if "debtor" in header.lower() or "name" in header.lower():
        print("WARNING: Output may contain debtor names!")
        sys.exit(1)
    else:
        print("Privacy check passed: no name columns in output.")


if __name__ == "__main__":
    main()
