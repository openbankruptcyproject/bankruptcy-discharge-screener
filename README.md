# Bankruptcy Court Monitoring Toolkit

Open-source Python tools for monitoring US bankruptcy courts and detecting patterns in publicly available PACER data. Standard library only. No pip install needed.

Three tool families:
1. **RSS Monitor** -- Real-time court surveillance using free RSS feeds ($0/day)
2. **Discharge Bar Screener** -- Detect potential [11 U.S.C. 1328(f)](https://www.law.cornell.edu/uscode/text/11/1328) violations, [109(g)](https://www.law.cornell.edu/uscode/text/11/109) filing bars, and Ch.7-to-Ch.13 pipeline patterns in PACER CSV exports
3. **Practice Report** -- Attorney practice quality profiles: volume, outcomes, case duration, statutory compliance, repeat debtors, comparative analysis

## RSS Monitor

### `rss_monitor.py` -- Real-Time Court Surveillance

Fetches free public RSS feeds from US bankruptcy courts and runs five analysis layers on every new docket entry. No PACER login required. $0 operating cost. Standard library only.

```
python rss_monitor.py                         # Default courts from config
python rss_monitor.py --court mowbk           # Single court
python rss_monitor.py --courts mowbk ksbk     # Multiple courts
python rss_monitor.py --national              # National mill-detection mode
python rss_monitor.py --fullsend              # ALL ~90 US bankruptcy courts
python rss_monitor.py --screen                # Enable 1328(f) screening
python rss_monitor.py --expanded              # Expanded court set from config
python rss_monitor.py --portfolio             # Show all portfolio hits
python rss_monitor.py --full                  # All display flags on
python rss_monitor.py --all                   # Show every RSS entry
python rss_monitor.py --stats                 # Portfolio loading stats
python rss_monitor.py --rebuild               # Force rebuild portfolio cache
python rss_monitor.py --dry-run               # Fetch without updating state
python rss_monitor.py --reset                 # Clear seen-state
```

**Five surveillance layers:**

1. **Case-specific alerts** -- Hand-picked cases with custom trigger keywords (e.g., "motion to dismiss", "withdrawal", "contempt"). Configurable per case.
2. **Portfolio monitoring** -- Cross-references RSS entries against PACER CSV exports. Any docket activity on a target attorney's case triggers an alert.
3. **New filing detection** -- Catches voluntary petitions as they hit the docket. Track new filings in real time.
4. **Section 1328(f) screening** -- Screens new Ch.13 filings against the debtor index to flag discharge-barred cases the moment they appear on the docket.
5. **Serial filer detection** -- Matches debtor names across the portfolio to identify repeat filers.

**Additional features:**
- Mill signal scoring (heuristic scoring of docket events for bankruptcy mill indicators)
- Tiered priority system (T1-T6: primary, secondary, watchlist, portfolio, associated, control)
- Filing velocity trends and time-series tracking (`--timeseries`)
- Monitored case changelog (`--history`)
- Covers all ~90 US bankruptcy courts

### Configuration

Copy `rss_config.example.json` to `rss_config.json` and customize:

```json
{
  "courts": {
    "default": ["mowbk", "ksbk"],
    "expanded": ["mowbk", "ksbk", "moebk"],
    "national": ["mowbk", "ksbk", "txsb", "ilnb", "cacb", "flsb"]
  },
  "target_attorneys": {
    "names": ["Smith", "Jones"]
  },
  "watched_cases": {
    "24-12345": {
      "name": "Example Debtor",
      "court": "mowbk",
      "tier": 1,
      "attorney": "Smith, John",
      "triggers": ["withdrawal", "plan modification", "contempt"]
    }
  },
  "portfolio_triggers": {
    "keywords": ["motion to dismiss", "conversion", "sanctions", "withdrawal"]
  }
}
```

See `rss_config.example.json` for the full configuration template with all options.

### How RSS Feeds Work

Every US bankruptcy court publishes a free RSS feed at a predictable URL:
```
https://ecf.{court-code}.uscourts.gov/cgi-bin/rss_outside.pl
```

These feeds contain the last ~24 hours of docket activity. Entries disappear when they roll off, so the monitor saves state between runs to track what's been seen. No authentication needed. No PACER charges.

### Data Directory

The monitor stores state in `rss_data/` (auto-created):
- `rss_state.json` -- Seen entries (prevents duplicate alerts)
- `rss_changelog.json` -- History of monitored case activity
- `rss_alerts.json` -- Triggered alerts log
- `portfolio_cache.json` -- Cached portfolio from CSV exports
- `timeseries.json` -- Filing velocity data

---

## Discharge Bar Screener

### What is Section 1328(f)?

Section 1328(f) of the Bankruptcy Code bars discharge in a Chapter 13 case if the debtor received a prior discharge within certain time limits:

- **1328(f)(1):** No discharge if a Ch.7, Ch.11, or Ch.12 discharge was granted within **4 years** before the Ch.13 filing date.
- **1328(f)(2):** No discharge if a Ch.13 discharge was granted within **2 years** before the Ch.13 filing date.

This provision was enacted by BAPCPA (effective October 17, 2005).

**Why this matters:** When an attorney files a Ch.13 case that is discharge-barred, the debtor pays filing fees and attorney fees for a case that can never achieve its purpose. The debtor's time is wasted, their filing history is impacted, and they receive no benefit. This is a bright-line test -- three data points determine the violation:

1. Date of prior discharge
2. Date of new Ch.13 filing
3. Chapter of prior case

No expert testimony needed. No subjective judgment. Arithmetic.

### `screen_1328f.py` -- Core Screener

The primary tool. Screens PACER Case Locator CSV exports for 1328(f) violations.

```
python screen_1328f.py --data-dir ./csv-exports --target Smith_John
python screen_1328f.py --data-dir ./csv-exports --target Smith_John --target Doe_Jane
python screen_1328f.py --data-dir ./csv-exports --target Smith_John --control Jones_Bob
python screen_1328f.py --data-dir ./csv-exports --target Smith_John --output-json results.json
```

**What it does:**
- Loads all PACER CSV exports from the specified directory
- Groups cases by debtor name (fuzzy matching on first + last name)
- For each debtor with 2+ cases, checks if any Ch.13 filing falls within the 1328(f) statutory window after a prior discharge
- Reports violations with full case details, gap calculations, and attorney attribution
- Optionally outputs structured JSON for further analysis

**Output sections:**
- f(1) violations (4-year bar: Ch.7/11/12 discharge -> Ch.13)
- f(2) violations (2-year bar: Ch.13 discharge -> Ch.13)
- Cross-attorney detail (prior case by different attorney)
- Most egregious cases (shortest gaps, non-dismissed barred cases)
- Per-attorney summary table
- Methodological caveats

### `screen_discharge_bars.py` -- Multi-Statute Scanner

Extended analysis covering three related statutory bars:

```
python screen_discharge_bars.py --data-dir ./csv-exports --target Smith_John
```

**Three analyses:**
1. **Section 1328(f) refinements** -- Same-firm vs. cross-firm classification, time-gap histograms, strict name matching for "discharged despite bar" cases
2. **Section 109(g) filing bar** -- Cases dismissed then refiled within 180 days by the same attorney
3. **Ch.7 -> Ch.13 pipeline** -- Same attorney handles Ch.7 discharge then files Ch.13 for same debtor (business model indicator)

---

## Attorney Practice Report

### `practice_report.py` -- Practice Quality Profiles

Same PACER CSVs, same `--target` / `--control` pattern. Generates a comprehensive practice profile for any attorney in your data.

```
python practice_report.py --data-dir ./csv-exports --target Smith_John
python practice_report.py --data-dir ./csv-exports --target Smith_John --control Jones_Bob
python practice_report.py --data-dir ./csv-exports --target Smith_John --output-json report.json
python practice_report.py --data-dir ./csv-exports --target Smith_John --oneline
python practice_report.py --data-dir ./csv-exports --all
```

**Six metric groups:**

1. **Volume Profile** -- Total cases, chapter breakdown (7/11/12/13), chapter mix %, filing date range, filing velocity (cases/year), courts active
2. **Outcome Analysis** -- Ch. 13 dismissal/discharge/pending rates, disposition breakdown (top reasons: failure to make payments, failure to file, etc.)
3. **Case Duration** -- Median days to dismissal, median days to discharge, % dismissed within 90 days (bare petition signal), % dismissed within 180 days
4. **Statutory Compliance** -- 1328(f)(1) and (2) hits with rate per 1,000 Ch. 13 cases, 109(g) refiling bar hits, Ch. 7 → Ch. 13 pipeline count
5. **Debtor Patterns** -- Unique debtors, debtors with 2+ cases under same attorney, serial filing rate, max cases per debtor
6. **Comparative Analysis** -- Side-by-side table with delta column when comparing target vs control

**Output formats:**
- **Text** (default): Clean tables, one section per metric group
- **JSON** (`--output-json`): Structured for aggregation across districts
- **One-line** (`--oneline`): Quick scan, one line per attorney:
  `Smith, John | 450 Ch.13 | 78% dismissed | 2.3/yr | 12 1328f hits (2.7%)`

---

## Getting PACER Data

These tools process locally-downloaded CSV files. They do **not** access PACER servers or make any network calls.

See [docs/pacer_csv_guide.md](docs/pacer_csv_guide.md) for step-by-step instructions on downloading CSVs from the PACER Case Locator.

**Quick version:**
1. Go to https://pcl.uscourts.gov
2. Create a free PACER account (if you don't have one)
3. Search by attorney name, selecting bankruptcy courts
4. Export results as CSV
5. Save CSVs to a directory
6. Run the screener against that directory

CSV files should follow the naming convention: `api_{LastName_FirstName}_{court}_{timestamp}.csv`

## Quick Start

```
git clone https://github.com/openbankruptcyproject/bankruptcy-discharge-screener.git
cd bankruptcy-discharge-screener

# RSS Monitor
cp rss_config.example.json rss_config.json   # Edit with your courts/attorneys
python rss_monitor.py --help

# Discharge Bar Screener
python screen_1328f.py --data-dir ./csv-exports --help
```

## Requirements

- Python 3.8 or higher
- Standard library only -- **no pip install needed**

Processes 100K+ cases in under a minute on commodity hardware.

## Methodology

### Name Matching
Debtor names are normalized (lowercased, suffixes stripped, middle names handled) and matched on first + last name. This catches middle-name variations and suffix differences but may produce false positives for common names. **All hits require manual verification.**

### BAPCPA Filter
Only Ch.13 cases filed on or after October 17, 2005 are screened. Section 1328(f) did not exist before BAPCPA.

### Deduplication
Cases are deduplicated by PACER case ID. Joint cases ("John Smith and Jane Smith") are split and each spouse is matched independently.

### Known Limitations
- Fuzzy name matching can produce false positives (different people, same name)
- PACER data may have entry lag or date imprecision
- "Discharged despite bar" cases may have legitimate explanations (hardship discharge, court waiver)
- The bar prevents **discharge**, not filing -- an open case is not necessarily an error yet

## Live Map

**[View the national map](https://openbankruptcyproject.github.io/bankruptcy-discharge-screener/)** -- see which districts have been screened and what the numbers look like.

The map updates as volunteers screen new districts. Every row is independently generated from public PACER data.

---

## Screen Your District

We tested this on two federal districts, 56,563 Ch. 13 filings screened, 360 flagged inside the 1328(f) window, 14 hand-verified, all confirmed. 114 flagged cases in the multi-district sample received a discharge despite the bar.

**Help build the national picture:**

- **[Screening guide](docs/volunteer_guide.md)**, step-by-step: pull PACER CSVs, run the screener, share results (~30 min per district)
- **[Submit results](docs/submission_template.md)**, form field reference for reporting what you find
- **[Leaderboard](LEADERBOARD.md)**, districts screened, records, hall of fame

Pick a district, pick some high-volume filers, and run the tool. The more districts screened, the clearer the picture of whether this is localized or systemic. First person to find a district with a 5%+ hit rate gets the top spot.

---

## Running Tests

```
python -m unittest discover tests
```

## License

MIT License. See [LICENSE](LICENSE).

## Disclaimer

This tool is for research and analysis purposes. It identifies *potential* violations based on publicly available data. All results require manual verification before drawing conclusions. The tool does not provide legal advice.
