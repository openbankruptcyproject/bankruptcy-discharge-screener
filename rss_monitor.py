#!/usr/bin/env python3
"""
PACER RSS Docket Monitor v1.0 — real-time court surveillance using free RSS feeds.

Fetches public RSS feeds from US bankruptcy courts and runs multiple analysis
layers on every new docket entry. No PACER login required. $0 cost. Stdlib only.

Five surveillance layers:
  1. Case-specific alerts with custom trigger keywords
  2. Portfolio-wide attorney case monitoring (from PACER CSV exports)
  3. New case filing detection (voluntary petitions)
  4. Section 1328(f) discharge-bar screening on new Ch. 13 filings
  5. Serial filer detection (debtor name matching across portfolio)

Configuration: copy rss_config.example.json to rss_config.json and customize.

Usage:
    python rss_monitor.py                    # Default courts from config
    python rss_monitor.py --court mowbk      # One court only
    python rss_monitor.py --courts mowbk ksbk moebk  # Multiple courts
    python rss_monitor.py --expanded         # Expanded court set from config
    python rss_monitor.py --national         # National mill-detection mode
    python rss_monitor.py --fullsend         # ALL ~90 US bankruptcy courts
    python rss_monitor.py --portfolio        # Show all portfolio hits
    python rss_monitor.py --screen           # Enable 1328(f) + serial filer screening
    python rss_monitor.py --full             # All display flags on
    python rss_monitor.py --all              # Show every RSS entry
    python rss_monitor.py --history          # Show monitored case changelog
    python rss_monitor.py --stats            # Portfolio loading stats
    python rss_monitor.py --timeseries       # Filing velocity trends
    python rss_monitor.py --reset            # Clear seen-state
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── Paths ─────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, 'rss_data')
CSV_DIR = os.path.join(SCRIPT_DIR, 'csv-exports')
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'rss_config.json')
STATE_FILE = os.path.join(DATA_DIR, 'rss_state.json')
CHANGELOG_FILE = os.path.join(DATA_DIR, 'rss_changelog.json')
ALERTS_FILE = os.path.join(DATA_DIR, 'rss_alerts.json')
PORTFOLIO_CACHE = os.path.join(DATA_DIR, 'portfolio_cache.json')
TIMESERIES_FILE = os.path.join(DATA_DIR, 'timeseries.json')

# ── RSS Feed URL Generation ──────────────────────────────────────────────

def _rss_url(ecf_code):
    """Generate RSS feed URL from ECF court code."""
    return f'https://ecf.{ecf_code}.uscourts.gov/cgi-bin/rss_outside.pl'

# Every US Bankruptcy Court — key = internal label, value = ECF subdomain
ALL_COURT_CODES = {
    # 8th Circuit
    'mowbk': 'mowb', 'moebk': 'moeb', 'ksbk': 'ksb',
    'nebk': 'neb', 'arwbk': 'arwb', 'arebk': 'areb',
    'mnbk': 'mnb', 'ianbk': 'ianb', 'iasbk': 'iasb',
    'ndbk': 'ndb', 'sdbk': 'sdb',
    # 5th Circuit
    'txsb': 'txsb', 'txnb': 'txnb', 'txeb': 'txeb', 'txwb': 'txwb',
    'laeb': 'laeb', 'lawb': 'lawb', 'lamb': 'lamb',
    'msnb': 'msnb', 'mssb': 'mssb',
    # 7th Circuit
    'ilnb': 'ilnb', 'ilcb': 'ilcb', 'ilsb': 'ilsb',
    'innb': 'innb', 'insb': 'insb', 'wieb': 'wieb', 'wiwb': 'wiwb',
    # 9th Circuit
    'cacb': 'cacb', 'caeb': 'caeb', 'canb': 'canb', 'casb': 'casb',
    'azb': 'azb', 'nvb': 'nvb', 'orb': 'orb',
    'wawb': 'wawb', 'waeb': 'waeb', 'hib': 'hib', 'akb': 'akb',
    'idb': 'idb', 'mtb': 'mtb', 'gub': 'gub',
    # 11th Circuit
    'ganb': 'ganb', 'gamb': 'gamb', 'gasb': 'gasb',
    'flsb': 'flsb', 'flmb': 'flmb', 'flnb': 'flnb',
    'alnb': 'alnb', 'almb': 'almb', 'alsb': 'alsb',
    # 6th Circuit
    'ohnb': 'ohnb', 'ohsb': 'ohsb', 'mieb': 'mieb', 'miwb': 'miwb',
    'kyeb': 'kyeb', 'kywb': 'kywb',
    'tneb': 'tneb', 'tnmb': 'tnmb', 'tnwb': 'tnwb',
    # 4th Circuit
    'vaeb': 'vaeb', 'vawb': 'vawb', 'mdb': 'mdb',
    'nceb': 'nceb', 'ncmb': 'ncmb', 'ncwb': 'ncwb',
    'scb': 'scb', 'wvnb': 'wvnb', 'wvsb': 'wvsb',
    # 2nd Circuit
    'nysb': 'nysb', 'nyeb': 'nyeb', 'nynb': 'nynb', 'nywb': 'nywb',
    'ctb': 'ctb', 'vtb': 'vtb',
    # 3rd Circuit
    'njb': 'njb', 'paeb': 'paeb', 'pawb': 'pawb', 'pamb': 'pamb', 'deb': 'deb',
    # 1st Circuit
    'mab': 'mab', 'nhb': 'nhb', 'rib': 'rib', 'meb': 'meb', 'prb': 'prb',
    # 10th Circuit
    'cob': 'cob', 'utb': 'utb', 'nmb': 'nmb',
    'okwb': 'okwb', 'oknb': 'oknb', 'okeb': 'okeb', 'wyb': 'wyb',
    # DC
    'dcb': 'dcb',
}

FEEDS = {code: _rss_url(ecf) for code, ecf in ALL_COURT_CODES.items()}

# ── Chapter-Specific Auto-Triggers ────────────────────────────────────────

AUTO_TRIGGERS_BY_CHAPTER = {
    '13': [
        'amended plan', 'confirmation denied', 'denying confirmation',
        'trustee motion to dismiss', '341 meeting', '341 continued',
        'wage order', 'income deduction', 'order to show cause',
        'deficiency', 'order to correct', 'relief from stay',
        'discharge entered', 'hardship discharge',
        'withdrawal', 'substitution of counsel',
        'fee application', 'compensation',
    ],
    '11': [
        'cash collateral', 'operating report', 'monthly report',
        'disclosure statement', 'plan of reorganization',
        'employment application', 'turnover',
        'status conference', 'status report',
        'order to show cause', 'conversion',
        'motion to dismiss', 'sub v', 'subchapter v',
        'withdrawal', 'substitution of counsel',
        'fee application', 'compensation',
    ],
    '7': [
        'discharge', 'objection to discharge',
        'complaint', 'adversary proceeding',
        'trustee report', 'trustee final report',
        'motion to dismiss', 'withdrawal',
        'fee application', 'reaffirmation',
    ],
    '12': [
        'plan', 'confirmation', 'trustee motion',
        'motion to dismiss', 'relief from stay',
        'discharge', 'fee application', 'withdrawal',
    ],
}

AUTO_TRIGGERS_DEFAULT = [
    'motion to dismiss', 'order dismissing', 'conversion',
    'order to show cause', 'deficiency',
    'withdrawal', 'substitution of counsel',
    'fee application', 'discharge',
    'relief from stay', 'amended plan',
    'confirmation denied', 'denying confirmation',
]

# ── Mill Signal Keywords ─────────────────────────────────────────────────

MILL_SIGNAL_KEYWORDS = [
    'order to show cause', 'deficiency', 'order to correct',
    'bare petition', 'motion to dismiss', 'order dismissing',
    'sanctions', 'disciplinary', 'contempt',
    'withdrawal of counsel', 'withdraw as counsel',
    'petition deficiency', 'failure to file',
    'failure to appear', 'failure to comply',
]

# ── Configuration Loading ────────────────────────────────────────────────

_CONFIG = None

def load_config():
    """Load rss_config.json. Returns config dict with defaults for missing keys."""
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    defaults = {
        'courts': {'default': [], 'expanded': [], 'national': []},
        'target_attorneys': {'names': []},
        'associated_attorneys': {'names': []},
        'control_attorneys': {'names': []},
        'watched_cases': {},
        'portfolio_triggers': {'keywords': []},
        'national_watchlist': {'attorneys': {}, 'firms': {}, 'keywords': []},
        'tier_labels': {
            '1': 'PRIMARY', '2': 'SECONDARY', '3': 'WATCHLIST',
            '4': 'PORTFOLIO', '5': 'ASSOCIATED', '6': 'CONTROL',
        },
    }

    if not os.path.exists(CONFIG_FILE):
        log(f"No config file at {CONFIG_FILE} — using defaults.")
        log(f"Copy rss_config.example.json to rss_config.json and customize.")
        _CONFIG = defaults
        return _CONFIG

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log(f"Error reading config: {e}")
        _CONFIG = defaults
        return _CONFIG

    # Merge with defaults
    for key, default_val in defaults.items():
        if key not in data:
            data[key] = default_val
    _CONFIG = data
    return _CONFIG


def get_target_attorneys():
    cfg = load_config()
    return set(cfg.get('target_attorneys', {}).get('names', []))


def get_associated_attorneys():
    cfg = load_config()
    return set(cfg.get('associated_attorneys', {}).get('names', []))


def get_control_attorneys():
    cfg = load_config()
    return set(cfg.get('control_attorneys', {}).get('names', []))


def get_watched_cases():
    """Returns dict: case_id -> {name, court, tier, attorney, triggers}."""
    cfg = load_config()
    raw = cfg.get('watched_cases', {})
    # Strip comment keys
    return {k: v for k, v in raw.items() if not k.startswith('_')}


def get_watched_triggers():
    """Returns dict: case_id -> [trigger keywords]."""
    cases = get_watched_cases()
    return {cid: info.get('triggers', []) for cid, info in cases.items()}


def get_portfolio_triggers():
    cfg = load_config()
    return cfg.get('portfolio_triggers', {}).get('keywords', [])


def get_tier_labels():
    cfg = load_config()
    raw = cfg.get('tier_labels', {})
    return {int(k): v for k, v in raw.items() if k.isdigit()}


def get_default_courts():
    cfg = load_config()
    return cfg.get('courts', {}).get('default', [])


def get_expanded_courts():
    cfg = load_config()
    return cfg.get('courts', {}).get('expanded', [])


def get_national_courts():
    cfg = load_config()
    return cfg.get('courts', {}).get('national', [])


# ── Regex ────────────────────────────────────────────────────────────────

CASE_NO_RE = re.compile(r'\b(\d{2}-\d{4,5})\b')
TITLE_NAME_RE = re.compile(r'^\d{2}-\d{4,5}(?:-\w+)?\s+(.+)$')

NEW_FILING_PATTERNS = [
    'voluntary petition', 'chapter 13 petition', 'chapter 7 petition',
    'chapter 11 petition', 'chapter 12 petition',
]


# ── Helpers ──────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def extract_case_number(text):
    m = CASE_NO_RE.search(text)
    return m.group(1) if m else None


def extract_docket_text(description):
    m = re.search(r'\[([^\]]+)\]', description)
    entry_text = m.group(1) if m else ''
    doc_m = re.search(r'>(\d+)</a>', description)
    doc_no = doc_m.group(1) if doc_m else ''
    if doc_no:
        return f"{entry_text} (Doc {doc_no})"
    return entry_text


def extract_doc_number(description):
    m = re.search(r'>(\d+)</a>', description)
    return int(m.group(1)) if m else None


def extract_chapter(description):
    m = re.search(r'Chapter:\s*(\d+)', description)
    return m.group(1) if m else ''


def extract_debtor_names(rss_title):
    m = TITLE_NAME_RE.match(rss_title)
    if not m:
        return []
    return parse_names(m.group(1))


def parse_names(name_str):
    parts = re.split(r'\s+and\s+', name_str, flags=re.IGNORECASE)
    names = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if re.search(r'\b(Inc|LLC|Corp|Ltd|LP|Co|L\.?L\.?C|P\.?C|LLP)\b\.?',
                      part, re.IGNORECASE):
            names.append({'type': 'business', 'full': part, 'last': '', 'first': ''})
            continue
        words = part.split()
        if len(words) >= 2:
            names.append({
                'type': 'individual', 'full': part,
                'first': words[0], 'last': words[-1],
            })
        elif len(words) == 1:
            names.append({
                'type': 'individual', 'full': part,
                'first': '', 'last': words[0],
            })
    return names


def is_new_filing(docket_text, doc_number=None):
    if doc_number == 1:
        return True
    text = docket_text.lower()
    return any(kw in text for kw in NEW_FILING_PATTERNS)


def parse_date_safe(date_str):
    if not date_str or not date_str.strip():
        return None
    for fmt in ('%a, %d %b %Y %H:%M:%S %Z', '%a, %d %b %Y %H:%M:%S GMT',
                '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%m/%d/%Y'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    stripped = re.sub(r'\s+\w{3,4}$', '', date_str.strip())
    for fmt in ('%a, %d %b %Y %H:%M:%S',):
        try:
            return datetime.strptime(stripped, fmt)
        except ValueError:
            continue
    return None


# ── Portfolio Loading ────────────────────────────────────────────────────

def load_portfolio_from_csvs():
    """Load case numbers from PACER Case Locator CSV exports.

    Returns dict: case_id -> {court, attorney, title, chapter, tier, ...}

    CSVs are expected at CSV_DIR with naming: api_LastName_FirstName_court_timestamp.csv

    Tier assignment:
      1-3: from watched_cases in config
      4: target attorneys
      5: associated attorneys
      6: control attorneys
    """
    csv_path = os.path.normpath(CSV_DIR)
    files = glob.glob(os.path.join(csv_path, 'api_*.csv'))

    target = get_target_attorneys()
    associated = get_associated_attorneys()
    controls = get_control_attorneys()

    if not files:
        log(f"No CSV files found in {csv_path}")
        log(f"Download CSVs from pcl.uscourts.gov and save them there.")
        return {}

    portfolio = {}
    for f in files:
        base = os.path.basename(f)
        parts = base.replace('api_', '').split('_')
        last_name = parts[0]

        if last_name in target:
            default_tier = 4
        elif last_name in associated:
            default_tier = 5
        elif last_name in controls:
            default_tier = 6
        else:
            continue

        try:
            with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    court = row.get('courtId', '')
                    year = row.get('caseYear', '')
                    num = row.get('caseNumber', '')
                    if not year or not num:
                        continue
                    case_id = f'{year[-2:]}-{num}'
                    if case_id in portfolio:
                        continue
                    first = parts[1] if len(parts) > 1 else ''
                    portfolio[case_id] = {
                        'court': court,
                        'attorney': f'{last_name}, {first}',
                        'attorney_last': last_name,
                        'title': row.get('caseTitle', ''),
                        'chapter': row.get('bankruptcyChapter', ''),
                        'filed': row.get('dateFiled', ''),
                        'disposition': row.get('disposition', ''),
                        'dismissed': row.get('dateDismissed', ''),
                        'discharged': row.get('dateDischarged', ''),
                        'tier': default_tier,
                    }
        except Exception as e:
            log(f"Error reading {base}: {e}")

    # Override tiers for watched cases
    watched = get_watched_cases()
    for case_id, info in watched.items():
        if case_id in portfolio:
            portfolio[case_id]['tier'] = info.get('tier', 1)
            portfolio[case_id]['name'] = info.get('name', '')
        else:
            portfolio[case_id] = {
                'court': info.get('court', ''),
                'attorney': info.get('attorney', ''),
                'attorney_last': info.get('attorney', '').split(',')[0].strip() if info.get('attorney') else '',
                'title': info.get('name', ''),
                'chapter': '',
                'filed': '', 'disposition': '', 'dismissed': '', 'discharged': '',
                'tier': info.get('tier', 1),
                'name': info.get('name', ''),
            }

    return portfolio


def load_portfolio():
    """Load portfolio, using cache if CSVs haven't changed."""
    csv_path = os.path.normpath(CSV_DIR)
    csv_files = glob.glob(os.path.join(csv_path, 'api_*.csv'))

    if os.path.exists(PORTFOLIO_CACHE):
        try:
            cache_mtime = os.path.getmtime(PORTFOLIO_CACHE)
            csv_mtime = max(os.path.getmtime(f) for f in csv_files) if csv_files else 0
            config_mtime = os.path.getmtime(CONFIG_FILE) if os.path.exists(CONFIG_FILE) else 0
            if cache_mtime > max(csv_mtime, config_mtime):
                with open(PORTFOLIO_CACHE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get('portfolio', {})
        except (json.JSONDecodeError, IOError, ValueError):
            pass

    portfolio = load_portfolio_from_csvs()

    ensure_data_dir()
    with open(PORTFOLIO_CACHE, 'w', encoding='utf-8') as f:
        json.dump({
            'built': datetime.now().isoformat(),
            'count': len(portfolio),
            'portfolio': portfolio,
        }, f)
    log(f"Portfolio cached: {len(portfolio)} cases")
    return portfolio


def auto_expand_monitored(portfolio, case_triggers):
    """Auto-expand triggers for recent active target-attorney filings.

    Finds all 2025+ target-attorney cases with no disposition and adds
    chapter-appropriate triggers. Does NOT overwrite hand-picked triggers.
    Returns count of cases added.
    """
    target = get_target_attorneys()
    added = 0
    cutoff = datetime(2025, 1, 1)

    for case_id, info in portfolio.items():
        atty_last = info.get('attorney_last', '')
        if atty_last not in target:
            continue
        if case_id in case_triggers:
            continue
        if info.get('dismissed') or info.get('discharged'):
            continue
        disp = (info.get('disposition') or '').strip().lower()
        if disp and disp not in ('', 'open', 'pending'):
            continue
        filed = info.get('filed', '')
        if not filed:
            continue
        filed_dt = parse_date_safe(filed)
        if not filed_dt or filed_dt < cutoff:
            continue

        ch = (info.get('chapter') or '').strip()
        triggers = AUTO_TRIGGERS_BY_CHAPTER.get(ch, AUTO_TRIGGERS_DEFAULT)
        case_triggers[case_id] = list(triggers)
        added += 1

    return added


# ── Debtor Name Index (for 1328(f) + serial filer screening) ─────────────

def build_debtor_index(portfolio):
    """Build last-name -> [records] index for name matching."""
    index = defaultdict(list)
    for case_no, info in portfolio.items():
        title = info.get('title', '')
        if not title:
            continue
        for name in parse_names(title):
            if name['type'] != 'individual' or not name.get('last'):
                continue
            last = name['last'].lower()
            if len(last) < 3:
                continue
            index[last].append({
                'case_no': case_no,
                'court': info.get('court', ''),
                'chapter': info.get('chapter', ''),
                'filed': info.get('filed', ''),
                'discharged': info.get('discharged', ''),
                'dismissed': info.get('dismissed', ''),
                'first': name['first'].lower(),
                'last': last,
                'full': name['full'],
                'attorney': info.get('attorney_last', ''),
                'tier': info.get('tier', 99),
            })
    return dict(index)


# ── Section 1328(f) Screening ────────────────────────────────────────────

def screen_1328f(debtor_names, debtor_index, filing_date_str):
    """Screen debtor names against prior filings for 1328(f) bar risk.

    Returns list of risk dicts, or None.
    """
    filing_date = parse_date_safe(filing_date_str)
    if not filing_date:
        return None

    risks = []
    for name in debtor_names:
        if name.get('type') == 'business':
            continue
        last = name.get('last', '').lower()
        first = name.get('first', '').lower()
        if not last or len(last) < 3:
            continue

        for m in debtor_index.get(last, []):
            m_first = m.get('first', '')
            if first and m_first and first[0] != m_first[0]:
                continue
            disch_date = parse_date_safe(m.get('discharged', ''))
            if not disch_date:
                continue
            gap_days = (filing_date - disch_date).days
            if gap_days < 0:
                continue
            gap_years = round(gap_days / 365.25, 2)
            prior_ch = m.get('chapter', '')

            risk = None
            if prior_ch in ('7', '11', '12') and gap_days < 1461:
                risk = {'bar': '4yr', 'section': '1328(f)(1)'}
            elif prior_ch == '13' and gap_days < 730:
                risk = {'bar': '2yr', 'section': '1328(f)(2)'}

            if risk:
                risk.update({
                    'name': name['full'],
                    'prior_case': m.get('case_no', ''),
                    'prior_court': m.get('court', ''),
                    'prior_chapter': prior_ch,
                    'discharged': m.get('discharged', ''),
                    'gap_days': gap_days,
                    'gap_years': gap_years,
                    'prior_attorney': m.get('attorney', ''),
                })
                risks.append(risk)

    seen = set()
    unique = []
    for r in risks:
        key = (r['prior_case'], r['name'])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique if unique else None


def check_serial_filer(debtor_names, current_case_no, debtor_index):
    """Check if debtor appeared in prior portfolio cases."""
    target = get_target_attorneys()
    matches = []
    for name in debtor_names:
        if name.get('type') == 'business':
            continue
        last = name.get('last', '').lower()
        first = name.get('first', '').lower()
        if not last or len(last) < 3:
            continue
        for m in debtor_index.get(last, []):
            if m['case_no'] == current_case_no:
                continue
            m_first = m.get('first', '')
            if first and m_first and first[0] != m_first[0]:
                continue
            if m.get('tier', 99) > 4:
                continue
            matches.append({
                'name': name['full'],
                'prior_case': m['case_no'],
                'prior_court': m.get('court', ''),
                'prior_name': m.get('full', ''),
                'prior_chapter': m.get('chapter', ''),
                'prior_attorney': m.get('attorney', ''),
                'prior_dismissed': m.get('dismissed', ''),
            })

    seen = set()
    unique = []
    for m in matches:
        if m['prior_case'] not in seen:
            seen.add(m['prior_case'])
            unique.append(m)
    return unique if unique else None


# ── Mill Signal Scoring ──────────────────────────────────────────────────

def score_mill_signals(entry):
    """Score an RSS entry for mill-like patterns. Returns (score, factors)."""
    score = 0
    factors = []
    docket_text = (entry.get('docket_text', '') or '').lower()
    doc_num = entry.get('doc_number')

    if doc_num == 1 and 'petition' in docket_text:
        score += 10
        factors.append('new_petition')
    if 'order to show cause' in docket_text or 'show cause' in docket_text:
        score += 15
        factors.append('osc')
    if any(kw in docket_text for kw in ('deficiency', 'order to correct',
                                         'failure to file', 'failure to comply')):
        score += 10
        factors.append('deficiency')
    if 'order dismissing' in docket_text or 'case dismissed' in docket_text:
        score += 10
        factors.append('dismissal')
    if 'sanction' in docket_text or 'contempt' in docket_text:
        score += 20
        factors.append('sanctions')
    if 'withdraw' in docket_text and ('counsel' in docket_text or 'attorney' in docket_text):
        score += 10
        factors.append('withdrawal')
    if 'fee application' in docket_text or 'application for compensation' in docket_text:
        score += 5
        factors.append('fee_app')
    if 'motion to dismiss' in docket_text and 'trustee' in docket_text:
        score += 10
        factors.append('trustee_mtd')
    if 'relief from stay' in docket_text or 'lift stay' in docket_text:
        score += 5
        factors.append('mfrs')

    return score, factors


def check_watchlist_hit(entry, watchlist):
    """Check if RSS entry matches national watchlist entries."""
    hits = []
    search_text = f"{entry.get('title', '')} {entry.get('docket_text', '')} " \
                  f"{entry.get('description', '')}".lower()
    for atty in watchlist.get('attorneys', set()):
        if atty.lower() in search_text:
            hits.append({'type': 'attorney', 'match': atty})
    for firm in watchlist.get('firms', set()):
        if firm.lower() in search_text:
            hits.append({'type': 'firm', 'match': firm})
    for kw in watchlist.get('keywords', []):
        if kw.lower() in search_text:
            hits.append({'type': 'keyword', 'match': kw})
    return hits


# ── State Persistence ────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return set(data.get('seen_guids', []))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def save_state(seen_guids):
    ensure_data_dir()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'updated': datetime.now().isoformat(),
            'count': len(seen_guids),
            'seen_guids': sorted(seen_guids),
        }, f, indent=2)


def load_changelog():
    if os.path.exists(CHANGELOG_FILE):
        try:
            with open(CHANGELOG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def append_changelog(new_entries):
    ensure_data_dir()
    changelog = load_changelog()
    existing_guids = {e.get('guid') for e in changelog if e.get('guid')}
    added = 0
    for entry in new_entries:
        if entry.get('guid') not in existing_guids:
            changelog.append(entry)
            existing_guids.add(entry['guid'])
            added += 1
    if added:
        with open(CHANGELOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(changelog, f, indent=2)
    return added


def append_alerts(new_alerts):
    ensure_data_dir()
    existing = []
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    existing_guids = {a.get('guid') for a in existing if a.get('guid')}
    added = 0
    for alert in new_alerts:
        if alert.get('guid') not in existing_guids:
            existing.append(alert)
            existing_guids.add(alert.get('guid'))
            added += 1
    if added:
        with open(ALERTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2)
    return added


# ── Time-Series Accumulator ──────────────────────────────────────────────

def load_timeseries():
    if os.path.exists(TIMESERIES_FILE):
        try:
            with open(TIMESERIES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {'daily_snapshots': {}}


def save_timeseries(ts):
    ensure_data_dir()
    with open(TIMESERIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(ts, f, indent=2)


def accumulate_timeseries(classified):
    """Record daily snapshot of RSS activity counts."""
    target = get_target_attorneys()
    today = datetime.now().strftime('%Y-%m-%d')
    ts = load_timeseries()
    if 'daily_snapshots' not in ts:
        ts['daily_snapshots'] = {}

    by_court = Counter(e.get('court', '?') for e in classified)
    portfolio_hits = sum(1 for e in classified if e.get('monitored'))
    new_filings = sum(1 for e in classified if e.get('new_filing'))
    f1328_hits = sum(1 for e in classified if e.get('f1328_risks'))

    dismissals = discharges = fee_apps = 0
    for e in classified:
        txt = (e.get('docket_text', '') or '').lower()
        if 'dismiss' in txt:
            dismissals += 1
        if 'discharge' in txt:
            discharges += 1
        if 'fee' in txt or 'compensation' in txt:
            fee_apps += 1

    by_attorney = defaultdict(lambda: {'events': 0, 'cases': set(), 'dismissals': 0})
    for e in classified:
        atty = e.get('attorney_last', '')
        if not atty or atty not in target:
            continue
        a = by_attorney[atty]
        a['events'] += 1
        a['cases'].add(e.get('case_no', ''))
        txt = (e.get('docket_text', '') or '').lower()
        if 'dismiss' in txt:
            a['dismissals'] += 1

    atty_dict = {}
    for atty, data in by_attorney.items():
        d = dict(data)
        d['cases'] = len(d['cases'])
        atty_dict[atty] = d

    snap = {
        'total_entries': len(classified),
        'portfolio_matches': portfolio_hits,
        'new_filings': new_filings,
        'dismissals': dismissals,
        'discharges': discharges,
        'fee_apps': fee_apps,
        'f1328_risks': f1328_hits,
        'by_court': dict(by_court),
        'by_attorney': atty_dict,
        'updated': datetime.now().isoformat(),
    }

    ts['daily_snapshots'][today] = snap
    save_timeseries(ts)


def show_timeseries(n=14):
    """Display filing velocity trends."""
    ts = load_timeseries()
    days = ts.get('daily_snapshots', {})
    if not days:
        print("No time-series data yet. Run the monitor first.")
        return

    sorted_days = sorted(days.keys())
    recent = sorted_days[-n:]

    print(f"\n{'=' * 60}")
    print(f"  Filing Velocity -- last {len(recent)} days of {len(sorted_days)} recorded")
    print(f"{'=' * 60}")
    print(f"\n  {'Date':<12} {'Total':>6} {'Port':>5} {'Dism':>5} "
          f"{'Disc':>5} {'Fee':>4} {'New':>4} {'1328f':>5}")
    print(f"  {'-' * 54}")

    totals = []
    for day in recent:
        d = days[day]
        total = d.get('total_entries', 0)
        port = d.get('portfolio_matches', 0)
        dism = d.get('dismissals', 0)
        disc = d.get('discharges', 0)
        fee = d.get('fee_apps', 0)
        nf = d.get('new_filings', 0)
        f13 = d.get('f1328_risks', 0)
        print(f"  {day:<12} {total:>6} {port:>5} {dism:>5} "
              f"{disc:>5} {fee:>4} {nf:>4} {f13:>5}")
        totals.append(total)

    if len(totals) >= 3:
        avg_recent = sum(totals[-3:]) / 3
        avg_older = sum(totals[:-3]) / max(len(totals) - 3, 1) if len(totals) > 3 else avg_recent
        if avg_older > 0:
            trend_pct = ((avg_recent - avg_older) / avg_older) * 100
            trend_dir = "UP" if trend_pct > 10 else "DOWN" if trend_pct < -10 else "STABLE"
            print(f"\n  Trend: {trend_dir} ({trend_pct:+.1f}% last 3d vs prior)")
    print()


# ── RSS Fetching & Parsing ───────────────────────────────────────────────

def fetch_feed(court_id, retries=2, timeout=15):
    """Fetch court RSS XML. Retries on transient failures."""
    url = FEEDS.get(court_id)
    if not url:
        return None
    for attempt in range(retries):
        try:
            req = Request(url, headers={'User-Agent': 'PACER-RSS-Monitor/1.0'})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode('utf-8', errors='replace')
        except (URLError, OSError):
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return None
    return None


def fetch_feeds_parallel(court_ids, max_workers=15):
    """Fetch multiple court RSS feeds concurrently."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_feed, cid): cid for cid in court_ids}
        for future in as_completed(futures):
            cid = futures[future]
            try:
                results[cid] = future.result()
            except Exception:
                results[cid] = None
    return results


def parse_feed(xml_string, court_id):
    """Parse RSS XML into list of entry dicts."""
    entries = []
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError as e:
        log(f"XML parse error for {court_id}: {e}")
        return entries

    channel = root.find('channel')
    if channel is None:
        return entries

    for item in channel.findall('item'):
        title = (item.findtext('title') or '').strip()
        link = (item.findtext('link') or '').strip()
        description = (item.findtext('description') or '').strip()
        pub_date = (item.findtext('pubDate') or '').strip()
        guid = (item.findtext('guid') or link or title).strip()
        case_no = extract_case_number(title) or extract_case_number(link)

        entries.append({
            'guid': guid,
            'court': court_id,
            'title': title,
            'link': link,
            'description': description,
            'pub_date': pub_date,
            'case_no': case_no,
            'fetched': datetime.now().isoformat(),
        })
    return entries


# ── Classification ───────────────────────────────────────────────────────

def classify_entry(entry, portfolio, case_triggers, debtor_index=None,
                   do_screen=False, national_mode=False, watchlist=None):
    """Enrich entry with portfolio + screening metadata."""
    target = get_target_attorneys()
    portfolio_kw = get_portfolio_triggers()

    e = dict(entry)
    case_no = e.get('case_no', '')
    desc = e.get('description', '')

    e['docket_text'] = extract_docket_text(desc)
    e['rss_chapter'] = extract_chapter(desc)
    e['doc_number'] = extract_doc_number(desc)

    # Portfolio match (must match BOTH case_no AND court)
    rss_court = e.get('court', '')
    if case_no in portfolio and portfolio[case_no].get('court', '') == rss_court:
        info = portfolio[case_no]
        e['monitored'] = True
        e['tier'] = info.get('tier', 4)
        e['case_name'] = info.get('name') or info.get('title', '')
        e['attorney'] = info.get('attorney', '')
        e['attorney_last'] = info.get('attorney_last', '')
    else:
        e['monitored'] = False
        e['tier'] = None
        e['case_name'] = None
        e['attorney'] = None
        e['attorney_last'] = None

    # Trigger matching
    search_text = f"{e['title']} {desc}".lower()
    triggers = []

    if case_no in case_triggers:
        for trigger in case_triggers[case_no]:
            if trigger.lower() in search_text:
                triggers.append(trigger)

    if e['monitored'] and e['tier'] in (1, 2, 3, 4):
        for trigger in portfolio_kw:
            if trigger.lower() in search_text and trigger not in triggers:
                triggers.append(f"[P] {trigger}")

    e['triggers'] = triggers
    e['debtor_names'] = extract_debtor_names(e.get('title', ''))
    e['new_filing'] = is_new_filing(e['docket_text'], e['doc_number'])

    # 1328(f) + serial filer screening
    e['f1328_risks'] = None
    e['serial_matches'] = None
    if do_screen and debtor_index and e['new_filing']:
        chapter = e['rss_chapter']
        if chapter == '13':
            e['f1328_risks'] = screen_1328f(
                e['debtor_names'], debtor_index, e.get('pub_date', ''))
        e['serial_matches'] = check_serial_filer(
            e['debtor_names'], case_no, debtor_index)

    # Mill signal scoring (national mode, non-portfolio entries)
    e['mill_score'] = 0
    e['mill_factors'] = []
    e['watchlist_hits'] = []
    if national_mode and not e['monitored']:
        score, factors = score_mill_signals(e)
        e['mill_score'] = score
        e['mill_factors'] = factors
        if watchlist:
            e['watchlist_hits'] = check_watchlist_hit(e, watchlist)
            if e['watchlist_hits']:
                e['mill_score'] += 15
                e['mill_factors'].append('watchlist')

    return e


# ── Display ──────────────────────────────────────────────────────────────

def format_summary(new_entries, show_portfolio=False, show_controls=False,
                   show_all=False, show_screen=False, national_mode=False):
    """Format classified entries into a readable summary."""
    tier_labels = get_tier_labels()
    lines = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines.append(f"\n{'=' * 60}")
    lines.append(f"  PACER RSS Monitor v1.0 -- {now}")
    lines.append(f"{'=' * 60}")

    max_tier = 999 if show_all else (5 if show_controls else 4)
    courts = sorted(set(e['court'] for e in new_entries))
    trigger_count = 0

    all_1328f = [e for e in new_entries if e.get('f1328_risks')]
    all_serial = [e for e in new_entries if e.get('serial_matches')]
    all_new_filings = [e for e in new_entries if e.get('new_filing')]

    for court in courts:
        court_entries = [e for e in new_entries if e['court'] == court]
        if show_all:
            matched = court_entries
        else:
            matched = [e for e in court_entries
                       if e.get('monitored') and (e.get('tier') or 99) <= max_tier]
        if not matched:
            continue

        total_court = len(court_entries)
        mon_count = len([e for e in court_entries if e.get('monitored')])
        new_count = len([e for e in court_entries if e.get('new_filing')])
        header_parts = [f"{total_court} total", f"{mon_count} portfolio"]
        if new_count:
            header_parts.append(f"{new_count} new filings")
        lines.append(f"\n{court.upper()} ({', '.join(header_parts)})")

        by_tier = defaultdict(list)
        for e in matched:
            by_tier[e.get('tier') or 99].append(e)

        for tier in sorted(by_tier.keys()):
            label = tier_labels.get(tier, f'TIER {tier}')
            entries = by_tier[tier]

            if tier <= 3:
                lines.append(f"  --- {label} ---")
                for e in sorted(entries, key=lambda x: x.get('case_no', '')):
                    name = e.get('case_name') or e.get('case_no') or '???'
                    case_no = e.get('case_no') or ''
                    docket = e.get('docket_text') or ''
                    lines.append(f"  [T{tier}] {name} {case_no} -- {docket}")
                    if e.get('triggers'):
                        trigger_count += len(e['triggers'])
                        lines.append(f"       >> {', '.join(e['triggers'])}")

            elif tier == 4:
                flagged = [e for e in entries if e.get('triggers')]
                quiet = [e for e in entries if not e.get('triggers')]
                lines.append(f"  --- {label} ({len(flagged)} flagged, "
                              f"{len(quiet)} quiet) ---")
                if flagged:
                    by_atty = defaultdict(list)
                    for e in flagged:
                        by_atty[e.get('attorney_last') or '???'].append(e)
                    for atty in sorted(by_atty.keys()):
                        for e in sorted(by_atty[atty], key=lambda x: x.get('case_no', '')):
                            case_no = e.get('case_no') or '???'
                            docket = e.get('docket_text') or ''
                            ch = e.get('rss_chapter') or ''
                            ch_str = f" ch{ch}" if ch else ''
                            lines.append(f"  [{atty}] {case_no}{ch_str} -- {docket}")
                            lines.append(f"       >> {', '.join(e['triggers'])}")
                            trigger_count += len(e['triggers'])
                if quiet:
                    by_atty_q = Counter(e.get('attorney_last') or '???' for e in quiet)
                    quiet_parts = [f"{a}: {c}" for a, c in sorted(by_atty_q.items())]
                    lines.append(f"    Quiet: {', '.join(quiet_parts)}")

    # 1328(f) screening results
    if show_screen and all_1328f:
        lines.append(f"\n{'=' * 60}")
        lines.append(f"  *** 1328(f) SCREENING: {len(all_1328f)} POTENTIAL VIOLATION(S) ***")
        lines.append(f"{'=' * 60}")
        for e in all_1328f:
            case_no = e.get('case_no', '???')
            court = e.get('court', '')
            names_str = ', '.join(n['full'] for n in e.get('debtor_names', []))
            lines.append(f"\n  NEW: {case_no} ({court}) ch{e.get('rss_chapter','')} -- {names_str}")
            for r in e['f1328_risks']:
                lines.append(f"    {r['section']}: {r['name']}")
                lines.append(f"    Prior: {r['prior_case']} ({r['prior_court']}) "
                             f"ch{r['prior_chapter']} -- discharged {r['discharged']}")
                lines.append(f"    Gap: {r['gap_days']}d ({r['gap_years']}yr) "
                             f"-- WITHIN {r['bar']} bar")

    # Serial filer matches
    if show_screen and all_serial:
        new_serial = [e for e in all_serial if not e.get('monitored')]
        if new_serial:
            lines.append(f"\n{'=' * 60}")
            lines.append(f"  SERIAL FILER MATCHES: {len(new_serial)} new filing(s) with history")
            lines.append(f"{'=' * 60}")
            for e in new_serial:
                case_no = e.get('case_no', '???')
                court = e.get('court', '')
                names_str = ', '.join(n['full'] for n in e.get('debtor_names', []))
                lines.append(f"\n  NEW: {case_no} ({court}) -- {names_str}")
                for m in e['serial_matches'][:5]:
                    parts = [f"Prior: {m['prior_case']}"]
                    if m.get('prior_court'):
                        parts[0] += f" ({m['prior_court']})"
                    if m.get('prior_chapter'):
                        parts.append(f"ch{m['prior_chapter']}")
                    if m.get('prior_attorney'):
                        parts.append(m['prior_attorney'])
                    lines.append(f"    {' | '.join(parts)}")

    # Mill signals (national mode)
    if national_mode:
        mill_flagged = [e for e in new_entries if e.get('mill_score', 0) >= 15]
        if mill_flagged:
            high_signal = [e for e in mill_flagged if e.get('mill_score', 0) >= 25]
            lines.append(f"\n{'=' * 60}")
            lines.append(f"  MILL SIGNALS: {len(mill_flagged)} flagged "
                         f"({len(high_signal)} high)")
            lines.append(f"{'=' * 60}")
            if high_signal:
                for e in sorted(high_signal, key=lambda x: -x.get('mill_score', 0))[:20]:
                    case_no = e.get('case_no', '???')
                    court = e.get('court', '')
                    docket = (e.get('docket_text', '') or '')[:55]
                    score = e.get('mill_score', 0)
                    factors = ', '.join(e.get('mill_factors', []))
                    lines.append(f"    [{score:>2}] {case_no} ({court}) -- {docket}")
                    lines.append(f"         Factors: {factors}")

    # Summary footer
    lines.append(f"\n{'=' * 60}")
    total = len(new_entries)
    mon = sum(1 for e in new_entries if e.get('monitored'))
    parts = [f"{total} RSS entries", f"{mon} portfolio matches"]
    if trigger_count:
        parts.append(f"{trigger_count} triggers")
    if all_new_filings:
        parts.append(f"{len(all_new_filings)} new filings")
    if all_1328f:
        parts.append(f"{len(all_1328f)} 1328(f) risks")
    lines.append(f"Total: {', '.join(parts)}")
    lines.append('')
    return '\n'.join(lines)


# ── History & Stats ──────────────────────────────────────────────────────

def show_history(n=30):
    changelog = load_changelog()
    if not changelog:
        print("No changelog entries yet. Run the monitor first.")
        return
    monitored = [e for e in changelog if e.get('monitored')]
    recent = monitored[-n:]
    print(f"\nLast {len(recent)} of {len(monitored)} portfolio entries "
          f"({len(changelog)} total):\n")
    for e in recent:
        tier = f"T{e['tier']}" if e.get('tier') else '--'
        case_no = e.get('case_no') or '???'
        court = e.get('court', '')
        name = e.get('case_name') or ''
        docket = e.get('docket_text') or e.get('title', '')[:60]
        print(f"  [{tier}] {name} {case_no} ({court}) -- {docket}")
        if e.get('triggers'):
            print(f"       >> {', '.join(e['triggers'])}")
    print()


def show_stats(portfolio):
    target = get_target_attorneys()
    associated = get_associated_attorneys()
    print(f"\n{'=' * 50}")
    print(f"  Portfolio Statistics")
    print(f"{'=' * 50}\n")
    print(f"Total cases loaded: {len(portfolio)}")
    by_tier = Counter(v.get('tier', 99) for v in portfolio.values())
    tier_labels = get_tier_labels()
    for tier in sorted(by_tier.keys()):
        label = tier_labels.get(tier, f'Tier {tier}')
        print(f"  T{tier} ({label}): {by_tier[tier]}")
    print()
    by_atty = Counter(v.get('attorney_last', '?') for v in portfolio.values())
    print("By attorney (target):")
    for atty, cnt in by_atty.most_common():
        if atty in target:
            print(f"  {atty}: {cnt}")
    print()


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='PACER RSS Docket Monitor -- real-time court surveillance')
    parser.add_argument('--court', help='Check one court only (e.g. mowbk)')
    parser.add_argument('--courts', nargs='+', help='Check specific courts')
    parser.add_argument('--expanded', action='store_true',
                        help='Scan expanded court set from config')
    parser.add_argument('--national', action='store_true',
                        help='Scan national courts (mill detection mode)')
    parser.add_argument('--fullsend', action='store_true',
                        help='Scan ALL ~90 US bankruptcy courts')
    parser.add_argument('--portfolio', action='store_true',
                        help='Show all portfolio hits (Tier 4)')
    parser.add_argument('--controls', action='store_true',
                        help='Include associated/control cases (Tier 5+)')
    parser.add_argument('--screen', action='store_true',
                        help='Enable 1328(f) + serial filer screening')
    parser.add_argument('--full', action='store_true',
                        help='All flags on')
    parser.add_argument('--all', action='store_true',
                        help='Show ALL RSS entries')
    parser.add_argument('--history', action='store_true',
                        help='Show portfolio changelog')
    parser.add_argument('--stats', action='store_true',
                        help='Show portfolio statistics')
    parser.add_argument('--timeseries', action='store_true',
                        help='Show filing velocity trends')
    parser.add_argument('--reset', action='store_true',
                        help='Clear seen-state')
    parser.add_argument('--rebuild', action='store_true',
                        help='Force rebuild portfolio cache')
    parser.add_argument('--dry-run', action='store_true',
                        help='Fetch and display without updating state')
    args = parser.parse_args()

    ensure_data_dir()

    # Fix Windows encoding
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except AttributeError:
            pass

    if args.full:
        args.portfolio = True
        args.controls = True
        args.screen = True

    # Load portfolio
    if args.rebuild and os.path.exists(PORTFOLIO_CACHE):
        os.remove(PORTFOLIO_CACHE)

    log("Loading portfolio...")
    portfolio = load_portfolio()
    target_count = sum(1 for v in portfolio.values() if v.get('tier', 99) <= 4)
    log(f"  {len(portfolio)} cases loaded ({target_count} target attorney)")

    # Build case triggers from config + auto-expand
    case_triggers = dict(get_watched_triggers())
    auto_count = auto_expand_monitored(portfolio, case_triggers)
    if auto_count:
        log(f"  Auto-expanded: {auto_count} active 2025+ cases with "
            f"chapter-specific triggers ({len(case_triggers)} total tracked)")

    if args.stats:
        show_stats(portfolio)
        return
    if args.history:
        show_history()
        return
    if args.timeseries:
        show_timeseries()
        return
    if args.reset:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
            log("State cleared.")
        return

    # Debtor index for screening
    debtor_index = None
    if args.screen:
        log("Building debtor name index...")
        debtor_index = build_debtor_index(portfolio)
        discharged = sum(1 for recs in debtor_index.values() for r in recs if r.get('discharged'))
        log(f"  {len(debtor_index)} unique last names, {discharged} with discharge dates")

    # National watchlist
    national_mode = args.national or args.fullsend
    watchlist = None
    if national_mode:
        cfg = load_config()
        wl_raw = cfg.get('national_watchlist', {})
        watchlist = {
            'attorneys': set(wl_raw.get('attorneys', {}).keys()),
            'firms': set(wl_raw.get('firms', {}).keys()),
            'keywords': [k.lower() for k in wl_raw.get('keywords', [])],
        }

    # Determine courts to scan
    if args.court:
        courts = [args.court]
    elif args.courts:
        courts = args.courts
    elif args.fullsend:
        courts = list(ALL_COURT_CODES.keys())
    elif args.national:
        courts = get_national_courts() or list(ALL_COURT_CODES.keys())[:15]
    elif args.expanded:
        courts = get_expanded_courts() or get_default_courts()
    else:
        courts = get_default_courts()

    seen = load_state()

    # Fetch RSS feeds
    all_entries = []
    failed_courts = []
    if len(courts) > 5:
        log(f"Parallel-fetching {len(courts)} courts...")
        results = fetch_feeds_parallel(courts, max_workers=20)
        for court_id in courts:
            xml = results.get(court_id)
            if xml is None:
                failed_courts.append(court_id)
                continue
            entries = parse_feed(xml, court_id)
            all_entries.extend(entries)
        log(f"  {len(all_entries)} total from {len(courts) - len(failed_courts)} courts")
    else:
        for court in courts:
            log(f"Fetching {court.upper()}...")
            xml = fetch_feed(court)
            if xml is None:
                failed_courts.append(court)
                continue
            entries = parse_feed(xml, court)
            log(f"  {len(entries)} entries from {court.upper()}")
            all_entries.extend(entries)

    if failed_courts:
        log(f"  {len(failed_courts)} failed: {', '.join(failed_courts[:10])}")

    if not all_entries:
        log("No entries fetched.")
        return

    # Filter to new
    new_entries = [e for e in all_entries if e['guid'] not in seen]
    log(f"{len(new_entries)} new ({len(all_entries) - len(new_entries)} seen)")

    if not new_entries:
        print(f"\nNo new entries. ({len(all_entries)} total, all previously seen)")
        return

    # Classify
    classified = [classify_entry(e, portfolio, case_triggers,
                                  debtor_index=debtor_index,
                                  do_screen=args.screen,
                                  national_mode=national_mode,
                                  watchlist=watchlist)
                  for e in new_entries]

    # Display
    print(format_summary(classified, show_portfolio=args.portfolio,
                         show_controls=args.controls, show_all=args.all,
                         show_screen=args.screen,
                         national_mode=national_mode))

    # Persist
    if not args.dry_run:
        new_guids = seen | {e['guid'] for e in all_entries}
        save_state(new_guids)

        portfolio_entries = [e for e in classified if e.get('monitored')]
        if portfolio_entries:
            append_changelog(portfolio_entries)

        alerts = [e for e in classified
                  if e.get('triggers') or e.get('f1328_risks')
                  or e.get('serial_matches')
                  or e.get('mill_score', 0) >= 20
                  or e.get('watchlist_hits')]
        if alerts:
            append_alerts(alerts)
            log(f"{len(alerts)} alerts logged")

        accumulate_timeseries(classified)
    else:
        log("Dry run -- state not updated.")


if __name__ == '__main__':
    main()
