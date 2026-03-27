#!/usr/bin/env python3
"""
Contribute Attorney Data to the National Lookup
=================================================
Takes PACER Case Locator CSV exports and generates a submission-ready JSON
file for the attorney lookup page.

This is the self-service pipeline:
  1. Download CSVs from PCL (https://pcl.uscourts.gov) — free under $30/quarter
  2. Run: python contribute.py --data-dir ./my-csvs
  3. Output: submission_COURTCODE_TIMESTAMP.json in submissions/ folder
  4. Submit via GitHub issue or PR

Can also rebuild attorneys.json from all submissions:
  python contribute.py --rebuild

Dependencies: Python 3.8+ standard library only (no pip install needed)
"""

import csv
import json
import sys
import os
import re
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

VERSION = '1.0.0'
MIN_CASES = 10  # minimum cases to include an attorney


def parse_date(s):
    """Parse a date string, return datetime or None."""
    if not s or not s.strip():
        return None
    s = s.strip().strip('"')
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def load_csvs(data_dir):
    """Load all CSV files from a directory."""
    cases = []
    csv_files = sorted(Path(data_dir).glob('*.csv'))
    if not csv_files:
        print(f"No CSV files found in {data_dir}")
        sys.exit(1)

    for csvf in csv_files:
        try:
            with open(csvf, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    cases.append(row)
        except Exception as e:
            print(f"  Warning: could not read {csvf.name}: {e}")

    return cases


def extract_attorney_name(row):
    """Extract attorney display name from a PCL row."""
    last = row.get('lastName', '').strip()
    first = row.get('firstName', '').strip()
    if not last:
        return None
    if first:
        return f"{last}, {first}"
    return last


def profile_attorneys(cases, min_cases=MIN_CASES):
    """Build attorney profiles from PCL case data."""
    # Group cases by attorney
    by_attorney = defaultdict(list)
    for c in cases:
        role = c.get('partyRole', '').strip().lower()
        if role != 'aty':
            continue
        name = extract_attorney_name(c)
        if not name:
            continue
        by_attorney[name].append(c)

    profiles = []
    for attorney, atty_cases in by_attorney.items():
        # Deduplicate by caseId
        seen_ids = set()
        unique_cases = []
        for c in atty_cases:
            cid = c.get('caseId', '')
            if cid and cid in seen_ids:
                continue
            seen_ids.add(cid)
            unique_cases.append(c)

        total = len(unique_cases)
        if total < min_cases:
            continue

        # Chapter breakdown
        chapters = defaultdict(int)
        for c in unique_cases:
            ch = c.get('bankruptcyChapter', '').strip()
            if ch:
                chapters[ch] += 1

        # Courts
        courts = set()
        for c in unique_cases:
            court = c.get('courtId', '').strip().lower()
            if court:
                courts.add(court)

        # Outcomes (all chapters)
        dismissed = 0
        discharged = 0
        for c in unique_cases:
            has_dismiss = bool(parse_date(c.get('dateDismissed', '')))
            has_discharge = bool(parse_date(c.get('dateDischarged', '')))
            if has_dismiss:
                dismissed += 1
            elif has_discharge:
                discharged += 1

        # Dismissal rate
        resolved = dismissed + discharged
        if resolved > 0:
            dismissal_rate = round(dismissed / resolved, 4)
        else:
            dismissal_rate = 0.0

        # Quality score (simple: dismissal rate weighted)
        quality_score = round(dismissal_rate * 60, 1)

        profiles.append({
            'attorney': attorney,
            'total_cases': total,
            'ch13': int(chapters.get('13', 0)),
            'ch7': int(chapters.get('7', 0)),
            'ch11': int(chapters.get('11', 0)),
            'ch12': int(chapters.get('12', 0)),
            'dismissal_rate': dismissal_rate,
            'quality_score': quality_score,
            'dismissed': dismissed,
            'discharged': discharged,
            'districts': sorted(courts),
        })

    # Validate: dismissed + discharged should not exceed total_cases
    clean = []
    for p in profiles:
        dd = p['dismissed'] + p['discharged']
        if dd > p['total_cases'] * 1.15:
            print(f"  Warning: skipping {p['attorney']} — dismissed+discharged ({dd}) > total_cases ({p['total_cases']})")
            continue
        clean.append(p)

    clean.sort(key=lambda a: a['dismissal_rate'], reverse=True)
    return clean


def generate_submission(profiles, courts):
    """Generate a submission JSON."""
    return {
        'tool': 'contribute.py',
        'version': VERSION,
        'generated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'source': 'PACER Case Locator (public federal court records)',
        'coverage': ', '.join(sorted(courts)),
        'total_attorneys': len(profiles),
        'attorneys': profiles,
    }


def rebuild_attorneys_json(submissions_dir, output_path, min_cases=MIN_CASES):
    """Rebuild attorneys.json from all submission files."""
    json_files = sorted(Path(submissions_dir).glob('*.json'))
    if not json_files:
        print(f"No submission files found in {submissions_dir}")
        sys.exit(1)

    print(f"Found {len(json_files)} submission files")

    # Merge all attorneys
    by_key = defaultdict(lambda: {
        'total_cases': 0, 'ch13': 0, 'ch7': 0, 'ch11': 0, 'ch12': 0,
        'dismissed': 0, 'discharged': 0, 'districts': set(),
    })

    for jf in json_files:
        print(f"  Loading: {jf.name}")
        with open(jf, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for a in data.get('attorneys', []):
            key = a['attorney']
            m = by_key[key]
            m['total_cases'] += a['total_cases']
            m['ch13'] += a['ch13']
            m['ch7'] += a['ch7']
            m['ch11'] += a.get('ch11', 0)
            m['ch12'] += a.get('ch12', 0)
            m['dismissed'] += a['dismissed']
            m['discharged'] += a['discharged']
            m['districts'].update(a.get('districts', []))

    merged = []
    for attorney, m in by_key.items():
        resolved = m['dismissed'] + m['discharged']
        if resolved > 0:
            dismissal_rate = round(m['dismissed'] / resolved, 4)
        else:
            dismissal_rate = 0.0

        # Validate
        dd = m['dismissed'] + m['discharged']
        if dd > m['total_cases'] * 1.15:
            print(f"  Warning: skipping {attorney} — data inconsistency")
            continue

        if m['total_cases'] < min_cases:
            continue

        merged.append({
            'attorney': attorney,
            'total_cases': m['total_cases'],
            'ch13': m['ch13'],
            'ch7': m['ch7'],
            'ch11': m['ch11'],
            'ch12': m['ch12'],
            'dismissal_rate': dismissal_rate,
            'quality_score': round(dismissal_rate * 60, 1),
            'dismissed': m['dismissed'],
            'discharged': m['discharged'],
            'districts': sorted(m['districts']),
        })

    merged.sort(key=lambda a: a['dismissal_rate'], reverse=True)

    all_districts = set()
    for a in merged:
        all_districts.update(a['districts'])

    output = {
        'generated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'coverage': f"{len(all_districts)} districts: {', '.join(sorted(all_districts))}",
        'source': 'PACER Case Locator (public federal court records)',
        'total_attorneys': len(merged),
        'total_submissions': len(json_files),
        'attorneys': merged,
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)

    print(f"\nRebuilt {output_path}: {len(merged)} attorneys across {len(all_districts)} districts")
    return merged


def main():
    parser = argparse.ArgumentParser(
        description='Contribute attorney data to the national lookup page'
    )
    parser.add_argument(
        '--data-dir', type=Path,
        help='Directory containing PCL CSV exports'
    )
    parser.add_argument(
        '--submissions-dir', type=Path, default=Path('submissions'),
        help='Directory to store/read submissions (default: submissions/)'
    )
    parser.add_argument(
        '--rebuild', action='store_true',
        help='Rebuild attorneys.json from all submissions'
    )
    parser.add_argument(
        '--output', type=Path, default=Path('attorneys.json'),
        help='Output path for rebuilt attorneys.json (default: attorneys.json)'
    )
    parser.add_argument(
        '--min-cases', type=int, default=MIN_CASES,
        help=f'Minimum cases to include an attorney (default: {MIN_CASES})'
    )
    args = parser.parse_args()

    min_cases = args.min_cases

    if args.rebuild:
        rebuild_attorneys_json(args.submissions_dir, args.output, min_cases)
        return

    if not args.data_dir:
        parser.error("--data-dir is required (or use --rebuild)")

    if not args.data_dir.exists():
        print(f"Error: {args.data_dir} does not exist")
        sys.exit(1)

    # Load and profile
    print(f"Loading CSVs from {args.data_dir}...")
    cases = load_csvs(args.data_dir)
    print(f"Loaded {len(cases):,} rows")

    profiles = profile_attorneys(cases, min_cases)
    print(f"Profiled {len(profiles)} attorneys (min {min_cases} cases)")

    # Determine courts
    courts = set()
    for p in profiles:
        courts.update(p['districts'])

    # Generate submission
    submission = generate_submission(profiles, courts)

    # Save
    args.submissions_dir.mkdir(exist_ok=True)
    court_str = '_'.join(sorted(courts)) if courts else 'unknown'
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = args.submissions_dir / f"submission_{court_str}_{ts}.json"

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(submission, f, indent=2)

    print(f"\nSubmission saved: {out_path}")
    print(f"  {len(profiles)} attorneys across {', '.join(sorted(courts))}")
    print(f"\nTo add to the lookup page:")
    print(f"  python contribute.py --rebuild --submissions-dir {args.submissions_dir}")
    print(f"\nOr submit via GitHub issue:")
    print(f"  https://github.com/ilikemath9999/bankruptcy-discharge-screener/issues/new?template=attorney-report.md")


if __name__ == '__main__':
    main()
