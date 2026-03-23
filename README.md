# Bankruptcy Discharge Bar Screener

Open-source Python tool for detecting potential [11 U.S.C. 1328(f)](https://www.law.cornell.edu/uscode/text/11/1328) discharge bar violations in publicly available PACER data. Standard library only. No pip install needed.

## What is Section 1328(f)?

Section 1328(f) of the Bankruptcy Code bars discharge in a Chapter 13 case if the debtor received a prior discharge within certain time limits:

- **1328(f)(1):** No discharge if a Ch.7, Ch.11, or Ch.12 discharge was granted within **4 years** before the Ch.13 filing date.
- **1328(f)(2):** No discharge if a Ch.13 discharge was granted within **2 years** before the Ch.13 filing date.

This provision was enacted by BAPCPA (effective October 17, 2005).

**Why this matters:** When an attorney files a Ch.13 case that is discharge-barred, the debtor pays filing fees and attorney fees for a case that can never achieve its purpose. The debtor's time is wasted, their filing history is impacted, and they receive no benefit. This is a bright-line test -- three data points determine the violation:

1. Date of prior discharge
2. Date of new Ch.13 filing
3. Chapter of prior case

No expert testimony needed. No subjective judgment. Arithmetic.

## `screen_1328f.py` -- Core Screener

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

## `screen_discharge_bars.py` -- Multi-Statute Scanner

Extended analysis covering three related statutory bars:

```
python screen_discharge_bars.py --data-dir ./csv-exports --target Smith_John
```

**Three analyses:**
1. **Section 1328(f) refinements** -- Same-firm vs. cross-firm classification, time-gap histograms, strict name matching for "discharged despite bar" cases
2. **Section 109(g) filing bar** -- Cases dismissed then refiled within 180 days by the same attorney
3. **Ch.7 -> Ch.13 pipeline** -- Same attorney handles Ch.7 discharge then files Ch.13 for same debtor (business model indicator)

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
git clone https://github.com/ilikemath9999/bankruptcy-discharge-screener.git
cd bankruptcy-discharge-screener

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

## Resources

| Resource | Link |
|----------|------|
| National Screener Map | [1328f.com](https://1328f.com) |
| Section 1328(f) Explainer | [1328f.com/explainer](https://1328f.com/explainer.html) |
| Eligibility Checker | [1328f.com/check](https://1328f.com/check.html) |
| Interactive Dashboard | [1328f.com/dashboard](https://1328f.com/dashboard.html) |
| Case Law Reference | [1328f.com/caselaw](https://1328f.com/caselaw.html) |
| Statute Comparison | [1328f.com/compare](https://1328f.com/compare.html) |
| Bankruptcy Glossary | [1328f.com/glossary](https://1328f.com/glossary.html) |
| State-by-State Data | [1328f.com/states/](https://1328f.com/states/missouri.html) (55 states) |
| Research & Reports | [1328f.org](https://1328f.org) |
| Research Library | [1328f.org/research](https://1328f.org/research/) |
| Methodology | [1328f.org/methodology](https://1328f.org/methodology/) |

The map updates as volunteers screen new districts. Every row is independently generated from public PACER data.

---

## Screen Your District

We tested this on a multi-district sample: 56,563 Ch. 13 filings screened, 360 flagged inside the 1328(f) window, 14 hand-verified, all confirmed. In that verified sample, 114 flagged cases received a discharge despite the bar.

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

## Citing This Tool

If you use this tool or its data in academic research, legal analysis, or published reporting, please cite it as:

**APA:**
> Bankruptcy Discharge Bar Screener (Version 1.3) [Computer software]. (2026). https://github.com/ilikemath9999/bankruptcy-discharge-screener

**BibTeX:**
```bibtex
@software{discharge_screener_2026,
  title = {Bankruptcy Discharge Bar Screener},
  version = {1.3},
  year = {2026},
  url = {https://github.com/ilikemath9999/bankruptcy-discharge-screener},
  note = {Open-source tool for detecting 11 U.S.C. \S 1328(f) discharge bar violations in PACER data}
}
```

**Chicago:**
> "Bankruptcy Discharge Bar Screener," version 1.3, 2026, https://github.com/ilikemath9999/bankruptcy-discharge-screener.

**Data source:** FJC Integrated Database, Ch.13 cases FY2008-2024; PACER Case Locator public records.

**Legal authority:** 11 U.S.C. Section 1328(f); *In re Blendheim*, 803 F.3d 477 (9th Cir. 2015) (filing-to-filing measurement).

---

## License

MIT License. See [LICENSE](LICENSE).

## Disclaimer

This tool is for research and analysis purposes. It identifies *potential* violations based on publicly available data. All results require manual verification before drawing conclusions. The tool does not provide legal advice.
