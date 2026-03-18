#!/usr/bin/env python3
r"""
Attorney Practice Report Generator
====================================
Generates a comprehensive practice quality profile for bankruptcy attorneys
using PACER Case Locator CSV exports.

Metrics: volume, chapter mix, outcomes, case duration, statutory compliance
(1328(f), 109(g)), repeat debtor analysis, and optional comparative tables.

Data: PACER Case Locator CSV exports (https://pcl.uscourts.gov)
Dependencies: Python 3.8+ standard library only (no pip install needed)

Usage:
  python practice_report.py --data-dir ./csv-exports --target Smith_John
  python practice_report.py --data-dir ./csv-exports --target Smith_John --control Jones_Bob
  python practice_report.py --data-dir ./csv-exports --target Smith_John --output-json report.json
  python practice_report.py --data-dir ./csv-exports --target Smith_John --oneline
  python practice_report.py --data-dir ./csv-exports --all
"""

import csv
import re
import os
import sys
import glob
import json
import argparse
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# -- Constants ---------------------------------------------------------------

BAPCPA_EFFECTIVE = datetime(2005, 10, 17)
WINDOW_F1_DAYS = 4 * 365 + 1   # 4 years (1328(f)(1))
WINDOW_F2_DAYS = 2 * 365 + 1   # 2 years (1328(f)(2))
WINDOW_109G_DAYS = 180          # 109(g) refiling bar

SUFFIXES = re.compile(
    r'\b(jr\.?|sr\.?|ii|iii|iv|v|vi|vii|viii|2nd|3rd|4th)\s*$',
    re.IGNORECASE
)

VERSION = '1.1.0'


# -- Name Normalization (self-contained copy from screen_1328f.py) -----------

def normalize_name(name: str) -> str:
    """Normalize a debtor name for matching."""
    if not name:
        return ""
    n = name.lower().strip()
    n = n.replace(".", "")
    n = re.sub(r'\bnmn\b', '', n)
    n = SUFFIXES.sub('', n).strip()
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def extract_names(case_title: str) -> list:
    """Extract individual debtor names from a case title."""
    if not case_title:
        return []
    parts = re.split(r'\s+and\s+', case_title, flags=re.IGNORECASE)
    names = []
    for part in parts:
        norm = normalize_name(part)
        if norm:
            names.append(norm)
            tokens = norm.split()
            if len(tokens) >= 2:
                fl_key = f"{tokens[0]} {tokens[-1]}"
                if fl_key != norm:
                    names.append(fl_key)
    return names


# -- Attorney Key Handling ---------------------------------------------------

def make_display_name(atty_key: str) -> str:
    """Convert 'LastName_FirstName' key to 'LastName, FirstName' display format."""
    parts = atty_key.split("_", 1)
    if len(parts) == 2:
        return f"{parts[0]}, {parts[1]}"
    return atty_key


def build_attorney_sets(target_keys, control_keys):
    """Build canonical display-name sets from CLI attorney keys."""
    target_canonical = set()
    control_canonical = set()
    display_map = {}
    all_keys = set()

    for key in target_keys:
        display = make_display_name(key)
        target_canonical.add(display)
        display_map[key] = display
        all_keys.add(key)

    for key in control_keys:
        display = make_display_name(key)
        control_canonical.add(display)
        display_map[key] = display
        all_keys.add(key)

    return target_canonical, control_canonical, all_keys, display_map


# -- CSV Loading -------------------------------------------------------------

def discover_csvs(data_dir: Path, attorney_keys: set = None, courts: set = None):
    """Discover PACER CSV files matching the expected filename pattern."""
    all_csvs = sorted(glob.glob(str(data_dir / "api_*.csv")))
    pattern = re.compile(
        r'^api_(.+)_([a-z]+(?:bk|courts))_(\d{8}(?:_\d+)*)\.csv$',
        re.IGNORECASE
    )

    groups = defaultdict(list)
    for csv_path in all_csvs:
        basename = os.path.basename(csv_path)
        m = pattern.match(basename)
        if m:
            atty_key = m.group(1)
            court = m.group(2).lower()
            if attorney_keys and atty_key not in attorney_keys:
                continue
            if courts and court not in courts:
                continue
            groups[(atty_key, court)].append(csv_path)

    result = []
    for (atty_key, court), files in sorted(groups.items()):
        result.append((files[-1], atty_key, court))

    return result


def discover_all_attorney_keys(data_dir: Path, courts: set = None):
    """Discover all unique attorney keys from CSV filenames in a directory."""
    csvs = discover_csvs(data_dir, attorney_keys=None, courts=courts)
    keys = set()
    for _, atty_key, _ in csvs:
        keys.add(atty_key)
    return sorted(keys)


def load_all_cases(data_dir: Path, attorney_keys: set, display_map: dict,
                   target_canonical: set, courts: set = None):
    """Load all cases from PACER CSV exports, deduplicating by caseId."""
    csv_files = discover_csvs(data_dir, attorney_keys, courts)

    if not csv_files:
        print("ERROR: No matching CSV files found.", file=sys.stderr)
        print(f"  Searched: {data_dir}", file=sys.stderr)
        print(f"  Expected pattern: api_{{LastName_FirstName}}_{{court}}_{{timestamp}}.csv",
              file=sys.stderr)
        if attorney_keys:
            print(f"  Attorney keys: {', '.join(sorted(attorney_keys))}", file=sys.stderr)
        sys.exit(1)

    seen_case_ids = {}
    case_attorneys = defaultdict(set)
    file_count = 0
    row_count = 0

    for csv_path, atty_key, court in csv_files:
        display_name = display_map.get(atty_key, make_display_name(atty_key))
        file_count += 1

        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_count += 1
                case_id = row.get('caseId', '').strip()
                if not case_id:
                    continue

                case_attorneys[case_id].add(display_name)

                if case_id not in seen_case_ids:
                    row['_attorney'] = display_name
                    row['_source_file'] = os.path.basename(csv_path)
                    seen_case_ids[case_id] = row
                else:
                    existing = seen_case_ids[case_id]
                    if display_name in target_canonical and existing['_attorney'] not in target_canonical:
                        existing['_attorney'] = display_name

    print(f"Loaded {len(seen_case_ids):,} unique cases from {file_count} CSV files "
          f"({row_count:,} total rows)")
    return list(seen_case_ids.values()), case_attorneys


# -- Date Parsing ------------------------------------------------------------

def parse_date(date_str: str):
    """Parse YYYY-MM-DD date string. Returns datetime or None."""
    if not date_str or not date_str.strip():
        return None
    try:
        return datetime.strptime(date_str.strip(), '%Y-%m-%d')
    except ValueError:
        return None


# -- Metric Computation ------------------------------------------------------

def compute_attorney_profile(cases, case_attorneys, attorney_display_name):
    """Compute all metrics for a single attorney.

    Returns a dict with all metric groups.
    """
    # Filter to cases associated with this attorney
    atty_cases = [c for c in cases
                  if attorney_display_name in case_attorneys.get(c.get('caseId', ''), set())]

    if not atty_cases:
        return None

    profile = {
        'attorney': attorney_display_name,
        'volume': compute_volume(atty_cases),
        'outcomes': compute_outcomes(atty_cases),
        'duration': compute_duration(atty_cases),
        'statutory': compute_statutory(cases, case_attorneys, attorney_display_name, atty_cases),
        'repeat_debtors': compute_repeat_debtors(atty_cases),
    }
    return profile


def compute_volume(atty_cases):
    """Compute volume profile metrics."""
    total = len(atty_cases)

    # Chapter breakdown
    chapter_counts = defaultdict(int)
    for c in atty_cases:
        ch = c.get('bankruptcyChapter', '').strip()
        if ch:
            chapter_counts[ch] += 1

    # Date range
    dates_filed = []
    for c in atty_cases:
        d = parse_date(c.get('dateFiled', ''))
        if d:
            dates_filed.append(d)

    earliest = min(dates_filed) if dates_filed else None
    latest = max(dates_filed) if dates_filed else None

    # Filing velocity
    velocity = 0.0
    if earliest and latest and earliest != latest:
        span_years = (latest - earliest).days / 365.25
        if span_years > 0:
            velocity = round(total / span_years, 1)

    # Courts
    courts = set()
    for c in atty_cases:
        court = c.get('courtId', '').strip()
        if court:
            courts.add(court.upper())

    return {
        'total_cases': total,
        'by_chapter': dict(sorted(chapter_counts.items())),
        'chapter_mix': {ch: round(100 * cnt / total, 1) for ch, cnt in sorted(chapter_counts.items())} if total else {},
        'earliest_filing': earliest.strftime('%Y-%m-%d') if earliest else None,
        'latest_filing': latest.strftime('%Y-%m-%d') if latest else None,
        'filing_velocity_per_year': velocity,
        'courts': sorted(courts),
        'court_count': len(courts),
    }


def compute_outcomes(atty_cases):
    """Compute outcome analysis (Ch. 13 focus)."""
    ch13_cases = [c for c in atty_cases
                  if c.get('bankruptcyChapter', '').strip() == '13']
    total_ch13 = len(ch13_cases)

    if total_ch13 == 0:
        return {
            'ch13_total': 0,
            'ch13_dismissed': 0, 'ch13_dismissed_pct': 0.0,
            'ch13_discharged': 0, 'ch13_discharged_pct': 0.0,
            'ch13_pending': 0, 'ch13_pending_pct': 0.0,
            'disposition_breakdown': {},
        }

    dismissed = 0
    discharged = 0
    pending = 0
    disposition_counts = defaultdict(int)

    for c in ch13_cases:
        has_dismiss = bool(parse_date(c.get('dateDismissed', '')))
        has_discharge = bool(parse_date(c.get('dateDischarged', '')))
        disp = c.get('disposition', '').strip().strip('"')

        if has_dismiss:
            dismissed += 1
        elif has_discharge:
            discharged += 1
        else:
            pending += 1

        if disp:
            disposition_counts[disp] += 1

    return {
        'ch13_total': total_ch13,
        'ch13_dismissed': dismissed,
        'ch13_dismissed_pct': round(100 * dismissed / total_ch13, 1),
        'ch13_discharged': discharged,
        'ch13_discharged_pct': round(100 * discharged / total_ch13, 1),
        'ch13_pending': pending,
        'ch13_pending_pct': round(100 * pending / total_ch13, 1),
        'disposition_breakdown': dict(sorted(disposition_counts.items(),
                                             key=lambda x: -x[1])),
    }


def compute_duration(atty_cases):
    """Compute case duration metrics (Ch. 13 focus)."""
    ch13_cases = [c for c in atty_cases
                  if c.get('bankruptcyChapter', '').strip() == '13']

    dismiss_days = []
    discharge_days = []

    for c in ch13_cases:
        filed = parse_date(c.get('dateFiled', ''))
        if not filed:
            continue

        dismissed = parse_date(c.get('dateDismissed', ''))
        discharged = parse_date(c.get('dateDischarged', ''))

        if dismissed:
            days = (dismissed - filed).days
            if days >= 0:
                dismiss_days.append(days)
        elif discharged:
            days = (discharged - filed).days
            if days >= 0:
                discharge_days.append(days)

    def median(lst):
        if not lst:
            return None
        s = sorted(lst)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2

    total_dismissed = len(dismiss_days)
    pct_90 = round(100 * sum(1 for d in dismiss_days if d <= 90) / total_dismissed, 1) if total_dismissed else 0.0
    pct_180 = round(100 * sum(1 for d in dismiss_days if d <= 180) / total_dismissed, 1) if total_dismissed else 0.0

    return {
        'median_days_to_dismissal': median(dismiss_days),
        'median_days_to_discharge': median(discharge_days),
        'dismissed_within_90d': sum(1 for d in dismiss_days if d <= 90),
        'dismissed_within_90d_pct': pct_90,
        'dismissed_within_180d': sum(1 for d in dismiss_days if d <= 180),
        'dismissed_within_180d_pct': pct_180,
        'total_dismissed_with_dates': total_dismissed,
        'total_discharged_with_dates': len(discharge_days),
    }


def compute_statutory(all_cases, case_attorneys, attorney_display_name, atty_cases):
    """Compute statutory compliance screens: 1328(f) and 109(g)."""
    ch13_cases = [c for c in atty_cases
                  if c.get('bankruptcyChapter', '').strip() == '13']
    total_ch13 = len(ch13_cases)

    # Build debtor groups across ALL cases (not just this attorney)
    debtor_groups = defaultdict(list)
    for c in all_cases:
        title = c.get('caseTitle', '')
        for key in extract_names(title):
            debtor_groups[key].append(c)

    # 1328(f) screening
    f1_count = 0
    f2_count = 0
    f1_f2_seen = set()

    for ch13 in ch13_cases:
        ch13_filed = parse_date(ch13.get('dateFiled', ''))
        if not ch13_filed or ch13_filed < BAPCPA_EFFECTIVE:
            continue

        ch13_case_id = ch13.get('caseId', '')
        title = ch13.get('caseTitle', '')
        name_keys = extract_names(title)

        for nk in name_keys:
            for prior in debtor_groups.get(nk, []):
                prior_case_id = prior.get('caseId', '')
                if prior_case_id == ch13_case_id:
                    continue

                # Prior case must have resulted in a discharge
                prior_discharge = parse_date(prior.get('dateDischarged', ''))
                if not prior_discharge or prior_discharge >= ch13_filed:
                    continue

                # Gap measured from prior FILING date, not discharge date
                # See In re Blendheim, 803 F.3d 477 (9th Cir. 2015)
                prior_filed = parse_date(prior.get('dateFiled', ''))
                if not prior_filed or prior_filed >= ch13_filed:
                    continue

                gap_days = (ch13_filed - prior_filed).days
                prior_ch = prior.get('bankruptcyChapter', '').strip()

                key_f1 = (prior_case_id, ch13_case_id, 'f1')
                if prior_ch in ('7', '11', '12') and gap_days <= WINDOW_F1_DAYS:
                    if key_f1 not in f1_f2_seen:
                        f1_f2_seen.add(key_f1)
                        f1_count += 1

                key_f2 = (prior_case_id, ch13_case_id, 'f2')
                if prior_ch == '13' and gap_days <= WINDOW_F2_DAYS:
                    if key_f2 not in f1_f2_seen:
                        f1_f2_seen.add(key_f2)
                        f2_count += 1

    # 109(g) screening: dismissed -> refiled within 180 days, same attorney
    # NOTE: These are POTENTIAL flags only. 109(g) only applies when:
    #   (1) case was dismissed for willful failure to comply with court orders, OR
    #   (2) debtor voluntarily dismissed after a creditor filed for stay relief.
    # Most dismissals are without prejudice and do not trigger 109(g).
    # Prejudice periods can also be shortened by motion.
    # Group this attorney's cases by debtor
    atty_debtor_groups = defaultdict(list)
    for c in atty_cases:
        title = c.get('caseTitle', '')
        for key in extract_names(title):
            atty_debtor_groups[key].append(c)

    g_count = 0
    g_seen = set()
    for nk, group in atty_debtor_groups.items():
        if len(group) < 2:
            continue
        unique = {}
        for c in group:
            cid = c.get('caseId', '')
            if cid not in unique:
                unique[cid] = c
        group_list = list(unique.values())
        if len(group_list) < 2:
            continue

        for dismissed_case in group_list:
            dismiss_date = parse_date(dismissed_case.get('dateDismissed', ''))
            if not dismiss_date:
                continue
            dismissed_id = dismissed_case.get('caseId', '')

            for refiled_case in group_list:
                refiled_id = refiled_case.get('caseId', '')
                if refiled_id == dismissed_id:
                    continue
                refiled_date = parse_date(refiled_case.get('dateFiled', ''))
                if not refiled_date:
                    continue
                if refiled_date <= dismiss_date:
                    continue

                gap = (refiled_date - dismiss_date).days
                if gap <= WINDOW_109G_DAYS:
                    pair_key = (dismissed_id, refiled_id)
                    if pair_key not in g_seen:
                        g_seen.add(pair_key)
                        g_count += 1

    # Ch. 7 -> Ch. 13 pipeline (same attorney, same debtor)
    pipeline_count = 0
    pipeline_seen = set()
    for nk, group in atty_debtor_groups.items():
        unique = {}
        for c in group:
            cid = c.get('caseId', '')
            if cid not in unique:
                unique[cid] = c
        group_list = list(unique.values())
        if len(group_list) < 2:
            continue

        ch7_cases = [c for c in group_list if c.get('bankruptcyChapter', '').strip() == '7']
        ch13_cases_g = [c for c in group_list if c.get('bankruptcyChapter', '').strip() == '13']

        for ch7 in ch7_cases:
            ch7_discharge = parse_date(ch7.get('dateDischarged', ''))
            if not ch7_discharge:
                continue
            ch7_id = ch7.get('caseId', '')

            for ch13 in ch13_cases_g:
                ch13_filed = parse_date(ch13.get('dateFiled', ''))
                if not ch13_filed or ch13_filed <= ch7_discharge:
                    continue
                ch13_id = ch13.get('caseId', '')
                pair_key = (ch7_id, ch13_id)
                if pair_key not in pipeline_seen:
                    pipeline_seen.add(pair_key)
                    pipeline_count += 1

    rate_per_1k = lambda count: round(1000 * count / total_ch13, 1) if total_ch13 else 0.0

    return {
        'f1_hits': f1_count,
        'f1_rate_per_1k': rate_per_1k(f1_count),
        'f2_hits': f2_count,
        'f2_rate_per_1k': rate_per_1k(f2_count),
        'g_109_hits': g_count,
        'g_109_rate_per_1k': rate_per_1k(g_count),
        'ch7_to_ch13_pipeline': pipeline_count,
        'ch7_to_ch13_rate_per_1k': rate_per_1k(pipeline_count),
        'ch13_total': total_ch13,
    }


def compute_repeat_debtors(atty_cases):
    """Compute repeat debtor analysis."""
    debtor_cases = defaultdict(set)
    for c in atty_cases:
        title = c.get('caseTitle', '')
        case_id = c.get('caseId', '')
        if not case_id:
            continue
        # Use first+last key only (more conservative matching)
        norm = normalize_name(title)
        if not norm:
            continue
        tokens = norm.split()
        if len(tokens) >= 2:
            fl_key = f"{tokens[0]} {tokens[-1]}"
            debtor_cases[fl_key].add(case_id)
        else:
            debtor_cases[norm].add(case_id)

    repeats = {k: v for k, v in debtor_cases.items() if len(v) >= 2}
    total_debtors = len(debtor_cases)

    return {
        'total_unique_debtors': total_debtors,
        'debtors_with_2plus_cases': len(repeats),
        'serial_filing_rate_pct': round(100 * len(repeats) / total_debtors, 1) if total_debtors else 0.0,
        'max_cases_single_debtor': max((len(v) for v in repeats.values()), default=0),
    }


# -- District-Level Computation ----------------------------------------------

def compute_district_profile(cases, court_id):
    """Compute aggregate metrics for an entire district (court)."""
    court_cases = [c for c in cases
                   if c.get('courtId', '').strip().lower() == court_id.lower()]
    if not court_cases:
        return None

    # Reuse the same metric functions by treating all court cases as one pool
    vol = compute_volume(court_cases)
    out = compute_outcomes(court_cases)
    dur = compute_duration(court_cases)
    rep = compute_repeat_debtors(court_cases)

    # Simplified statutory screen (no attorney filtering — all cases in district)
    ch13_cases = [c for c in court_cases
                  if c.get('bankruptcyChapter', '').strip() == '13']
    total_ch13 = len(ch13_cases)

    # 1328(f) screen across district
    debtor_groups = defaultdict(list)
    for c in cases:  # use ALL cases for prior discharge matching
        title = c.get('caseTitle', '')
        for key in extract_names(title):
            debtor_groups[key].append(c)

    f1_count = 0
    f2_count = 0
    seen = set()
    for ch13 in ch13_cases:
        ch13_filed = parse_date(ch13.get('dateFiled', ''))
        if not ch13_filed or ch13_filed < BAPCPA_EFFECTIVE:
            continue
        ch13_case_id = ch13.get('caseId', '')
        for nk in extract_names(ch13.get('caseTitle', '')):
            for prior in debtor_groups.get(nk, []):
                prior_id = prior.get('caseId', '')
                if prior_id == ch13_case_id:
                    continue
                prior_discharge = parse_date(prior.get('dateDischarged', ''))
                if not prior_discharge or prior_discharge >= ch13_filed:
                    continue
                gap = (ch13_filed - prior_discharge).days
                prior_ch = prior.get('bankruptcyChapter', '').strip()
                if prior_ch in ('7', '11', '12') and gap <= WINDOW_F1_DAYS:
                    k = (prior_id, ch13_case_id, 'f1')
                    if k not in seen:
                        seen.add(k)
                        f1_count += 1
                if prior_ch == '13' and gap <= WINDOW_F2_DAYS:
                    k = (prior_id, ch13_case_id, 'f2')
                    if k not in seen:
                        seen.add(k)
                        f2_count += 1

    rate_per_1k = lambda count: round(1000 * count / total_ch13, 1) if total_ch13 else 0.0

    # Count unique attorneys in district
    atty_set = set()
    for c in court_cases:
        atty = c.get('_attorney', '')
        if atty:
            atty_set.add(atty)

    return {
        'district': court_id.upper(),
        'volume': vol,
        'outcomes': out,
        'duration': dur,
        'repeat_debtors': rep,
        'statutory': {
            'f1_hits': f1_count,
            'f1_rate_per_1k': rate_per_1k(f1_count),
            'f2_hits': f2_count,
            'f2_rate_per_1k': rate_per_1k(f2_count),
            'ch13_total': total_ch13,
        },
        'attorney_count': len(atty_set),
    }


def format_district_oneline(dp):
    """Format a one-line summary for a district."""
    out = dp['outcomes']
    stat = dp['statutory']
    f_total = stat['f1_hits'] + stat['f2_hits']
    ch13 = out['ch13_total']
    f_pct = f"{100 * f_total / ch13:.1f}%" if ch13 else "N/A"
    dismiss_pct = f"{out['ch13_dismissed_pct']:.1f}%" if ch13 else "N/A"
    med = dp['duration']['median_days_to_dismissal']
    med_str = str(int(med)) if med is not None else "  -"

    return (f"{dp['district']:<8} | "
            f"{ch13:>6,} Ch.13 | "
            f"{dismiss_pct:>6} dismissed | "
            f"med {med_str:>4}d | "
            f"{f_total:>4} 1328f ({f_pct:>5}) | "
            f"{dp['attorney_count']} attys")


def print_district_report(dp):
    """Print full report for a district."""
    print()
    print("=" * 78)
    print("  DISTRICT PRACTICE REPORT")
    print(f"  {dp['district']}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Attorneys in dataset: {dp['attorney_count']}")
    print("=" * 78)
    print_volume(dp['volume'])
    print_outcomes(dp['outcomes'])
    print_duration(dp['duration'])

    # Simplified statutory section
    stat = dp['statutory']
    print("-" * 78)
    print("  STATUTORY COMPLIANCE (District-Wide)")
    print("-" * 78)
    print()
    print(f"  Ch. 13 case base:           {stat['ch13_total']:,}")
    print()
    print(f"  {'Screen':<32} {'Hits':<8} {'Rate/1K':<10}")
    print(f"  {'-'*50}")
    print(f"  {'1328(f)(1) (4-yr bar)':<32} {stat['f1_hits']:<8} {stat['f1_rate_per_1k']:.1f}")
    print(f"  {'1328(f)(2) (2-yr bar)':<32} {stat['f2_hits']:<8} {stat['f2_rate_per_1k']:.1f}")
    print()

    print_repeat_debtors(dp['repeat_debtors'])
    print_footer()


# -- Output: Text -----------------------------------------------------------

def print_header(attorney_name):
    """Print report header."""
    print()
    print("=" * 78)
    print("  ATTORNEY PRACTICE REPORT")
    print(f"  {attorney_name}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 78)


def print_volume(vol):
    """Print volume profile section."""
    print()
    print("-" * 78)
    print("  VOLUME PROFILE")
    print("-" * 78)
    print()
    print(f"  Total cases:         {vol['total_cases']:,}")
    print(f"  Date range:          {vol['earliest_filing'] or 'N/A'} to {vol['latest_filing'] or 'N/A'}")
    print(f"  Filing velocity:     {vol['filing_velocity_per_year']:.1f} cases/year")
    print(f"  Courts active:       {', '.join(vol['courts']) if vol['courts'] else 'N/A'} ({vol['court_count']})")
    print()

    if vol['by_chapter']:
        print(f"  {'Chapter':<12} {'Cases':<10} {'Mix':<8}")
        print(f"  {'-'*30}")
        for ch, cnt in sorted(vol['by_chapter'].items()):
            pct = vol['chapter_mix'].get(ch, 0)
            print(f"  Ch. {ch:<7} {cnt:<10,} {pct:.1f}%")
    print()


def print_outcomes(out):
    """Print outcome analysis section."""
    print("-" * 78)
    print("  OUTCOME ANALYSIS (Ch. 13)")
    print("-" * 78)
    print()

    if out['ch13_total'] == 0:
        print("  No Ch. 13 cases found.")
        print()
        return

    print(f"  Ch. 13 caseload:     {out['ch13_total']:,}")
    print(f"  Dismissed:           {out['ch13_dismissed']:,} ({out['ch13_dismissed_pct']:.1f}%)")
    print(f"  Discharged:          {out['ch13_discharged']:,} ({out['ch13_discharged_pct']:.1f}%)")
    print(f"  Pending/Open:        {out['ch13_pending']:,} ({out['ch13_pending_pct']:.1f}%)")
    print()

    if out['disposition_breakdown']:
        print(f"  {'Disposition':<65} {'Count':<6}")
        print(f"  {'-'*71}")
        for disp, cnt in list(out['disposition_breakdown'].items())[:10]:
            label = disp[:62] + "..." if len(disp) > 62 else disp
            print(f"  {label:<65} {cnt:<6}")
    print()


def print_duration(dur):
    """Print case duration section."""
    print("-" * 78)
    print("  CASE DURATION (Ch. 13)")
    print("-" * 78)
    print()

    med_dismiss = dur['median_days_to_dismissal']
    med_discharge = dur['median_days_to_discharge']

    print(f"  Median days to dismissal:   {med_dismiss if med_dismiss is not None else 'N/A'}"
          f"  (n={dur['total_dismissed_with_dates']})")
    print(f"  Median days to discharge:   {med_discharge if med_discharge is not None else 'N/A'}"
          f"  (n={dur['total_discharged_with_dates']})")
    print()

    if dur['total_dismissed_with_dates']:
        print(f"  Dismissed within 90 days:   {dur['dismissed_within_90d']:,}"
              f" ({dur['dismissed_within_90d_pct']:.1f}%)")
        print(f"  Dismissed within 180 days:  {dur['dismissed_within_180d']:,}"
              f" ({dur['dismissed_within_180d_pct']:.1f}%)")
    print()


def print_statutory(stat):
    """Print statutory compliance section."""
    print("-" * 78)
    print("  STATUTORY COMPLIANCE")
    print("-" * 78)
    print()
    print(f"  Ch. 13 case base:           {stat['ch13_total']:,}")
    print()
    print(f"  {'Screen':<32} {'Hits':<8} {'Rate/1K':<10}")
    print(f"  {'-'*50}")
    print(f"  {'1328(f)(1) (4-yr bar)':<32} {stat['f1_hits']:<8} {stat['f1_rate_per_1k']:.1f}")
    print(f"  {'1328(f)(2) (2-yr bar)':<32} {stat['f2_hits']:<8} {stat['f2_rate_per_1k']:.1f}")
    print(f"  {'109(g) rapid refile*':<32} {stat['g_109_hits']:<8} {stat['g_109_rate_per_1k']:.1f}")
    print(f"  {'Ch.7 -> Ch.13 pipeline':<32} {stat['ch7_to_ch13_pipeline']:<8} {stat['ch7_to_ch13_rate_per_1k']:.1f}")
    print()
    print("  * 109(g) flags are potential only. The 180-day bar requires dismissal")
    print("    for willful noncompliance or voluntary dismissal after stay relief")
    print("    motion. Most routine dismissals do not trigger 109(g).")
    print("    Ch.7->Ch.13 pipeline includes legitimate 'Chapter 20' strategies.")
    print()


def print_repeat_debtors(rep):
    """Print repeat debtor section."""
    print("-" * 78)
    print("  DEBTOR PATTERNS")
    print("-" * 78)
    print()
    print(f"  Unique debtors:              {rep['total_unique_debtors']:,}")
    print(f"  Debtors with 2+ cases:       {rep['debtors_with_2plus_cases']:,}")
    print(f"  Serial filing rate:          {rep['serial_filing_rate_pct']:.1f}%")
    print(f"  Max cases, single debtor:    {rep['max_cases_single_debtor']}")
    print()


def print_comparative(profiles):
    """Print side-by-side comparison table."""
    if len(profiles) < 2:
        return

    print()
    print("=" * 78)
    print("  COMPARATIVE ANALYSIS")
    print("=" * 78)
    print()

    # Build comparison rows
    names = [p['attorney'] for p in profiles]
    col_w = max(20, max(len(n) for n in names) + 2)

    def row(label, values, fmt=None):
        parts = [f"  {label:<34}"]
        for v in values:
            if fmt and v is not None:
                parts.append(f"{fmt.format(v):>{col_w}}")
            elif v is None:
                parts.append(f"{'N/A':>{col_w}}")
            else:
                parts.append(f"{str(v):>{col_w}}")
        print("".join(parts))

    # Header
    header = f"  {'Metric':<34}"
    for n in names:
        header += f"{n:>{col_w}}"
    print(header)
    print(f"  {'-' * (34 + col_w * len(names))}")

    # Volume
    row("Total cases",
        [p['volume']['total_cases'] for p in profiles], "{:,}")
    row("Filing velocity (cases/yr)",
        [p['volume']['filing_velocity_per_year'] for p in profiles], "{:.1f}")
    row("Courts active",
        [p['volume']['court_count'] for p in profiles])

    ch13_totals = [p['outcomes']['ch13_total'] for p in profiles]
    row("Ch. 13 cases",
        ch13_totals, "{:,}")

    # Outcomes
    row("Dismissal rate (%)",
        [p['outcomes']['ch13_dismissed_pct'] for p in profiles], "{:.1f}")
    row("Discharge rate (%)",
        [p['outcomes']['ch13_discharged_pct'] for p in profiles], "{:.1f}")

    # Duration
    row("Median days to dismissal",
        [p['duration']['median_days_to_dismissal'] for p in profiles])
    row("Dismissed within 90d (%)",
        [p['duration']['dismissed_within_90d_pct'] for p in profiles], "{:.1f}")
    row("Dismissed within 180d (%)",
        [p['duration']['dismissed_within_180d_pct'] for p in profiles], "{:.1f}")

    # Statutory
    row("1328(f)(1) hits",
        [p['statutory']['f1_hits'] for p in profiles])
    row("1328(f)(2) hits",
        [p['statutory']['f2_hits'] for p in profiles])
    row("109(g) hits",
        [p['statutory']['g_109_hits'] for p in profiles])
    row("Ch.7->Ch.13 pipeline",
        [p['statutory']['ch7_to_ch13_pipeline'] for p in profiles])

    # Repeat debtors
    row("Serial filing rate (%)",
        [p['repeat_debtors']['serial_filing_rate_pct'] for p in profiles], "{:.1f}")
    row("Max cases, single debtor",
        [p['repeat_debtors']['max_cases_single_debtor'] for p in profiles])

    print()

    # Delta column if exactly 2
    if len(profiles) == 2:
        print(f"  Delta ({names[0]} vs {names[1]}):")
        p0, p1 = profiles[0], profiles[1]

        def delta(label, v0, v1, fmt="{:.1f}", suffix=""):
            if v0 is not None and v1 is not None:
                d = v0 - v1
                sign = "+" if d > 0 else ""
                print(f"    {label:<36} {sign}{fmt.format(d)}{suffix}")

        delta("Dismissal rate",
              p0['outcomes']['ch13_dismissed_pct'],
              p1['outcomes']['ch13_dismissed_pct'], suffix=" pp")
        delta("Dismissed within 90d",
              p0['duration']['dismissed_within_90d_pct'],
              p1['duration']['dismissed_within_90d_pct'], suffix=" pp")
        delta("1328(f) total hits",
              p0['statutory']['f1_hits'] + p0['statutory']['f2_hits'],
              p1['statutory']['f1_hits'] + p1['statutory']['f2_hits'], fmt="{:.0f}")
        delta("Serial filing rate",
              p0['repeat_debtors']['serial_filing_rate_pct'],
              p1['repeat_debtors']['serial_filing_rate_pct'], suffix=" pp")
        print()


def print_footer():
    """Print report footer with caveat."""
    print("-" * 78)
    print("  Generated from publicly available PACER data. A high dismissal rate may")
    print("  reflect case complexity, client population, or local practice norms.")
    print("  Compare against peer attorneys in the same district for meaningful")
    print("  benchmarks. All name matching is fuzzy and requires manual verification.")
    print("-" * 78)
    print()


def print_report(profile):
    """Print full report for one attorney."""
    print_header(profile['attorney'])
    print_volume(profile['volume'])
    print_outcomes(profile['outcomes'])
    print_duration(profile['duration'])
    print_statutory(profile['statutory'])
    print_repeat_debtors(profile['repeat_debtors'])
    print_footer()


# -- Output: One-Line -------------------------------------------------------

def format_oneline(profile):
    """Format a one-line summary for an attorney."""
    vol = profile['volume']
    out = profile['outcomes']
    stat = profile['statutory']

    f_total = stat['f1_hits'] + stat['f2_hits']
    ch13 = out['ch13_total']
    f_pct = f"{100 * f_total / ch13:.1f}%" if ch13 else "N/A"

    return (f"{profile['attorney']:<30} | "
            f"{ch13:>5} Ch.13 | "
            f"{out['ch13_dismissed_pct']:>5.1f}% dismissed | "
            f"{vol['filing_velocity_per_year']:>5.1f}/yr | "
            f"{f_total} 1328f hits ({f_pct})")


# -- Output: JSON ------------------------------------------------------------

def write_json_output(profiles, output_path):
    """Write structured JSON output."""
    result = {
        'metadata': {
            'tool': 'practice_report',
            'version': VERSION,
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        },
        'profiles': profiles,
    }
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, default=str)
    print(f"JSON output written to: {output_path}")


# -- Output: Markdown --------------------------------------------------------

def format_markdown_report(profile):
    """Format a full attorney report as Reddit-ready markdown."""
    vol = profile['volume']
    out = profile['outcomes']
    dur = profile['duration']
    stat = profile['statutory']
    rep = profile['repeat_debtors']

    f_total = stat['f1_hits'] + stat['f2_hits']
    ch13 = out['ch13_total']

    lines = []
    lines.append(f"## Attorney Practice Report: {profile['attorney']}")
    lines.append(f"*Generated {datetime.now().strftime('%Y-%m-%d')} by practice_report.py v{VERSION}*")
    lines.append("")

    # Volume
    lines.append("### Volume")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total cases | {vol['total_cases']:,} |")
    lines.append(f"| Date range | {vol['earliest_filing'] or 'N/A'} to {vol['latest_filing'] or 'N/A'} |")
    lines.append(f"| Filing velocity | {vol['filing_velocity_per_year']:.1f} cases/year |")
    lines.append(f"| Courts | {', '.join(vol['courts']) if vol['courts'] else 'N/A'} ({vol['court_count']}) |")
    lines.append("")

    if vol['by_chapter']:
        lines.append("**Chapter Mix:**")
        lines.append("")
        lines.append("| Chapter | Cases | Mix |")
        lines.append("|---------|-------|-----|")
        for ch, cnt in sorted(vol['by_chapter'].items()):
            pct = vol['chapter_mix'].get(ch, 0)
            lines.append(f"| Ch. {ch} | {cnt:,} | {pct:.1f}% |")
        lines.append("")

    # Outcomes
    if ch13 > 0:
        lines.append("### Outcomes (Ch. 13)")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Ch. 13 caseload | {ch13:,} |")
        lines.append(f"| Dismissed | {out['ch13_dismissed']:,} ({out['ch13_dismissed_pct']:.1f}%) |")
        lines.append(f"| Discharged | {out['ch13_discharged']:,} ({out['ch13_discharged_pct']:.1f}%) |")
        lines.append(f"| Pending | {out['ch13_pending']:,} ({out['ch13_pending_pct']:.1f}%) |")
        lines.append("")

    # Duration
    med_dismiss = dur['median_days_to_dismissal']
    med_discharge = dur['median_days_to_discharge']
    if dur['total_dismissed_with_dates'] or dur['total_discharged_with_dates']:
        lines.append("### Case Duration (Ch. 13)")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Median days to dismissal | {int(med_dismiss) if med_dismiss is not None else 'N/A'} (n={dur['total_dismissed_with_dates']}) |")
        lines.append(f"| Median days to discharge | {int(med_discharge) if med_discharge is not None else 'N/A'} (n={dur['total_discharged_with_dates']}) |")
        if dur['total_dismissed_with_dates']:
            lines.append(f"| Dismissed within 90 days | {dur['dismissed_within_90d']:,} ({dur['dismissed_within_90d_pct']:.1f}%) |")
            lines.append(f"| Dismissed within 180 days | {dur['dismissed_within_180d']:,} ({dur['dismissed_within_180d_pct']:.1f}%) |")
        lines.append("")

    # Statutory
    lines.append("### Statutory Compliance")
    lines.append("")
    lines.append(f"| Screen | Hits | Rate/1K |")
    lines.append(f"|--------|------|---------|")
    lines.append(f"| 1328(f)(1) (4-yr bar) | {stat['f1_hits']} | {stat['f1_rate_per_1k']:.1f} |")
    lines.append(f"| 1328(f)(2) (2-yr bar) | {stat['f2_hits']} | {stat['f2_rate_per_1k']:.1f} |")
    lines.append(f"| 109(g) rapid refile* | {stat['g_109_hits']} | {stat['g_109_rate_per_1k']:.1f} |")
    lines.append(f"| Ch.7 -> Ch.13 pipeline | {stat['ch7_to_ch13_pipeline']} | {stat['ch7_to_ch13_rate_per_1k']:.1f} |")
    lines.append("")
    lines.append("\\* 109(g) flags are potential only. The 180-day bar requires dismissal for willful noncompliance or voluntary dismissal after a stay relief motion. Most routine dismissals do not trigger 109(g). Ch.7->Ch.13 pipeline includes legitimate 'Chapter 20' strategies.")
    lines.append("")

    # Repeat debtors
    lines.append("### Debtor Patterns")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Unique debtors | {rep['total_unique_debtors']:,} |")
    lines.append(f"| Debtors with 2+ cases | {rep['debtors_with_2plus_cases']:,} |")
    lines.append(f"| Serial filing rate | {rep['serial_filing_rate_pct']:.1f}% |")
    lines.append(f"| Max cases, single debtor | {rep['max_cases_single_debtor']} |")
    lines.append("")

    lines.append("---")
    lines.append("*Generated from publicly available PACER data. Compare against peer attorneys in the same district for meaningful benchmarks.*")
    lines.append("")

    return "\n".join(lines)


def format_markdown_comparative(profiles):
    """Format a comparative table as markdown."""
    if len(profiles) < 2:
        return ""

    names = [p['attorney'] for p in profiles]
    lines = []
    lines.append("## Comparative Analysis")
    lines.append("")

    header = "| Metric |"
    sep = "|--------|"
    for n in names:
        header += f" {n} |"
        sep += "------|"
    lines.append(header)
    lines.append(sep)

    def mrow(label, values, fmt=None):
        row = f"| {label} |"
        for v in values:
            if v is None:
                row += " N/A |"
            elif fmt:
                row += f" {fmt.format(v)} |"
            else:
                row += f" {v} |"
        lines.append(row)

    mrow("Total cases", [p['volume']['total_cases'] for p in profiles], "{:,}")
    mrow("Filing velocity", [p['volume']['filing_velocity_per_year'] for p in profiles], "{:.1f}/yr")
    mrow("Ch. 13 cases", [p['outcomes']['ch13_total'] for p in profiles], "{:,}")
    mrow("Dismissal rate", [p['outcomes']['ch13_dismissed_pct'] for p in profiles], "{:.1f}%")
    mrow("Discharge rate", [p['outcomes']['ch13_discharged_pct'] for p in profiles], "{:.1f}%")
    mrow("Median days to dismissal", [p['duration']['median_days_to_dismissal'] for p in profiles])
    mrow("Dismissed within 90d", [p['duration']['dismissed_within_90d_pct'] for p in profiles], "{:.1f}%")
    mrow("1328(f)(1) hits", [p['statutory']['f1_hits'] for p in profiles])
    mrow("1328(f)(2) hits", [p['statutory']['f2_hits'] for p in profiles])
    mrow("109(g) hits", [p['statutory']['g_109_hits'] for p in profiles])
    mrow("Serial filing rate", [p['repeat_debtors']['serial_filing_rate_pct'] for p in profiles], "{:.1f}%")

    lines.append("")
    return "\n".join(lines)


def format_markdown_oneline(profile):
    """Format a one-line markdown table row for an attorney."""
    vol = profile['volume']
    out = profile['outcomes']
    stat = profile['statutory']
    f_total = stat['f1_hits'] + stat['f2_hits']
    ch13 = out['ch13_total']
    f_pct = f"{100 * f_total / ch13:.1f}%" if ch13 else "N/A"
    med = profile['duration']['median_days_to_dismissal']
    med_str = str(int(med)) if med is not None else "-"

    return (f"| {profile['attorney']} | {ch13:,} | "
            f"{out['ch13_dismissed_pct']:.1f}% | {med_str} | "
            f"{f_total} ({f_pct}) | "
            f"{stat['g_109_hits']} | {profile['repeat_debtors']['serial_filing_rate_pct']:.1f}% |")


def format_markdown_oneline_header():
    """Return the markdown table header for oneline rows."""
    return ("| Attorney | Ch.13 | Dismissed | Med Days | 1328(f) Hits | 109(g) | Serial Rate |\n"
            "|----------|-------|-----------|----------|--------------|--------|-------------|")


# -- Output: Leaderboard Submission -----------------------------------------

def format_leaderboard_submission(profiles, district_profiles, username=None):
    """Generate a paste-ready leaderboard submission block."""
    uname = username or "anonymous"
    lines = []
    lines.append("```")
    lines.append("=== LEADERBOARD SUBMISSION ===")
    lines.append(f"Screened by: @{uname}")
    lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"Tool version: practice_report v{VERSION}")
    lines.append("")

    if district_profiles:
        for dp in district_profiles:
            vol = dp['volume']
            out = dp['outcomes']
            stat = dp['statutory']
            f_total = stat['f1_hits'] + stat['f2_hits']
            ch13 = out['ch13_total']

            lines.append(f"District: {dp['district']}")
            lines.append(f"  Total cases loaded: {vol['total_cases']:,}")
            lines.append(f"  Ch.13 cases: {ch13:,}")
            lines.append(f"  Attorneys in dataset: {dp.get('attorney_count', '?')}")
            lines.append(f"  Dismissal rate: {out['ch13_dismissed_pct']:.1f}%")
            med = dp['duration']['median_days_to_dismissal']
            lines.append(f"  Median days to dismissal: {int(med) if med is not None else 'N/A'}")
            lines.append(f"  1328(f)(1) hits: {stat['f1_hits']}")
            lines.append(f"  1328(f)(2) hits: {stat['f2_hits']}")
            lines.append(f"  Total 1328(f) hits: {f_total}")
            lines.append(f"  Hit rate: {100 * f_total / ch13:.2f}%" if ch13 else "  Hit rate: N/A")
            lines.append("")

    if profiles:
        lines.append("--- TOP ATTORNEYS ---")
        # Sort by total 1328(f) hits descending
        ranked = sorted(profiles, key=lambda p: p['statutory']['f1_hits'] + p['statutory']['f2_hits'], reverse=True)
        for i, p in enumerate(ranked[:5], 1):
            stat = p['statutory']
            out = p['outcomes']
            f_total = stat['f1_hits'] + stat['f2_hits']
            ch13 = out['ch13_total']
            lines.append(f"  #{i}: {p['attorney']}")
            lines.append(f"      Ch.13: {ch13:,} | Dismissed: {out['ch13_dismissed_pct']:.1f}%")
            lines.append(f"      1328(f): {f_total} hits | 109(g): {stat['g_109_hits']}")
            lines.append(f"      Serial filing rate: {p['repeat_debtors']['serial_filing_rate_pct']:.1f}%")
            lines.append("")

    # Summary stats for leaderboard entry
    if profiles:
        total_cases = sum(p['volume']['total_cases'] for p in profiles)
        total_ch13 = sum(p['outcomes']['ch13_total'] for p in profiles)
        total_f = sum(p['statutory']['f1_hits'] + p['statutory']['f2_hits'] for p in profiles)
        max_dismiss = max((p['outcomes']['ch13_dismissed_pct'] for p in profiles
                          if p['outcomes']['ch13_total'] >= 50), default=0)
        lines.append("--- LEADERBOARD ENTRY ---")
        lines.append(f"  Cases screened: {total_cases:,}")
        lines.append(f"  Ch.13 screened: {total_ch13:,}")
        lines.append(f"  Total 1328(f) hits: {total_f}")
        lines.append(f"  Hit rate: {100 * total_f / total_ch13:.2f}%" if total_ch13 else "  Hit rate: N/A")
        lines.append(f"  Highest dismissal rate (50+ cases): {max_dismiss:.1f}%")
        lines.append(f"  Attorneys profiled: {len(profiles)}")

    lines.append("```")
    lines.append("")
    lines.append("*Copy this block and paste it in a GitHub issue or Reddit comment.*")

    return "\n".join(lines)


# -- CLI ---------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Generate attorney practice reports from PACER Case Locator CSV "
            "exports. Analyzes volume, outcomes, case duration, statutory "
            "compliance, and debtor patterns.\n\n"
            "This tool processes locally-downloaded CSV files. It does NOT "
            "access PACER servers or make any network calls."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --data-dir ./csvs --target Smith_John\n"
            "  %(prog)s --data-dir ./csvs --target Smith_John --control Jones_Bob\n"
            "  %(prog)s --data-dir ./csvs --target Smith_John --output-json report.json\n"
            "  %(prog)s --data-dir ./csvs --target Smith_John --oneline\n"
            "  %(prog)s --data-dir ./csvs --all\n"
            "  %(prog)s --data-dir ./csvs --all --markdown --oneline\n"
            "  %(prog)s --data-dir ./csvs --all --leaderboard --username myreddit\n"
            "  %(prog)s --data-dir ./csvs --by-district --leaderboard --username myreddit\n\n"
            "CSV files should follow the PACER Case Locator export naming convention:\n"
            "  api_{LastName_FirstName}_{court}_{timestamp}.csv\n\n"
            "For instructions on downloading CSVs from PACER Case Locator,\n"
            "see docs/pacer_csv_guide.md"
        ),
    )
    parser.add_argument(
        '--data-dir', required=True, type=Path,
        help='Directory containing PACER Case Locator CSV exports',
    )
    parser.add_argument(
        '--target', action='append', default=[], metavar='LastName_FirstName',
        help='Target attorney to profile (repeatable). Format: LastName_FirstName',
    )
    parser.add_argument(
        '--control', action='append', default=[], metavar='LastName_FirstName',
        help='Control/comparison attorney (repeatable). Format: LastName_FirstName',
    )
    parser.add_argument(
        '--courts', default=None,
        help='Comma-separated court IDs to include (default: all). E.g.: mowbk,ksbk',
    )
    parser.add_argument(
        '--output-json', default=None, type=Path, metavar='PATH',
        help='Write structured JSON output to this file',
    )
    parser.add_argument(
        '--oneline', action='store_true',
        help='Print one-line summary per attorney instead of full report',
    )
    parser.add_argument(
        '--all', action='store_true',
        help='Profile every attorney found in the data directory',
    )
    parser.add_argument(
        '--by-district', action='store_true',
        help='Aggregate by district (court) instead of by attorney',
    )
    parser.add_argument(
        '--markdown', action='store_true',
        help='Output in Reddit-ready markdown format instead of plain text',
    )
    parser.add_argument(
        '--leaderboard', action='store_true',
        help='Generate a paste-ready leaderboard submission block',
    )
    parser.add_argument(
        '--username', default=None, metavar='NAME',
        help='Reddit/GitHub username for leaderboard submission (default: anonymous)',
    )
    return parser


# -- Main --------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.target and not args.all and not args.by_district:
        parser.error("At least one --target attorney is required (or use --all / --by-district)")

    courts = None
    if args.courts:
        courts = set(c.strip().lower() for c in args.courts.split(','))

    # District mode
    if args.by_district:
        # Load everything
        all_found = discover_all_attorney_keys(args.data_dir, courts)
        if not all_found:
            print("ERROR: No attorney CSVs found in data directory.", file=sys.stderr)
            sys.exit(1)
        dummy_target = set()
        dummy_display = {}
        for k in all_found:
            d = make_display_name(k)
            dummy_target.add(d)
            dummy_display[k] = d

        cases, case_attorneys = load_all_cases(
            args.data_dir, set(all_found), dummy_display, dummy_target, courts
        )

        # Discover unique courts in the data
        court_ids = set()
        for c in cases:
            cid = c.get('courtId', '').strip().lower()
            if cid:
                court_ids.add(cid)

        district_profiles = []
        for cid in sorted(court_ids):
            dp = compute_district_profile(cases, cid)
            if dp:
                district_profiles.append(dp)

        if args.oneline:
            for dp in district_profiles:
                print(format_district_oneline(dp))
        else:
            for dp in district_profiles:
                print_district_report(dp)

        if args.leaderboard:
            # Also compute attorney profiles for the leaderboard block
            atty_profiles = []
            for k in all_found:
                d = dummy_display.get(k, make_display_name(k))
                p = compute_attorney_profile(cases, case_attorneys, d)
                if p:
                    atty_profiles.append(p)
            print(format_leaderboard_submission(atty_profiles, district_profiles, args.username))

        if args.output_json:
            write_json_output(district_profiles, args.output_json)

        return

    # Discover attorneys if --all
    if args.all:
        all_found = discover_all_attorney_keys(args.data_dir, courts)
        if not all_found:
            print("ERROR: No attorney CSVs found in data directory.", file=sys.stderr)
            sys.exit(1)
        args.target = all_found
        print(f"Discovered {len(all_found)} attorneys in {args.data_dir}")

    # Build attorney sets (controls are also profiled, just tagged)
    all_attorney_keys = list(set(args.target + args.control))
    target_canonical, control_canonical, all_keys, display_map = \
        build_attorney_sets(args.target, args.control)

    # For loading, we want all keys (no [CONTROL] suffix in file matching)
    file_keys = set(args.target + args.control)

    # Load data
    cases, case_attorneys = load_all_cases(
        args.data_dir, file_keys, display_map, target_canonical, courts
    )
    print()

    # Compute profiles
    profiles = []
    for key in args.target:
        display = display_map.get(key, make_display_name(key))
        profile = compute_attorney_profile(cases, case_attorneys, display)
        if profile:
            profiles.append(profile)
        else:
            print(f"  WARNING: No cases found for {display}", file=sys.stderr)

    control_profiles = []
    for key in args.control:
        display = display_map.get(key, make_display_name(key))
        profile = compute_attorney_profile(cases, case_attorneys, display)
        if profile:
            control_profiles.append(profile)
        else:
            print(f"  WARNING: No cases found for {display}", file=sys.stderr)

    # Output
    all_profiles = profiles + control_profiles

    if args.leaderboard:
        print(format_leaderboard_submission(all_profiles, [], args.username))
    elif args.markdown:
        if args.oneline:
            print(format_markdown_oneline_header())
            for p in all_profiles:
                print(format_markdown_oneline(p))
        else:
            for p in all_profiles:
                print(format_markdown_report(p))
            if profiles and control_profiles:
                print(format_markdown_comparative(profiles + control_profiles))
            elif len(profiles) > 1:
                print(format_markdown_comparative(profiles))
    elif args.oneline:
        for p in all_profiles:
            print(format_oneline(p))
    else:
        for p in profiles:
            print_report(p)
        for p in control_profiles:
            print_report(p)

        # Comparative table if we have target + control
        if profiles and control_profiles:
            print_comparative(profiles + control_profiles)
        elif len(profiles) > 1:
            print_comparative(profiles)

    # JSON output
    if args.output_json:
        write_json_output(all_profiles, args.output_json)


if __name__ == '__main__':
    main()
