#!/usr/bin/env python3
r"""
Discharge Bar Scanner -- Three Analyses on PACER CSV Data
=========================================================
1. Section 1328(f) refinements (same-firm vs cross-firm, time-gap histogram,
   strict name matching for "discharged despite bar" cases)
2. Section 109(g) filing bar screen (dismiss-refile within 180 days)
3. Ch.7 -> Ch.13 same-attorney conversion timing ("pipeline" behavior)

Data: PACER Case Locator CSV exports (https://pcl.uscourts.gov)
Dependencies: Python 3.8+ standard library only (no pip install needed)

Usage:
  python screen_discharge_bars.py --data-dir ./csv-exports --target Smith_John
  python screen_discharge_bars.py --data-dir ./csv-exports --target Smith_John --control Jones_Bob
"""

import csv
import re
import os
import sys
import glob
import json
import argparse
import statistics
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# -- Constants ---------------------------------------------------------------

BAPCPA_EFFECTIVE = datetime(2005, 10, 17)
WINDOW_F1_DAYS = 4 * 365 + 1
WINDOW_F2_DAYS = 2 * 365 + 1
WINDOW_109G_DAYS = 180

SUFFIXES = re.compile(
    r'\b(jr\.?|sr\.?|ii|iii|iv|v|vi|vii|viii|2nd|3rd|4th)\s*$',
    re.IGNORECASE
)


# -- Name Normalization ------------------------------------------------------

def normalize_name(name: str) -> str:
    if not name:
        return ""
    n = name.lower().strip().replace(".", "")
    n = re.sub(r'\bnmn\b', '', n)
    n = SUFFIXES.sub('', n).strip()
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def extract_names(case_title: str) -> list:
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


def extract_first_last_strict(case_title: str) -> list:
    """Extract strict (first, last) tuples for exact matching."""
    if not case_title:
        return []
    parts = re.split(r'\s+and\s+', case_title, flags=re.IGNORECASE)
    pairs = []
    for part in parts:
        norm = normalize_name(part)
        if norm:
            tokens = norm.split()
            if len(tokens) >= 2:
                pairs.append((tokens[0], tokens[-1]))
    return pairs


# -- Attorney Key Handling ---------------------------------------------------

def make_display_name(atty_key: str) -> str:
    parts = atty_key.split("_", 1)
    if len(parts) == 2:
        return f"{parts[0]}, {parts[1]}"
    return atty_key


def build_attorney_sets(target_keys, control_keys):
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


def load_all_cases(data_dir, attorney_keys, display_map, target_canonical, courts=None):
    csv_files = discover_csvs(data_dir, attorney_keys, courts)
    if not csv_files:
        print("ERROR: No matching CSV files found.", file=sys.stderr)
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


# -- Utility -----------------------------------------------------------------

def parse_date(date_str: str):
    if not date_str or not date_str.strip():
        return None
    try:
        return datetime.strptime(date_str.strip(), '%Y-%m-%d')
    except ValueError:
        return None


def fmt_attys(atty_set):
    if isinstance(atty_set, (set, frozenset)):
        return ' | '.join(sorted(atty_set))
    if isinstance(atty_set, list):
        return ' | '.join(atty_set)
    return str(atty_set)


def group_by_debtor(cases):
    groups = defaultdict(list)
    for case in cases:
        title = case.get('caseTitle', '')
        for key in extract_names(title):
            groups[key].append(case)
    return groups


# -- ANALYSIS 1: Section 1328(f) Refinements --------------------------------

def screen_1328f(cases, case_attorneys, target_canonical, control_canonical):
    """Core 1328(f) screen. Returns (f1_hits, f2_hits)."""
    debtor_groups = group_by_debtor(cases)
    repeat_groups = {k: v for k, v in debtor_groups.items() if len(v) >= 2}

    f1_seen, f2_seen = set(), set()
    f1_hits, f2_hits = [], []
    pre_bapcpa_skipped = 0

    for name_key, group_cases in repeat_groups.items():
        unique_cases = {}
        for c in group_cases:
            cid = c.get('caseId', '')
            if cid not in unique_cases:
                unique_cases[cid] = c
        cases_list = list(unique_cases.values())
        if len(cases_list) < 2:
            continue

        discharged_cases = [c for c in cases_list if parse_date(c.get('dateDischarged', ''))]
        ch13_filings = [c for c in cases_list if c.get('bankruptcyChapter', '').strip() == '13']
        if not discharged_cases or not ch13_filings:
            continue

        for ch13 in ch13_filings:
            ch13_filed = parse_date(ch13.get('dateFiled', ''))
            if not ch13_filed:
                continue
            if ch13_filed < BAPCPA_EFFECTIVE:
                pre_bapcpa_skipped += 1
                continue

            ch13_case_id = ch13.get('caseId', '')
            ch13_attys = case_attorneys.get(ch13_case_id, set())
            target_attys = ch13_attys & target_canonical
            ctrl_attys = ch13_attys & control_canonical
            if not target_attys and not ctrl_attys:
                continue
            is_control = bool(ctrl_attys) and not bool(target_attys)

            for prior in discharged_cases:
                prior_case_id = prior.get('caseId', '')
                if prior_case_id == ch13_case_id:
                    continue
                prior_discharge = parse_date(prior.get('dateDischarged', ''))
                if not prior_discharge or prior_discharge >= ch13_filed:
                    continue

                gap_days = (ch13_filed - prior_discharge).days
                prior_ch = prior.get('bankruptcyChapter', '').strip()
                prior_attys = case_attorneys.get(prior_case_id, set())

                # Determine same-firm: was prior also by a target attorney?
                prior_is_target = any(a in target_canonical for a in prior_attys)

                hit_base = {
                    'debtor': ch13.get('caseTitle', ''),
                    'name_key': name_key,
                    'prior_case': prior.get('caseNumberFull', ''),
                    'prior_court': prior.get('courtId', ''),
                    'prior_chapter': prior_ch,
                    'prior_discharge': prior_discharge.strftime('%Y-%m-%d'),
                    'prior_attorneys_set': frozenset(prior_attys),
                    'prior_is_target': prior_is_target,
                    'ch13_case': ch13.get('caseNumberFull', ''),
                    'ch13_court': ch13.get('courtId', ''),
                    'ch13_filed': ch13_filed.strftime('%Y-%m-%d'),
                    'ch13_target_attys': frozenset(target_attys),
                    'ch13_ctrl_attys': frozenset(ctrl_attys),
                    'ch13_all_attys': frozenset(target_attys | ctrl_attys),
                    'gap_days': gap_days,
                    'gap_years': round(gap_days / 365.25, 2),
                    'is_control': is_control,
                    'ch13_dismissed': ch13.get('dateDismissed', ''),
                    'ch13_discharged': ch13.get('dateDischarged', ''),
                    'ch13_disposition': ch13.get('disposition', ''),
                    'prior_case_title': prior.get('caseTitle', ''),
                    'ch13_case_title': ch13.get('caseTitle', ''),
                }

                hit_key_f1 = (prior_case_id, ch13_case_id, 'f1')
                hit_key_f2 = (prior_case_id, ch13_case_id, 'f2')

                if prior_ch in ('7', '11', '12') and gap_days <= WINDOW_F1_DAYS:
                    if hit_key_f1 not in f1_seen:
                        f1_seen.add(hit_key_f1)
                        f1_hits.append(dict(hit_base, section='f1'))

                if prior_ch == '13' and gap_days <= WINDOW_F2_DAYS:
                    if hit_key_f2 not in f2_seen:
                        f2_seen.add(hit_key_f2)
                        f2_hits.append(dict(hit_base, section='f2'))

    print(f"  Skipped {pre_bapcpa_skipped} pre-BAPCPA Ch.13 filings")
    return f1_hits, f2_hits


def analysis_1a_same_vs_cross(f1_hits, f2_hits, target_canonical, control_canonical):
    """Same-firm vs cross-firm classification."""
    print()
    print("=" * 80)
    print("  ANALYSIS 1a: Same-Firm vs Cross-Firm Classification")
    print("  (Was the PRIOR discharge case also handled by a target attorney?)")
    print("=" * 80)
    print()

    all_hits = f1_hits + f2_hits
    target_hits = [h for h in all_hits if not h['is_control']]
    ctrl_hits = [h for h in all_hits if h['is_control']]

    same_firm = [h for h in target_hits if h['prior_is_target']]
    cross_firm = [h for h in target_hits if not h['prior_is_target']]

    print(f"  Target 1328(f) hits: {len(target_hits)} total")
    print(f"    Same-firm (prior also target):  {len(same_firm)}")
    print(f"    Cross-firm (prior = other atty): {len(cross_firm)}")
    print()

    # Per-attorney breakdown
    atty_stats = defaultdict(lambda: {'same': 0, 'cross': 0})
    for h in target_hits:
        for atty in h['ch13_target_attys']:
            if h['prior_is_target']:
                atty_stats[atty]['same'] += 1
            else:
                atty_stats[atty]['cross'] += 1

    print(f"  Per-attorney (Target):")
    print(f"  {'Attorney':<28} {'Same-Firm':<12} {'Cross-Firm':<12} {'Total':<8}")
    print(f"  {'-'*60}")
    for atty in sorted(atty_stats.keys(), key=lambda k: -(atty_stats[k]['same'] + atty_stats[k]['cross'])):
        s = atty_stats[atty]
        print(f"  {atty:<28} {s['same']:<12} {s['cross']:<12} {s['same']+s['cross']:<8}")
    total_same = sum(v['same'] for v in atty_stats.values())
    total_cross = sum(v['cross'] for v in atty_stats.values())
    print(f"  {'-'*60}")
    print(f"  {'Target TOTAL':<28} {total_same:<12} {total_cross:<12} {total_same + total_cross:<8}")
    print()

    # Same-firm detail listing
    if same_firm:
        print(f"  Same-firm cases are the most culpable: the filing attorney's own firm")
        print(f"  handled the prior discharge and should have known about the bar.")
        print()
        seen = set()
        count = 0
        for h in sorted(same_firm, key=lambda x: x['gap_days']):
            key = (h['prior_case'], h['ch13_case'])
            if key in seen:
                continue
            seen.add(key)
            count += 1
            section = h['section'].replace('f', 'f(') + ')'
            print(f"    [{count}] {h['debtor']}")
            print(f"        Prior: {h['prior_case']} Ch.{h['prior_chapter']} discharged "
                  f"{h['prior_discharge']} by {fmt_attys(h['prior_attorneys_set'])}")
            print(f"        Ch.13: {h['ch13_case']} filed {h['ch13_filed']} "
                  f"by {fmt_attys(h['ch13_target_attys'])} [{section}] gap={h['gap_days']}d")
            print()

    if ctrl_hits:
        print(f"  Control attorney 1328(f) hits: {len(ctrl_hits)} total")
        print()


def analysis_1b_histogram(f1_hits, f2_hits):
    """Time-gap distribution histogram."""
    print()
    print("=" * 80)
    print("  ANALYSIS 1b: Time-Gap Distribution (days between prior discharge & Ch.13 filing)")
    print("=" * 80)
    print()

    all_hits = f1_hits + f2_hits
    target_hits = [h for h in all_hits if not h['is_control']]
    ctrl_hits = [h for h in all_hits if h['is_control']]

    buckets = [
        ("0-30 days", 0, 30), ("31-90 days", 31, 90), ("91-180 days", 91, 180),
        ("181-365 days", 181, 365), ("1-2 years", 366, 730),
        ("2-3 years", 731, 1095), ("3-4 years", 1096, 1461),
    ]

    def bucket_hits(hits):
        counts = {label: 0 for label, _, _ in buckets}
        for h in hits:
            for label, lo, hi in buckets:
                if lo <= h['gap_days'] <= hi:
                    counts[label] += 1
                    break
        return counts

    target_counts = bucket_hits(target_hits)
    max_val = max(target_counts.values()) if target_counts and max(target_counts.values()) > 0 else 1
    bar_width = 40

    print(f"  Target ({len(target_hits)} total hits):")
    print(f"  {'Bucket':<18} {'Count':>6}  Bar")
    print(f"  {'-'*70}")
    for label, _, _ in buckets:
        c = target_counts[label]
        bar_len = int((c / max_val) * bar_width) if c > 0 else 0
        print(f"  {label:<18} {c:>6}  {'#' * bar_len}")
    print()

    if ctrl_hits:
        ctrl_counts = bucket_hits(ctrl_hits)
        max_ctrl = max(ctrl_counts.values()) if ctrl_counts and max(ctrl_counts.values()) > 0 else 1
        print(f"  Control ({len(ctrl_hits)} total hits):")
        print(f"  {'Bucket':<18} {'Count':>6}  Bar")
        print(f"  {'-'*70}")
        for label, _, _ in buckets:
            c = ctrl_counts[label]
            bar_len = int((c / max_ctrl) * bar_width) if c > 0 else 0
            print(f"  {label:<18} {c:>6}  {'#' * bar_len}")
        print()

    if target_hits:
        gaps = [h['gap_days'] for h in target_hits]
        print(f"  Target gap stats:  min={min(gaps)}d  median={statistics.median(gaps):.0f}d  "
              f"mean={statistics.mean(gaps):.0f}d  max={max(gaps)}d")
    if ctrl_hits:
        gaps = [h['gap_days'] for h in ctrl_hits]
        print(f"  Control gap stats: min={min(gaps)}d  median={statistics.median(gaps):.0f}d  "
              f"mean={statistics.mean(gaps):.0f}d  max={max(gaps)}d")
    print()


def analysis_1c_strict_discharged(f1_hits, f2_hits):
    """Strict name matching for 'discharged despite bar' cases."""
    print()
    print("=" * 80)
    print("  ANALYSIS 1c: STRICT Matching -- 'Discharged Despite Bar' Cases")
    print("  (Requires EXACT first+last name match between prior and Ch.13 case titles)")
    print("=" * 80)
    print()

    all_hits = f1_hits + f2_hits
    target_hits = [h for h in all_hits if not h['is_control']]

    discharged_despite = [h for h in target_hits if h.get('ch13_discharged', '').strip()]
    print(f"  Total target hits where barred Ch.13 shows a discharge: {len(discharged_despite)}")
    print()

    def apply_strict_filter(hits_list):
        strict, fuzzy_only = [], []
        for h in hits_list:
            prior_pairs = extract_first_last_strict(h.get('prior_case_title', ''))
            ch13_pairs = extract_first_last_strict(h.get('ch13_case_title', ''))
            matched = any(pp[0] == cp[0] and pp[1] == cp[1]
                          for pp in prior_pairs for cp in ch13_pairs)
            (strict if matched else fuzzy_only).append(h)
        return strict, fuzzy_only

    strict, fuzzy = apply_strict_filter(discharged_despite)

    def dedup(hits_list):
        seen = set()
        unique = []
        for h in sorted(hits_list, key=lambda x: x['gap_days']):
            key = (h['prior_case'], h['ch13_case'])
            if key not in seen:
                seen.add(key)
                unique.append(h)
        return unique

    unique_strict = dedup(strict)
    unique_fuzzy = dedup(fuzzy)

    print(f"  Target STRICT first+last matches with discharge despite bar: {len(unique_strict)}")
    print()

    if unique_strict:
        for i, h in enumerate(unique_strict, 1):
            section = h['section'].replace('f', 'f(') + ')'
            print(f"  [{i}] {h['debtor']}")
            print(f"      Prior:  {h['prior_case']} ({h['prior_court'].upper()}) Ch.{h['prior_chapter']}"
                  f" discharged {h['prior_discharge']}")
            print(f"              Attorneys: {fmt_attys(h['prior_attorneys_set'])}")
            print(f"      Ch.13:  {h['ch13_case']} ({h['ch13_court'].upper()}) filed {h['ch13_filed']}")
            print(f"              Attorneys: {fmt_attys(h['ch13_all_attys'])}")
            print(f"      Gap:    {h['gap_days']}d ({h['gap_years']}yr)  [{section}]")
            print(f"      Ch.13 DISCHARGED: {h['ch13_discharged']}")
            same_tag = "SAME-FIRM" if h['prior_is_target'] else "CROSS-FIRM"
            print(f"      Firm:   {same_tag}")
            print()

    if unique_fuzzy:
        print(f"  FUZZY-ONLY matches (failed strict -- possible false positives): {len(unique_fuzzy)}")
        for i, h in enumerate(unique_fuzzy, 1):
            section = h['section'].replace('f', 'f(') + ')'
            print(f"    [{i}] Prior title: {h['prior_case_title']!r}")
            print(f"        Ch.13 title: {h['ch13_case_title']!r}")
            print(f"        Name key: {h['name_key']!r}")
            print(f"        {h['prior_case']} Ch.{h['prior_chapter']} disch {h['prior_discharge']}"
                  f" -> {h['ch13_case']} filed {h['ch13_filed']} [{section}]")
            print()

    print(f"  SUMMARY: {len(unique_strict)} strict + {len(unique_fuzzy)} fuzzy-only"
          f" = {len(unique_strict) + len(unique_fuzzy)} total 'discharged despite bar'")
    print()


def analysis_1_summary(f1_hits, f2_hits, target_canonical, control_canonical):
    """Per-attorney summary table for 1328(f)."""
    print()
    print("=" * 80)
    print("  ANALYSIS 1 SUMMARY: Section 1328(f) Violations by Attorney")
    print("  (Ch.13 filed on/after BAPCPA 10/17/2005)")
    print("=" * 80)
    print()

    by_attorney = defaultdict(lambda: {'f1': 0, 'f2': 0, 'total': 0,
                                        'f1_same': 0, 'f1_cross': 0,
                                        'f2_same': 0, 'f2_cross': 0})

    for h in f1_hits:
        for atty in h['ch13_all_attys']:
            by_attorney[atty]['f1'] += 1
            by_attorney[atty]['total'] += 1
            if h['prior_is_target']:
                by_attorney[atty]['f1_same'] += 1
            else:
                by_attorney[atty]['f1_cross'] += 1

    for h in f2_hits:
        for atty in h['ch13_all_attys']:
            by_attorney[atty]['f2'] += 1
            by_attorney[atty]['total'] += 1
            if h['prior_is_target']:
                by_attorney[atty]['f2_same'] += 1
            else:
                by_attorney[atty]['f2_cross'] += 1

    target_attys = {k: v for k, v in by_attorney.items() if k in target_canonical}
    ctrl_attys = {k: v for k, v in by_attorney.items() if k in control_canonical}

    if target_attys:
        print(f"  Target Attorneys:")
        print(f"  {'Attorney':<28} {'f(1)':<7} {'f(2)':<7} {'Total':<7} {'Same':<7} {'Cross':<7}")
        print(f"  {'-'*63}")
        for atty in sorted(target_attys.keys(), key=lambda k: -target_attys[k]['total']):
            v = target_attys[atty]
            same = v['f1_same'] + v['f2_same']
            cross = v['f1_cross'] + v['f2_cross']
            print(f"  {atty:<28} {v['f1']:<7} {v['f2']:<7} {v['total']:<7} {same:<7} {cross:<7}")
        t_f1 = sum(v['f1'] for v in target_attys.values())
        t_f2 = sum(v['f2'] for v in target_attys.values())
        t_same = sum(v['f1_same'] + v['f2_same'] for v in target_attys.values())
        t_cross = sum(v['f1_cross'] + v['f2_cross'] for v in target_attys.values())
        print(f"  {'-'*63}")
        print(f"  {'Target TOTAL':<28} {t_f1:<7} {t_f2:<7} {t_f1+t_f2:<7} {t_same:<7} {t_cross:<7}")
        print()

    if ctrl_attys:
        print(f"  Control Attorneys:")
        print(f"  {'Attorney':<28} {'f(1)':<7} {'f(2)':<7} {'Total':<7}")
        print(f"  {'-'*49}")
        for atty in sorted(ctrl_attys.keys(), key=lambda k: -ctrl_attys[k]['total']):
            v = ctrl_attys[atty]
            print(f"  {atty:<28} {v['f1']:<7} {v['f2']:<7} {v['total']:<7}")
        c_f1 = sum(v['f1'] for v in ctrl_attys.values())
        c_f2 = sum(v['f2'] for v in ctrl_attys.values())
        print(f"  {'-'*49}")
        print(f"  {'Control TOTAL':<28} {c_f1:<7} {c_f2:<7} {c_f1+c_f2:<7}")
        print()

    target_f1 = [h for h in f1_hits if not h['is_control']]
    target_f2 = [h for h in f2_hits if not h['is_control']]
    unique_ch13 = set(h['ch13_case'] for h in target_f1 + target_f2)
    print(f"  Unique Target Ch.13 cases with 1328(f) bar: {len(unique_ch13)}")
    discharged = [h for h in target_f1 + target_f2 if h.get('ch13_discharged', '').strip()]
    unique_discharged = set(h['ch13_case'] for h in discharged)
    print(f"  Ch.13 cases with discharge DESPITE bar: {len(unique_discharged)}")
    print()


# -- ANALYSIS 2: Section 109(g) Filing Bar -----------------------------------

def analysis_2_109g(cases, case_attorneys, target_canonical, control_canonical):
    """Screen for 109(g)(1) violations: dismiss-refile within 180 days."""
    print()
    print("=" * 80)
    print("  ANALYSIS 2: Section 109(g)(1) Filing Bar Screen")
    print("  (Case dismissed + new case filed within 180 days)")
    print("=" * 80)
    print()

    WILLFUL_PATTERNS = [
        re.compile(r'failure\s+to\s+make\s+plan\s+payments', re.IGNORECASE),
        re.compile(r'failure\s+to\s+appear', re.IGNORECASE),
        re.compile(r'failure\s+to\s+file', re.IGNORECASE),
        re.compile(r'failure\s+to\s+commence', re.IGNORECASE),
        re.compile(r'failure\s+to\s+pay\s+filing\s+fee', re.IGNORECASE),
        re.compile(r'other\s+reason', re.IGNORECASE),
    ]

    def is_potentially_willful(disposition):
        if not disposition:
            return False
        return any(pat.search(disposition) for pat in WILLFUL_PATTERNS)

    debtor_groups = group_by_debtor(cases)
    repeat_groups = {k: v for k, v in debtor_groups.items() if len(v) >= 2}

    hits = []
    seen_pairs = set()

    for name_key, group_cases in repeat_groups.items():
        unique_cases = {}
        for c in group_cases:
            cid = c.get('caseId', '')
            if cid not in unique_cases:
                unique_cases[cid] = c
        cases_list = list(unique_cases.values())
        if len(cases_list) < 2:
            continue

        dismissed = [c for c in cases_list if parse_date(c.get('dateDismissed', ''))]
        if not dismissed:
            continue

        for prior in dismissed:
            prior_dismissed = parse_date(prior.get('dateDismissed', ''))
            if not prior_dismissed:
                continue
            prior_case_id = prior.get('caseId', '')
            prior_attys = case_attorneys.get(prior_case_id, set())

            for new_case in cases_list:
                new_case_id = new_case.get('caseId', '')
                if new_case_id == prior_case_id:
                    continue
                new_filed = parse_date(new_case.get('dateFiled', ''))
                if not new_filed or new_filed <= prior_dismissed:
                    continue
                gap_days = (new_filed - prior_dismissed).days
                if gap_days > WINDOW_109G_DAYS:
                    continue
                pair_key = (prior_case_id, new_case_id)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                new_attys = case_attorneys.get(new_case_id, set())
                new_target = new_attys & target_canonical
                new_ctrl = new_attys & control_canonical
                if not new_target and not new_ctrl:
                    continue

                is_control = bool(new_ctrl) and not bool(new_target)

                hits.append({
                    'debtor': new_case.get('caseTitle', ''),
                    'prior_case': prior.get('caseNumberFull', ''),
                    'prior_court': prior.get('courtId', ''),
                    'prior_chapter': prior.get('bankruptcyChapter', '').strip(),
                    'prior_dismissed': prior_dismissed.strftime('%Y-%m-%d'),
                    'prior_disposition': prior.get('disposition', ''),
                    'prior_attorneys_set': frozenset(prior_attys),
                    'potentially_willful': is_potentially_willful(prior.get('disposition', '')),
                    'new_case': new_case.get('caseNumberFull', ''),
                    'new_court': new_case.get('courtId', ''),
                    'new_chapter': new_case.get('bankruptcyChapter', '').strip(),
                    'new_filed': new_filed.strftime('%Y-%m-%d'),
                    'new_target_attys': frozenset(new_target),
                    'new_ctrl_attys': frozenset(new_ctrl),
                    'gap_days': gap_days,
                    'is_control': is_control,
                    'new_dismissed': new_case.get('dateDismissed', ''),
                    'new_discharged': new_case.get('dateDischarged', ''),
                    'new_disposition': new_case.get('disposition', ''),
                })

    hits.sort(key=lambda h: (h['is_control'], h['gap_days']))
    target_hits = [h for h in hits if not h['is_control']]
    ctrl_hits = [h for h in hits if h['is_control']]

    print(f"  Total potential 109(g) violations: {len(hits)}")
    print(f"    Target:  {len(target_hits)}")
    print(f"    Control: {len(ctrl_hits)}")
    print()

    target_willful = [h for h in target_hits if h['potentially_willful']]
    print(f"  Potentially willful (disposition suggests failure):")
    print(f"    Target:  {len(target_willful)}")
    print(f"    Control: {len([h for h in ctrl_hits if h['potentially_willful']])}")
    print()

    # Per-attorney breakdown
    atty_stats = defaultdict(lambda: {'total': 0, 'willful': 0})
    for h in hits:
        attys = h['new_target_attys'] | h['new_ctrl_attys']
        for atty in attys:
            atty_stats[atty]['total'] += 1
            if h['potentially_willful']:
                atty_stats[atty]['willful'] += 1

    target_atty_stats = {k: v for k, v in atty_stats.items() if k in target_canonical}
    if target_atty_stats:
        print(f"  Per-Attorney (Target):")
        print(f"  {'Attorney':<28} {'Total':<8} {'Willful':<8}")
        print(f"  {'-'*44}")
        for atty in sorted(target_atty_stats.keys(), key=lambda k: -target_atty_stats[k]['total']):
            v = target_atty_stats[atty]
            print(f"  {atty:<28} {v['total']:<8} {v['willful']:<8}")
        print()

    # Shortest gaps
    shortest = sorted(target_hits, key=lambda x: x['gap_days'])[:15]
    if shortest:
        print(f"  FASTEST Target Dismiss-Refile Turnarounds (top 15):")
        print(f"  {'#':<4} {'Gap':>5} {'Debtor':<40} {'Prior Case':<22} {'New Case':<22}")
        print(f"  {'-'*93}")
        for i, h in enumerate(shortest, 1):
            print(f"  {i:<4} {h['gap_days']:>4}d {h['debtor'][:40]:<40} "
                  f"{h['prior_case']:<22} {h['new_case']:<22}")
        print()

    print(f"  NOTE: Section 109(g)(1) requires 'willful failure to abide by orders")
    print(f"  of the court.' PACER disposition codes cannot definitively distinguish")
    print(f"  voluntary from willful dismissals. All hits require manual verification.")
    print()
    return hits


# -- ANALYSIS 3: Ch.7 -> Ch.13 Pipeline -------------------------------------

def analysis_3_pipeline(cases, case_attorneys, target_canonical, control_canonical):
    """Ch.7 discharge -> Ch.13 filing by same attorney."""
    print()
    print("=" * 80)
    print("  ANALYSIS 3: Ch.7 -> Ch.13 Same-Attorney Conversion Timing ('Pipeline')")
    print("  (Same attorney handles Ch.7 discharge then files Ch.13 for same debtor)")
    print("=" * 80)
    print()

    debtor_groups = group_by_debtor(cases)
    repeat_groups = {k: v for k, v in debtor_groups.items() if len(v) >= 2}

    hits = []
    seen_pairs = set()

    for name_key, group_cases in repeat_groups.items():
        unique_cases = {}
        for c in group_cases:
            cid = c.get('caseId', '')
            if cid not in unique_cases:
                unique_cases[cid] = c
        cases_list = list(unique_cases.values())
        if len(cases_list) < 2:
            continue

        ch7_discharged = [c for c in cases_list
                          if c.get('bankruptcyChapter', '').strip() == '7'
                          and parse_date(c.get('dateDischarged', ''))]
        ch13_filed = [c for c in cases_list
                      if c.get('bankruptcyChapter', '').strip() == '13']
        if not ch7_discharged or not ch13_filed:
            continue

        for ch7 in ch7_discharged:
            ch7_discharge = parse_date(ch7.get('dateDischarged', ''))
            ch7_case_id = ch7.get('caseId', '')
            ch7_attys = case_attorneys.get(ch7_case_id, set())

            for ch13 in ch13_filed:
                ch13_case_id = ch13.get('caseId', '')
                if ch13_case_id == ch7_case_id:
                    continue
                ch13_file_date = parse_date(ch13.get('dateFiled', ''))
                if not ch13_file_date or ch13_file_date <= ch7_discharge:
                    continue

                pair_key = (ch7_case_id, ch13_case_id)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                ch13_attys = case_attorneys.get(ch13_case_id, set())
                shared_attys = ch7_attys & ch13_attys
                if not shared_attys:
                    continue

                shared_target = shared_attys & target_canonical
                shared_ctrl = shared_attys & control_canonical
                if not shared_target and not shared_ctrl:
                    continue

                is_control = bool(shared_ctrl) and not bool(shared_target)
                gap_days = (ch13_file_date - ch7_discharge).days

                hits.append({
                    'debtor': ch13.get('caseTitle', ''),
                    'ch7_case': ch7.get('caseNumberFull', ''),
                    'ch7_court': ch7.get('courtId', ''),
                    'ch7_discharge': ch7_discharge.strftime('%Y-%m-%d'),
                    'ch13_case': ch13.get('caseNumberFull', ''),
                    'ch13_court': ch13.get('courtId', ''),
                    'ch13_filed': ch13_file_date.strftime('%Y-%m-%d'),
                    'shared_attorneys': frozenset(shared_attys),
                    'shared_target': frozenset(shared_target),
                    'shared_ctrl': frozenset(shared_ctrl),
                    'gap_days': gap_days,
                    'is_control': is_control,
                    'ch13_dismissed': ch13.get('dateDismissed', ''),
                    'ch13_discharged': ch13.get('dateDischarged', ''),
                    'ch13_disposition': ch13.get('disposition', ''),
                })

    hits.sort(key=lambda h: (h['is_control'], h['gap_days']))
    target_hits = [h for h in hits if not h['is_control']]
    ctrl_hits = [h for h in hits if h['is_control']]

    print(f"  Total Ch.7->Ch.13 same-attorney conversions: {len(hits)}")
    print(f"    Target:  {len(target_hits)}")
    print(f"    Control: {len(ctrl_hits)}")
    print()

    # Per-attorney stats
    atty_gaps = defaultdict(list)
    for h in hits:
        for atty in h['shared_attorneys']:
            if atty in target_canonical or atty in control_canonical:
                atty_gaps[atty].append(h['gap_days'])

    target_atty_gaps = {k: v for k, v in atty_gaps.items() if k in target_canonical}
    if target_atty_gaps:
        print(f"  Per-Attorney (Target):")
        print(f"  {'Attorney':<28} {'Count':>6} {'Min':>7} {'Median':>8} {'Mean':>8} {'Max':>7} {'<90d':>5} {'<180d':>6}")
        print(f"  {'-'*76}")
        for atty in sorted(target_atty_gaps.keys(), key=lambda k: -len(target_atty_gaps[k])):
            gaps = target_atty_gaps[atty]
            lt90 = sum(1 for g in gaps if g < 90)
            lt180 = sum(1 for g in gaps if g < 180)
            med = statistics.median(gaps)
            mn = statistics.mean(gaps)
            print(f"  {atty:<28} {len(gaps):>6} {min(gaps):>6}d {med:>7.0f}d {mn:>7.0f}d "
                  f"{max(gaps):>6}d {lt90:>5} {lt180:>6}")

        if target_hits:
            all_gaps = [h['gap_days'] for h in target_hits]
            lt90 = sum(1 for g in all_gaps if g < 90)
            lt180 = sum(1 for g in all_gaps if g < 180)
            print(f"  {'-'*76}")
            print(f"  {'Target TOTAL':<28} {len(all_gaps):>6} {min(all_gaps):>6}d "
                  f"{statistics.median(all_gaps):>7.0f}d {statistics.mean(all_gaps):>7.0f}d "
                  f"{max(all_gaps):>6}d {lt90:>5} {lt180:>6}")
        print()

    # Top 20 fastest turnarounds
    fastest = sorted(target_hits, key=lambda x: x['gap_days'])[:20]
    if fastest:
        print(f"  FASTEST Target Ch.7->Ch.13 Turnarounds (top 20):")
        print(f"  {'#':<4} {'Gap':>5} {'Debtor':<35} {'Ch.7 Case':<22} {'Ch.13 Case':<22} {'Attorney':<25}")
        print(f"  {'-'*113}")
        for i, h in enumerate(fastest, 1):
            atty_str = fmt_attys(h['shared_target'] or h['shared_attorneys'])
            print(f"  {i:<4} {h['gap_days']:>4}d {h['debtor'][:35]:<35} "
                  f"{h['ch7_case']:<22} {h['ch13_case']:<22} {atty_str[:25]}")
        print()

    # Outcome analysis
    if target_hits:
        dismissed_count = sum(1 for h in target_hits if h['ch13_dismissed'])
        discharged_count = sum(1 for h in target_hits if h['ch13_discharged'])
        open_count = sum(1 for h in target_hits if not h['ch13_dismissed'] and not h['ch13_discharged'])
        print(f"  Target Ch.13 Outcomes (in Ch.7->Ch.13 pipeline):")
        print(f"    Dismissed:  {dismissed_count} ({100*dismissed_count/len(target_hits):.1f}%)")
        print(f"    Discharged: {discharged_count} ({100*discharged_count/len(target_hits):.1f}%)")
        print(f"    Open:       {open_count} ({100*open_count/len(target_hits):.1f}%)")
        resolved = dismissed_count + discharged_count
        if resolved > 0:
            print(f"    Failure rate (dismissed / resolved): "
                  f"{dismissed_count}/{resolved} = {100*dismissed_count/resolved:.1f}%")
        print()

    return hits


# -- Main --------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Multi-statute discharge bar scanner for PACER CSV data.\n\n"
            "Runs three analyses:\n"
            "  1. Section 1328(f) refinements (same-firm, histogram, strict matching)\n"
            "  2. Section 109(g) filing bar (dismiss-refile within 180 days)\n"
            "  3. Ch.7 -> Ch.13 pipeline (same-attorney conversion timing)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--data-dir', required=True, type=Path,
                        help='Directory containing PACER CSV exports')
    parser.add_argument('--target', action='append', default=[], metavar='LastName_FirstName',
                        help='Target attorney (repeatable)')
    parser.add_argument('--control', action='append', default=[], metavar='LastName_FirstName',
                        help='Control attorney (repeatable)')
    parser.add_argument('--courts', default=None,
                        help='Comma-separated court IDs (default: all)')
    parser.add_argument('--all-csvs', action='store_true',
                        help='Load ALL CSVs in data-dir')
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.target and not args.all_csvs:
        parser.error("At least one --target attorney is required (or use --all-csvs)")

    courts = set(c.strip().lower() for c in args.courts.split(',')) if args.courts else None
    target_canonical, control_canonical, all_keys, display_map = \
        build_attorney_sets(args.target, args.control)
    file_filter_keys = None if args.all_csvs else all_keys

    print("=" * 80)
    print("  DISCHARGE BAR SCANNER -- Three Analyses on PACER CSV Data")
    print("=" * 80)
    print()
    if target_canonical:
        print(f"  Target attorneys: {', '.join(sorted(target_canonical))}")
    if control_canonical:
        print(f"  Control attorneys: {', '.join(sorted(control_canonical))}")
    print()

    cases, case_attorneys = load_all_cases(
        args.data_dir, file_filter_keys, display_map, target_canonical, courts
    )

    ch7 = sum(1 for c in cases if c.get('bankruptcyChapter', '').strip() == '7')
    ch13 = sum(1 for c in cases if c.get('bankruptcyChapter', '').strip() == '13')
    ch11 = sum(1 for c in cases if c.get('bankruptcyChapter', '').strip() == '11')
    print(f"  Ch.7: {ch7:,}  |  Ch.13: {ch13:,}  |  Ch.11: {ch11:,}  |  "
          f"Other: {len(cases) - ch7 - ch13 - ch11:,}")
    print()

    # Analysis 1
    print("\n" + "#" * 80)
    print("#  ANALYSIS 1: Section 1328(f) Discharge Bar Refinements")
    print("#" * 80)
    print("\n  Running 1328(f) screen...")
    f1_hits, f2_hits = screen_1328f(cases, case_attorneys, target_canonical, control_canonical)
    target_f1 = [h for h in f1_hits if not h['is_control']]
    target_f2 = [h for h in f2_hits if not h['is_control']]
    ctrl_f1 = [h for h in f1_hits if h['is_control']]
    ctrl_f2 = [h for h in f2_hits if h['is_control']]
    print(f"  f(1) hits: {len(f1_hits)} ({len(target_f1)} Target + {len(ctrl_f1)} Control)")
    print(f"  f(2) hits: {len(f2_hits)} ({len(target_f2)} Target + {len(ctrl_f2)} Control)")

    analysis_1a_same_vs_cross(f1_hits, f2_hits, target_canonical, control_canonical)
    analysis_1b_histogram(f1_hits, f2_hits)
    analysis_1c_strict_discharged(f1_hits, f2_hits)
    analysis_1_summary(f1_hits, f2_hits, target_canonical, control_canonical)

    # Analysis 2
    print("\n" + "#" * 80)
    print("#  ANALYSIS 2: Section 109(g)(1) Filing Bar Screen")
    print("#" * 80)
    analysis_2_109g(cases, case_attorneys, target_canonical, control_canonical)

    # Analysis 3
    print("\n" + "#" * 80)
    print("#  ANALYSIS 3: Ch.7 -> Ch.13 Same-Attorney Conversion Timing")
    print("#" * 80)
    analysis_3_pipeline(cases, case_attorneys, target_canonical, control_canonical)

    # Methodological notes
    print()
    print("=" * 80)
    print("  METHODOLOGICAL NOTES")
    print("=" * 80)
    print()
    print("  1. Name matching uses normalized first+last tokens. Some hits may be")
    print("     different people with the same name. Manual verification required.")
    print("  2. Pre-BAPCPA Ch.13 cases (filed before 10/17/2005) excluded from 1328(f).")
    print("  3. 'Discharged despite bar' cases may have legitimate explanations")
    print("     (hardship discharge, date imprecision, court waiver).")
    print("  4. Section 109(g)(1) requires 'willful failure' -- disposition codes in")
    print("     PACER CSVs cannot definitively distinguish voluntary vs willful.")
    print("  5. Ch.7->Ch.13 pipeline analysis captures cases where the SAME attorney")
    print("     handled both. Short turnarounds suggest systematic pipeline behavior.")
    print("  6. Cases deduplicated by caseId before all analyses.")
    print("  7. Joint cases split on ' and ' -- each spouse matched independently.")
    print()


if __name__ == '__main__':
    main()
