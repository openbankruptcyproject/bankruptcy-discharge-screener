#!/usr/bin/env python3
"""
Merge Attorney Submissions
===========================
Merges practice_report.py JSON submissions from multiple districts
into a single attorneys.json for the lookup page.

Usage:
  python merge_submissions.py --submissions-dir ./submissions --output attorneys.json
  python merge_submissions.py --submissions-dir ./submissions --output attorneys.json --min-cases 10

Each submission file should be a JSON file produced by:
  python practice_report.py --data-dir ./csv-exports --all --output-json report.json

The merge script extracts per-attorney metrics from each submission and
combines them. If the same attorney appears in multiple districts,
their records are merged (cases summed, rates recomputed).

Dependencies: Python 3.8+ standard library only (no pip install needed)
"""

import json
import sys
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

VERSION = '1.0.0'


def extract_attorneys(submission_path):
    """Extract attorney records from a practice_report.py JSON output."""
    with open(submission_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    profiles = data.get('profiles', [])
    if not profiles:
        print(f"  Warning: {submission_path.name} has no profiles, skipping")
        return []

    records = []
    for p in profiles:
        attorney = p.get('attorney', '').strip()
        if not attorney:
            continue

        vol = p.get('volume', {})
        out = p.get('outcomes', {})

        total_cases = vol.get('total_cases', 0)
        chapters = vol.get('by_chapter', {})
        courts = vol.get('courts', [])

        ch13_dismissed = out.get('ch13_dismissed', 0)
        ch13_discharged = out.get('ch13_discharged', 0)
        ch13_total = out.get('ch13_total', 0)

        # For overall dismissed/discharged, use ch13 + ch7 estimates
        # Ch. 7 cases that have a discharge date are discharged; rest are pending
        # But the JSON only gives us ch13 detail, so we track what we can
        ch7 = int(chapters.get('7', 0))
        ch13 = int(chapters.get('13', 0))
        ch11 = int(chapters.get('11', 0))
        ch12 = int(chapters.get('12', 0))

        records.append({
            'attorney': attorney,
            'total_cases': total_cases,
            'ch13': ch13,
            'ch7': ch7,
            'ch11': ch11,
            'ch12': ch12,
            'ch13_dismissed': ch13_dismissed,
            'ch13_discharged': ch13_discharged,
            'ch13_total': ch13_total,
            'districts': [c.lower() for c in courts],
        })

    return records


def merge_records(all_records):
    """Merge records by attorney name, combining multi-district appearances."""
    by_attorney = defaultdict(lambda: {
        'total_cases': 0,
        'ch13': 0,
        'ch7': 0,
        'ch11': 0,
        'ch12': 0,
        'ch13_dismissed': 0,
        'ch13_discharged': 0,
        'ch13_total': 0,
        'districts': set(),
    })

    for r in all_records:
        key = r['attorney']
        m = by_attorney[key]
        m['total_cases'] += r['total_cases']
        m['ch13'] += r['ch13']
        m['ch7'] += r['ch7']
        m['ch11'] += r['ch11']
        m['ch12'] += r['ch12']
        m['ch13_dismissed'] += r['ch13_dismissed']
        m['ch13_discharged'] += r['ch13_discharged']
        m['ch13_total'] += r['ch13_total']
        m['districts'].update(r['districts'])

    merged = []
    for attorney, m in by_attorney.items():
        # Compute dismissal rate from ch13 outcomes
        if m['ch13_total'] > 0:
            dismissal_rate = round(m['ch13_dismissed'] / m['ch13_total'], 4)
        else:
            dismissal_rate = 0.0

        # Quality score: simple dismissal-weighted metric
        # Lower = better. Just the dismissal rate * 60 for now.
        quality_score = round(dismissal_rate * 60, 1)

        merged.append({
            'attorney': attorney,
            'total_cases': m['total_cases'],
            'ch13': m['ch13'],
            'ch7': m['ch7'],
            'ch11': m['ch11'],
            'ch12': m['ch12'],
            'dismissal_rate': dismissal_rate,
            'quality_score': quality_score,
            'dismissed': m['ch13_dismissed'],
            'discharged': m['ch13_discharged'],
            'districts': sorted(m['districts']),
        })

    return merged


def main():
    parser = argparse.ArgumentParser(
        description='Merge practice_report.py submissions into attorneys.json'
    )
    parser.add_argument(
        '--submissions-dir', type=Path, required=True,
        help='Directory containing submission JSON files'
    )
    parser.add_argument(
        '--output', type=Path, default=Path('attorneys.json'),
        help='Output path for merged attorneys.json (default: attorneys.json)'
    )
    parser.add_argument(
        '--min-cases', type=int, default=10,
        help='Minimum total cases to include an attorney (default: 10)'
    )
    args = parser.parse_args()

    if not args.submissions_dir.exists():
        print(f"Error: {args.submissions_dir} does not exist")
        sys.exit(1)

    # Find all JSON files in submissions dir
    json_files = sorted(args.submissions_dir.glob('*.json'))
    if not json_files:
        print(f"No JSON files found in {args.submissions_dir}")
        sys.exit(1)

    print(f"Found {len(json_files)} submission files")
    print()

    # Extract all attorney records
    all_records = []
    for jf in json_files:
        print(f"  Processing: {jf.name}")
        records = extract_attorneys(jf)
        print(f"    -> {len(records)} attorneys")
        all_records.extend(records)

    print(f"\nTotal raw records: {len(all_records)}")

    # Merge duplicates
    merged = merge_records(all_records)
    print(f"After merge: {len(merged)} unique attorneys")

    # Filter by min cases
    filtered = [a for a in merged if a['total_cases'] >= args.min_cases]
    print(f"After min-cases filter ({args.min_cases}): {len(filtered)} attorneys")

    # Sort by dismissal rate descending
    filtered.sort(key=lambda a: a['dismissal_rate'], reverse=True)

    # Collect all districts
    all_districts = set()
    for a in filtered:
        all_districts.update(a['districts'])

    # Build output
    output = {
        'generated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'coverage': f"{len(all_districts)} districts: {', '.join(sorted(all_districts))}",
        'source': 'PACER Case Locator (public federal court records)',
        'total_attorneys': len(filtered),
        'total_submissions': len(json_files),
        'attorneys': filtered,
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {args.output} ({len(filtered)} attorneys, {len(all_districts)} districts)")

    # Summary stats
    total_cases = sum(a['total_cases'] for a in filtered)
    avg_dismiss = sum(a['dismissal_rate'] for a in filtered) / len(filtered) if filtered else 0
    print(f"Total cases: {total_cases:,}")
    print(f"Avg dismissal rate: {avg_dismiss:.1%}")
    print(f"Dismissal range: {min(a['dismissal_rate'] for a in filtered):.1%} - {max(a['dismissal_rate'] for a in filtered):.1%}")


if __name__ == '__main__':
    main()
