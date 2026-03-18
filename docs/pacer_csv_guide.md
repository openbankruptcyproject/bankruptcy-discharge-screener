# How to Download PACER Case Locator CSVs

This guide explains how to get the CSV data files that the screening tools require.

## What is PACER Case Locator?

The PACER Case Locator (PCL) is a free search tool provided by the U.S. Courts that lets you search for bankruptcy cases across all federal courts. It's available at:

**https://pcl.uscourts.gov**

## Step-by-Step Instructions

### 1. Create a PACER Account

If you don't already have one:
- Go to https://pacer.uscourts.gov
- Click "Register for an Account"
- Follow the registration process
- PACER charges $0.10/page for document access, but Case Locator searches and CSV exports are **free**

### 2. Access the Case Locator

- Go to https://pcl.uscourts.gov
- Log in with your PACER credentials
- Select "Bankruptcy" as the case type

### 3. Search by Attorney Name

- In the search form, select "Attorney" as the party role
- Enter the attorney's last name and first name
- Select the court(s) you want to search (e.g., "Missouri Western Bankruptcy" = mowbk)
- You can search multiple courts, but it's cleaner to search one court at a time
- Click "Search"

### 4. Export Results as CSV

- After results load, look for the "Download" or "Export" option
- Select CSV format
- Save the file

### 5. Naming Convention

For the screening tools to auto-discover your CSVs, name them following this pattern:

```
api_{LastName_FirstName}_{court}_{timestamp}.csv
```

Examples:
```
api_Smith_John_mowbk_20260301.csv
api_Smith_John_ksbk_20260301.csv
api_Doe_Jane_mowbk_20260301.csv
```

The tools will automatically:
- Match attorney keys from `--target` and `--control` arguments to filenames
- Pick the latest file when multiple exports exist for the same attorney+court
- Extract court IDs from the filename

### 6. Organize Your Data

Create a directory for your CSV exports:

```
csv-exports/
  api_Smith_John_mowbk_20260301.csv
  api_Smith_John_ksbk_20260301.csv
  api_Doe_Jane_mowbk_20260301.csv
  api_Jones_Bob_mowbk_20260301.csv    (control attorney)
```

Then run:
```
python screen_1328f.py --data-dir ./csv-exports --target Smith_John --target Doe_Jane --control Jones_Bob
```

## CSV Column Format

PACER Case Locator CSVs contain these key columns (among others):

| Column | Description | Example |
|--------|-------------|---------|
| `caseId` | Internal unique case ID | `1234567` |
| `caseNumberFull` | Full case number | `4:2024bk40010` |
| `caseTitle` | Debtor name(s) | `John A Smith` |
| `bankruptcyChapter` | Chapter (7, 11, 13) | `13` |
| `dateFiled` | Filing date | `2024-01-05` |
| `dateDischarged` | Discharge date | `2024-06-15` |
| `dateDismissed` | Dismissal date | `2025-03-01` |
| `disposition` | Case outcome | `Standard Discharge` |
| `courtId` | Court code | `mowbk` |
| `lastName` | Attorney last name | `Smith` |
| `firstName` | Attorney first name | `John` |

Dates are in `YYYY-MM-DD` format. Empty cells indicate missing or not-applicable data.

## Tips

- **Search broadly.** Include all courts where the attorney might practice. Many attorneys are admitted in multiple districts.
- **Include control attorneys.** Searching a comparison attorney from the same court gives you a baseline violation rate to compare against.
- **Multiple exports are fine.** If you re-export data later, the tools automatically pick the latest file per attorney+court combination.
- **Large portfolios.** An attorney with thousands of cases will produce a large CSV. This is expected and the tools handle it efficiently.

## Cost

- PACER Case Locator searches: **Free**
- CSV exports: **Free**
- Individual document downloads (dockets, petitions): $0.10/page, capped at $3.00/document

The screening tools only need the CSV exports, which cost nothing.
