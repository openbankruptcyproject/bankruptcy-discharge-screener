#!/usr/bin/env python3
r"""
Section 1328(f) Discharge Bar Violation Screener
=================================================
Screens PACER Case Locator CSV exports for cases where a Ch.13 was filed
despite a prior discharge that bars a new Ch.13 discharge under 11 U.S.C. 1328(f).

  1328(f)(1): Ch.7/11/12 case FILED within 4 YEARS before Ch.13 filing -> NO discharge
  1328(f)(2): Ch.13 case FILED within 2 YEARS before Ch.13 filing -> NO discharge

NOTE: The statutory period runs from the FILING DATE of the prior case to the
filing date (order for relief) of the current Ch.13, NOT from the discharge date.
See In re Blendheim, 803 F.3d 477 (9th Cir. 2015). The prior case must have
resulted in a discharge, but the gap is measured filing-to-filing.

Section 1328(f) was enacted by BAPCPA, effective October 17, 2005.
Only Ch.13 cases filed on or after that date are subject to this bar.

Data: PACER Case Locator CSV exports (https://pcl.uscourts.gov)
Dependencies: Python 3.8+ standard library only (no pip install needed)

Usage:
  python screen_1328f.py --data-dir ./csv-exports --target Smith_John --target Doe_Jane
  python screen_1328f.py --data-dir ./csv-exports --target Smith_John --control Jones_Bob
  python screen_1328f.py --data-dir ./csv-exports --target Smith_John --output-json results.json
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

# BAPCPA effective date -- 1328(f) only applies to Ch.13 cases filed on/after this
BAPCPA_EFFECTIVE = datetime(2005, 10, 17)

# 1328(f) statutory windows
WINDOW_F1_DAYS = 4 * 365 + 1   # 4 years (1461 days, +1 for leap year buffer)
WINDOW_F2_DAYS = 2 * 365 + 1   # 2 years (731 days)

# Name suffix patterns to strip during normalization
SUFFIXES = re.compile(
    r'\b(jr\.?|sr\.?|ii|iii|iv|v|vi|vii|viii|2nd|3rd|4th)\s*$',
    re.IGNORECASE
)


# -- Name Normalization ------------------------------------------------------

def normalize_name(name: str) -> str:
    """Normalize a debtor name for matching.

    Lowercases, strips suffixes (Jr., Sr., II, etc.), removes periods,
    strips 'NMN' (no middle name), collapses whitespace.
    """
    if not name:
        return ""
    n = name.lower().strip()
    n = n.replace(".", "")
    n = re.sub(r'\bnmn\b', '', n)
    n = SUFFIXES.sub('', n).strip()
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def extract_names(case_title: str) -> list:
    """Extract individual debtor names from a case title.

    Joint cases use ' and ' as separator (e.g., "John Smith and Jane Smith").
    Returns list of normalized name keys for matching.
    Generates both full-name and first+last keys to catch middle-name variations.
    """
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
    """Build canonical display-name sets from CLI attorney keys.

    Returns:
        target_canonical: set of display names for target attorneys
        control_canonical: set of display names for control attorneys
        all_keys: set of all attorney filename keys
        display_map: dict mapping filename key -> display name
    """
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
        display = make_display_name(key) + " [CONTROL]"
        control_canonical.add(display)
        display_map[key] = display
        all_keys.add(key)

    return target_canonical, control_canonical, all_keys, display_map


# -- CSV Loading -------------------------------------------------------------

def discover_csvs(data_dir: Path, attorney_keys: set, courts: set = None):
    """Discover PACER CSV files matching the expected filename pattern.

    Expected pattern: api_{LastName_FirstName}_{court}_{timestamp}.csv
    If attorney_keys is provided, only loads CSVs matching those keys.
    If courts is provided, only loads CSVs for those courts.

    Returns list of (csv_path, attorney_key, court) tuples.
    """
    all_csvs = sorted(glob.glob(str(data_dir / "api_*.csv")))
    # Pattern: api_{attorney_key}_{court}_{timestamp}.csv
    # Attorney keys contain underscores (e.g., Smith_John), so we match the
    # court code and timestamp from the RIGHT side and derive the attorney key.
    # Timestamp: YYYYMMDD or YYYYMMDD_HHMMSS (with optional trailing parts)
    pattern = re.compile(
        r'^api_(.+)_([a-z]+(?:bk|courts))_(\d{8}(?:_\d+)*)\.csv$',
        re.IGNORECASE
    )

    # Group by (attorney, court) and keep latest
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

    # Pick latest file per group (lexicographic = latest timestamp)
    result = []
    for (atty_key, court), files in sorted(groups.items()):
        result.append((files[-1], atty_key, court))

    return result


def load_all_cases(data_dir: Path, attorney_keys: set, display_map: dict,
                   target_canonical: set, courts: set = None):
    """Load all cases from PACER CSV exports, deduplicating by caseId.

    Returns:
        cases: list of dicts (one per unique case)
        case_attorneys: dict mapping caseId -> set of attorney display names
    """
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
                    # Prefer target attorney as primary
                    existing = seen_case_ids[case_id]
                    if display_name in target_canonical and existing['_attorney'] not in target_canonical:
                        existing['_attorney'] = display_name

    print(f"Loaded {len(seen_case_ids):,} unique cases from {file_count} CSV files "
          f"({row_count:,} total rows)")
    return list(seen_case_ids.values()), case_attorneys


# -- Debtor Grouping ---------------------------------------------------------

def group_by_debtor(cases: list) -> dict:
    """Group cases by normalized debtor name."""
    groups = defaultdict(list)
    for case in cases:
        title = case.get('caseTitle', '')
        name_keys = extract_names(title)
        for key in name_keys:
            groups[key].append(case)
    return groups


# -- Date Parsing ------------------------------------------------------------

def parse_date(date_str: str):
    """Parse YYYY-MM-DD date string. Returns datetime or None."""
    if not date_str or not date_str.strip():
        return None
    try:
        return datetime.strptime(date_str.strip(), '%Y-%m-%d')
    except ValueError:
        return None


# -- 1328(f) Screening -------------------------------------------------------

def screen_1328f(cases, case_attorneys, target_canonical, control_canonical):
    """Screen all cases for 1328(f) violations.

    Logic:
    - Group cases by debtor name (fuzzy matching on first+last)
    - For each debtor with 2+ cases, check if any Ch.13 filing occurred
      within the statutory window after a prior discharge
    - Only flag cases where the Ch.13 was filed by a target or control attorney
    - Deduplicate hits by (prior_case_id, ch13_case_id, section)

    Returns:
        f1_hits: list of dicts for 1328(f)(1) violations (4-year bar)
        f2_hits: list of dicts for 1328(f)(2) violations (2-year bar)
    """
    debtor_groups = group_by_debtor(cases)
    repeat_groups = {k: v for k, v in debtor_groups.items() if len(v) >= 2}
    print(f"Found {len(repeat_groups):,} debtor name keys with 2+ cases")

    f1_seen = set()
    f2_seen = set()
    f1_hits = []
    f2_hits = []
    pre_bapcpa_skipped = 0

    for name_key, group_cases in repeat_groups.items():
        # Deduplicate within group
        unique_cases = {}
        for c in group_cases:
            cid = c.get('caseId', '')
            if cid not in unique_cases:
                unique_cases[cid] = c
        cases_list = list(unique_cases.values())

        if len(cases_list) < 2:
            continue

        discharged_cases = [c for c in cases_list if parse_date(c.get('dateDischarged', ''))]
        ch13_filings = [c for c in cases_list
                        if c.get('bankruptcyChapter', '').strip() == '13']

        if not discharged_cases or not ch13_filings:
            continue

        for ch13 in ch13_filings:
            ch13_filed = parse_date(ch13.get('dateFiled', ''))
            if not ch13_filed:
                continue

            # BAPCPA filter
            if ch13_filed < BAPCPA_EFFECTIVE:
                pre_bapcpa_skipped += 1
                continue

            ch13_case_num = ch13.get('caseNumberFull', '')
            ch13_case_id = ch13.get('caseId', '')
            ch13_court = ch13.get('courtId', '')

            ch13_attys = case_attorneys.get(ch13_case_id, set())
            target_attys = ch13_attys & target_canonical
            ctrl_attys = ch13_attys & control_canonical

            # Only flag if filed by a target or control attorney
            if not target_attys and not ctrl_attys:
                continue

            is_control = bool(ctrl_attys) and not bool(target_attys)

            for prior in discharged_cases:
                prior_case_id = prior.get('caseId', '')
                if prior_case_id == ch13_case_id:
                    continue

                # Prior case must have resulted in a discharge (prerequisite)
                prior_discharge = parse_date(prior.get('dateDischarged', ''))
                if not prior_discharge:
                    continue

                # Gap measured from prior FILING date, not discharge date
                # See In re Blendheim, 803 F.3d 477 (9th Cir. 2015)
                prior_filed = parse_date(prior.get('dateFiled', ''))
                if not prior_filed:
                    continue

                if prior_filed >= ch13_filed:
                    continue

                gap_days = (ch13_filed - prior_filed).days
                prior_ch = prior.get('bankruptcyChapter', '').strip()
                prior_case_num = prior.get('caseNumberFull', '')
                prior_court = prior.get('courtId', '')
                prior_attys = case_attorneys.get(prior_case_id, set())

                hit_key_f1 = (prior_case_id, ch13_case_id, 'f1')
                hit_key_f2 = (prior_case_id, ch13_case_id, 'f2')

                hit_base = {
                    'debtor': ch13.get('caseTitle', ''),
                    'name_key': name_key,
                    'prior_case': prior_case_num,
                    'prior_court': prior_court,
                    'prior_chapter': prior_ch,
                    'prior_filed': prior_filed.strftime('%Y-%m-%d'),
                    'prior_discharge': prior_discharge.strftime('%Y-%m-%d'),
                    'prior_attorneys': sorted(prior_attys),
                    'ch13_case': ch13_case_num,
                    'ch13_court': ch13_court,
                    'ch13_filed': ch13_filed.strftime('%Y-%m-%d'),
                    'ch13_target_attys': sorted(target_attys),
                    'ch13_ctrl_attys': sorted(ctrl_attys),
                    'ch13_all_attys': sorted(target_attys | ctrl_attys),
                    'gap_days': gap_days,
                    'gap_years': round(gap_days / 365.25, 2),
                    'is_control': is_control,
                    'ch13_dismissed': ch13.get('dateDismissed', ''),
                    'ch13_discharged': ch13.get('dateDischarged', ''),
                    'ch13_disposition': ch13.get('disposition', ''),
                }

                if prior_ch in ('7', '11', '12') and gap_days <= WINDOW_F1_DAYS:
                    if hit_key_f1 not in f1_seen:
                        f1_seen.add(hit_key_f1)
                        f1_hits.append(dict(hit_base, section='f1'))

                if prior_ch == '13' and gap_days <= WINDOW_F2_DAYS:
                    if hit_key_f2 not in f2_seen:
                        f2_seen.add(hit_key_f2)
                        f2_hits.append(dict(hit_base, section='f2'))

    print(f"Skipped {pre_bapcpa_skipped} pre-BAPCPA Ch.13 filings (before 10/17/2005)")
    return f1_hits, f2_hits


# -- Output Formatting -------------------------------------------------------

def fmt_attys(atty_list):
    """Format attorney list for display."""
    if isinstance(atty_list, (set, frozenset)):
        return ' | '.join(sorted(atty_list))
    return ' | '.join(atty_list)


def print_hits(hits, section_label, section_desc):
    """Print violation hits in a formatted table."""
    if not hits:
        print(f"\n{'='*80}")
        print(f"  {section_label}: {section_desc}")
        print(f"{'='*80}")
        print("  No violations found.\n")
        return

    hits.sort(key=lambda h: (h['is_control'], h['gap_days'], h['debtor']))

    target_hits = [h for h in hits if not h['is_control']]
    ctrl_hits = [h for h in hits if h['is_control']]

    print(f"\n{'='*80}")
    print(f"  {section_label}: {section_desc}")
    print(f"  Total: {len(hits)} ({len(target_hits)} Target + {len(ctrl_hits)} Control)")
    print(f"{'='*80}\n")

    for i, h in enumerate(hits, 1):
        ctrl_tag = " [CONTROL]" if h['is_control'] else ""
        print(f"  [{i}]{ctrl_tag} {h['debtor']}")
        print(f"      Prior:  {h['prior_case']} ({h['prior_court'].upper()}) Ch.{h['prior_chapter']}"
              f"  filed {h.get('prior_filed', 'N/A')}  discharged {h['prior_discharge']}")
        print(f"              Attorney(s): {fmt_attys(h['prior_attorneys'])}")
        print(f"      NEW 13: {h['ch13_case']} ({h['ch13_court'].upper()}) Ch.13"
              f"  filed {h['ch13_filed']}")
        print(f"              Attorney(s): {fmt_attys(h['ch13_all_attys'])}")
        print(f"      Gap:    {h['gap_days']} days ({h['gap_years']} years)")

        outcome_parts = []
        if h['ch13_dismissed']:
            outcome_parts.append(f"DISMISSED {h['ch13_dismissed']}")
        if h['ch13_discharged']:
            outcome_parts.append(f"DISCHARGED {h['ch13_discharged']}")
        if h['ch13_disposition']:
            outcome_parts.append(h['ch13_disposition'])
        if not outcome_parts:
            outcome_parts.append("PENDING/OPEN")
        print(f"      Status: {' | '.join(outcome_parts)}")
        print()


def print_summary(f1_hits, f2_hits, target_canonical, control_canonical):
    """Print summary counts by attorney."""
    by_attorney = defaultdict(lambda: {'f1': 0, 'f2': 0, 'total': 0})

    for h in f1_hits:
        for atty in h['ch13_all_attys']:
            by_attorney[atty]['f1'] += 1
            by_attorney[atty]['total'] += 1

    for h in f2_hits:
        for atty in h['ch13_all_attys']:
            by_attorney[atty]['f2'] += 1
            by_attorney[atty]['total'] += 1

    print(f"\n{'='*80}")
    print(f"  SUMMARY: 1328(f) Violations by Attorney (Ch.13 filed on/after BAPCPA 10/17/2005)")
    print(f"{'='*80}\n")

    # Target attorneys
    target_attys = {k: v for k, v in by_attorney.items() if k in target_canonical}
    ctrl_attys = {k: v for k, v in by_attorney.items() if k in control_canonical}

    if target_attys:
        target_total_f1 = sum(v['f1'] for v in target_attys.values())
        target_total_f2 = sum(v['f2'] for v in target_attys.values())

        print(f"  Target Attorneys:")
        print(f"  {'Attorney':<30} {'f(1)':<8} {'f(2)':<8} {'Total':<8}")
        print(f"  {'-'*54}")
        for atty in sorted(target_attys.keys(), key=lambda k: -target_attys[k]['total']):
            v = target_attys[atty]
            print(f"  {atty:<30} {v['f1']:<8} {v['f2']:<8} {v['total']:<8}")
        print(f"  {'-'*54}")
        print(f"  {'Target TOTAL':<30} {target_total_f1:<8} {target_total_f2:<8} "
              f"{target_total_f1 + target_total_f2:<8}")

    if ctrl_attys:
        ctrl_total_f1 = sum(v['f1'] for v in ctrl_attys.values())
        ctrl_total_f2 = sum(v['f2'] for v in ctrl_attys.values())
        print(f"\n  Control Attorneys:")
        print(f"  {'Attorney':<30} {'f(1)':<8} {'f(2)':<8} {'Total':<8}")
        print(f"  {'-'*54}")
        for atty in sorted(ctrl_attys.keys(), key=lambda k: -ctrl_attys[k]['total']):
            v = ctrl_attys[atty]
            print(f"  {atty:<30} {v['f1']:<8} {v['f2']:<8} {v['total']:<8}")
        print(f"  {'-'*54}")
        print(f"  {'Control TOTAL':<30} {ctrl_total_f1:<8} {ctrl_total_f2:<8} "
              f"{ctrl_total_f1 + ctrl_total_f2:<8}")

    # Unique Ch.13 cases
    target_f1 = [h for h in f1_hits if not h['is_control']]
    target_f2 = [h for h in f2_hits if not h['is_control']]
    unique_ch13 = set(h['ch13_case'] for h in target_f1 + target_f2)
    print(f"\n  Unique Target Ch.13 cases with 1328(f) bar: {len(unique_ch13)}")

    unique_pairs = set((h['prior_case'], h['ch13_case']) for h in target_f1 + target_f2)
    print(f"  Unique prior-discharge -> Ch.13 violation pairs: {len(unique_pairs)}")

    discharged_despite = [h for h in target_f1 + target_f2 if h['ch13_discharged']]
    unique_discharged = set(h['ch13_case'] for h in discharged_despite)
    print(f"  Ch.13 cases that received discharge DESPITE bar: {len(unique_discharged)}")
    if unique_discharged:
        print(f"    (May be legitimate if court granted waiver or dates are imprecise)")
    print()


def print_cross_attorney_detail(f1_hits, f2_hits):
    """Print cases where prior discharge attorney differs from Ch.13 filer."""
    print(f"\n{'='*80}")
    print(f"  CROSS-ATTORNEY DETAIL: Prior case by different attorney than Ch.13 filer")
    print(f"{'='*80}\n")

    cross = []
    for h in f1_hits + f2_hits:
        if set(h['prior_attorneys']) != set(h['ch13_all_attys']) and not h['is_control']:
            cross.append(h)

    if not cross:
        print("  None found.\n")
        return

    seen = set()
    count = 0
    for h in sorted(cross, key=lambda x: x['gap_days']):
        key = (h['prior_case'], h['ch13_case'])
        if key in seen:
            continue
        seen.add(key)
        count += 1

    print(f"  Found {count} cross-attorney violation pairs:\n")

    seen2 = set()
    for i, h in enumerate(sorted(cross, key=lambda x: x['gap_days']), 1):
        key = (h['prior_case'], h['ch13_case'])
        if key in seen2:
            continue
        seen2.add(key)
        print(f"  [{i}] {h['debtor']}")
        print(f"      Prior: {h['prior_case']} Ch.{h['prior_chapter']} by "
              f"{fmt_attys(h['prior_attorneys'])}")
        print(f"      Ch.13: {h['ch13_case']} by {fmt_attys(h['ch13_all_attys'])} "
              f"({h['gap_days']}d / {h['gap_years']}yr gap)")
        print()


def print_most_egregious(f1_hits, f2_hits):
    """Print shortest-gap and non-dismissed barred cases."""
    target_hits = [h for h in f1_hits + f2_hits if not h['is_control']]

    print(f"\n{'='*80}")
    print(f"  MOST EGREGIOUS: Short gaps and non-dismissed barred Ch.13 cases")
    print(f"{'='*80}\n")

    # Cases not dismissed
    not_dismissed = [h for h in target_hits if not h['ch13_dismissed']]
    seen_cases = set()
    unique_not_dismissed = []
    for h in sorted(not_dismissed, key=lambda x: x['gap_days']):
        if h['ch13_case'] not in seen_cases:
            seen_cases.add(h['ch13_case'])
            unique_not_dismissed.append(h)

    if unique_not_dismissed:
        print(f"  Barred Ch.13 cases NOT DISMISSED ({len(unique_not_dismissed)}):")
        for h in unique_not_dismissed:
            note = (f" ** DISCHARGED {h['ch13_discharged']} **"
                    if h['ch13_discharged'] else " [OPEN/PENDING]")
            print(f"    {h['debtor']}: {h['ch13_case']} (gap: {h['gap_days']}d){note}")
        print()

    # Shortest f(1) gaps
    short_f1 = [h for h in f1_hits if not h['is_control'] and h['gap_days'] < 730]
    if short_f1:
        print(f"  f(1) hits with gap < 2 years ({len(short_f1)}):")
        for h in sorted(short_f1, key=lambda x: x['gap_days']):
            print(f"    {h['debtor']}: {h['gap_days']}d ({h['gap_years']}yr) "
                  f"Ch.{h['prior_chapter']} discharge -> Ch.13 "
                  f"[{fmt_attys(h['ch13_target_attys'])}]")
        print()

    # Shortest f(2) gaps
    short_f2 = [h for h in f2_hits if not h['is_control'] and h['gap_days'] < 365]
    if short_f2:
        print(f"  f(2) hits with gap < 1 year ({len(short_f2)}):")
        for h in sorted(short_f2, key=lambda x: x['gap_days']):
            print(f"    {h['debtor']}: {h['gap_days']}d ({h['gap_years']}yr) "
                  f"Ch.13 discharge -> Ch.13 "
                  f"[{fmt_attys(h['ch13_target_attys'])}]")
        print()


def print_methodological_notes():
    """Print caveats about the screening methodology."""
    print(f"\n{'='*80}")
    print(f"  METHODOLOGICAL NOTES / CAVEATS")
    print(f"{'='*80}\n")
    print("  1. Name matching is fuzzy (first+last). Some hits may be different people")
    print("     with the same name. Manual verification required for each hit.")
    print("  2. Pre-BAPCPA cases (Ch.13 filed before 10/17/2005) are EXCLUDED.")
    print("     Section 1328(f) did not exist before BAPCPA.")
    print("  3. Some 'DISCHARGED' Ch.13 cases may reflect legitimate situations:")
    print("     - Court may have determined dates did not overlap")
    print("     - Hardship discharge under 1328(b) may not be affected")
    print("     - Data entry lag in PACER")
    print("  4. 'OPEN/PENDING' status means the case has not yet reached discharge.")
    print("     The bar prevents discharge, not filing.")
    print("  5. The prior discharge NEED NOT be by a target attorney. The violation")
    print("     is filing a Ch.13 that cannot result in discharge.")
    print("  6. The statutory gap is measured from the FILING DATE of the prior case")
    print("     to the filing date of the current Ch.13 (order for relief date).")
    print("     See In re Blendheim, 803 F.3d 477 (9th Cir. 2015).")
    print("     The prior case must have resulted in a discharge, but the time")
    print("     window is anchored to filing dates, not discharge dates.")
    print("  7. Attorney competence issue: an attorney should check 1328(f) before")
    print("     filing. Filing a case that is discharge-barred wastes the debtor's")
    print("     filing fee, attorney fees, and time, while providing no benefit.")
    print("  7. Joint cases are split on ' and ' -- each spouse matched independently.")
    print("  8. Encoding: utf-8-sig used for CSV reading (handles BOM from PACER).")
    print()


def write_json_output(f1_hits, f2_hits, output_path):
    """Write structured JSON output."""
    def clean_hit(h):
        """Convert hit dict to JSON-serializable form."""
        return {k: v for k, v in h.items()
                if not isinstance(v, (set, frozenset))}

    result = {
        'metadata': {
            'tool': 'screen_1328f',
            'version': '1.0.0',
            'bapcpa_effective': '2005-10-17',
            'f1_window_days': WINDOW_F1_DAYS,
            'f2_window_days': WINDOW_F2_DAYS,
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        },
        'f1_violations': [clean_hit(h) for h in f1_hits],
        'f2_violations': [clean_hit(h) for h in f2_hits],
        'summary': {
            'total_f1': len(f1_hits),
            'total_f2': len(f2_hits),
            'total': len(f1_hits) + len(f2_hits),
            'target_f1': len([h for h in f1_hits if not h['is_control']]),
            'target_f2': len([h for h in f2_hits if not h['is_control']]),
            'control_f1': len([h for h in f1_hits if h['is_control']]),
            'control_f2': len([h for h in f2_hits if h['is_control']]),
            'unique_ch13_cases': len(set(
                h['ch13_case'] for h in f1_hits + f2_hits if not h['is_control']
            )),
            'discharged_despite_bar': len(set(
                h['ch13_case'] for h in f1_hits + f2_hits
                if not h['is_control'] and h['ch13_discharged']
            )),
        },
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, default=str)
    print(f"JSON output written to: {output_path}")


# -- CLI ---------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Screen PACER Case Locator CSV exports for Section 1328(f) "
            "discharge bar violations.\n\n"
            "Section 1328(f) bars discharge in a Ch.13 case if the debtor "
            "received a prior discharge in a case filed within statutory time limits:\n"
            "  f(1): prior Ch.7/11/12 case FILED within 4 years before current Ch.13\n"
            "  f(2): prior Ch.13 case FILED within 2 years before current Ch.13\n\n"
            "This tool processes locally-downloaded CSV files from the PACER "
            "Case Locator (https://pcl.uscourts.gov). It does NOT access "
            "PACER servers or make any network calls."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --data-dir ./csvs --target Smith_John\n"
            "  %(prog)s --data-dir ./csvs --target Smith_John --target Doe_Jane\n"
            "  %(prog)s --data-dir ./csvs --target Smith_John --control Jones_Bob\n"
            "  %(prog)s --data-dir ./csvs --target Smith_John --output-json out.json\n\n"
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
        help='Target attorney to screen (repeatable). Format: LastName_FirstName',
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
        '--all-csvs', action='store_true',
        help='Load ALL CSVs in data-dir (ignore --target/--control for file discovery)',
    )
    return parser


# -- Main --------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.target and not args.all_csvs:
        parser.error("At least one --target attorney is required (or use --all-csvs)")

    courts = None
    if args.courts:
        courts = set(c.strip().lower() for c in args.courts.split(','))

    # Build attorney sets
    target_canonical, control_canonical, all_keys, display_map = \
        build_attorney_sets(args.target, args.control)

    # If --all-csvs, discover keys from filenames
    file_filter_keys = None if args.all_csvs else all_keys

    print("=" * 80)
    print("  11 U.S.C. 1328(f) DISCHARGE BAR VIOLATION SCREEN")
    print("  BAPCPA filter: Only Ch.13 cases filed on/after 10/17/2005")
    print("=" * 80)
    print()
    if target_canonical:
        print(f"  Target attorneys: {', '.join(sorted(target_canonical))}")
    if control_canonical:
        print(f"  Control attorneys: {', '.join(sorted(control_canonical))}")
    print(f"  Data directory: {args.data_dir}")
    if courts:
        print(f"  Courts filter: {', '.join(sorted(courts))}")
    print()

    # Load data
    cases, case_attorneys = load_all_cases(
        args.data_dir, file_filter_keys, display_map, target_canonical, courts
    )

    ch13_count = sum(1 for c in cases if c.get('bankruptcyChapter', '').strip() == '13')
    print(f"Ch.13 cases in dataset: {ch13_count:,}")

    debtor_groups = group_by_debtor(cases)
    repeat_count = sum(1 for v in debtor_groups.values() if len(v) >= 2)
    print(f"Debtor name keys with 2+ cases: {repeat_count:,}")
    print()

    # Run screen
    f1_hits, f2_hits = screen_1328f(cases, case_attorneys,
                                     target_canonical, control_canonical)

    # Print results
    print_hits(
        [h for h in f1_hits if not h['is_control']],
        "Section 1328(f)(1)",
        "Ch.7/11/12 discharge within 4 YEARS before Ch.13 filing [TARGET]"
    )
    print_hits(
        [h for h in f2_hits if not h['is_control']],
        "Section 1328(f)(2)",
        "Ch.13 discharge within 2 YEARS before Ch.13 filing [TARGET]"
    )
    print_hits(
        [h for h in f1_hits if h['is_control']],
        "Section 1328(f)(1) -- CONTROL",
        "Ch.7/11/12 discharge within 4 YEARS before Ch.13 filing [CONTROL]"
    )
    print_hits(
        [h for h in f2_hits if h['is_control']],
        "Section 1328(f)(2) -- CONTROL",
        "Ch.13 discharge within 2 YEARS before Ch.13 filing [CONTROL]"
    )

    # Detail sections
    print_cross_attorney_detail(f1_hits, f2_hits)
    print_most_egregious(f1_hits, f2_hits)

    # Summary
    print_summary(f1_hits, f2_hits, target_canonical, control_canonical)

    # Caveats
    print_methodological_notes()

    # JSON output
    if args.output_json:
        write_json_output(f1_hits, f2_hits, args.output_json)


if __name__ == '__main__':
    main()
