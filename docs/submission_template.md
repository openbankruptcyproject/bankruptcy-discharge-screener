# Screening Results Submission Form, Field Reference

This documents the fields for the Google Form where volunteers submit their screening results. Create the form at [forms.google.com](https://forms.google.com) with these fields.

## Form Fields

### District Info

| Field | Type | Notes |
|---|---|---|
| District screened | Short text | Court code (e.g., `txsb`, `cacb`, `flsb`) |
| State | Dropdown | US states |

### Screening Results

| Field | Type | Notes |
|---|---|---|
| Total Ch. 13 cases loaded | Number | From screener output |
| Number of attorneys screened | Number | Target + control |
| f(1) hits (4-year bar) | Number | Ch. 7/11/12 → Ch. 13 |
| f(2) hits (2-year bar) | Number | Ch. 13 → Ch. 13 |
| Discharged despite bar | Number | If the screener reports this |

### Top Attorney Findings

| Field | Type | Notes |
|---|---|---|
| Attorney with most hits | Short text | Name, hit count |
| Their total Ch. 13 caseload | Number | Approximate |
| Hit rate (hits / total cases) | Short text | e.g., "12/450 = 2.7%" |
| Second highest attorney (optional) | Short text | Name, hit count |

### Control Group

| Field | Type | Notes |
|---|---|---|
| Control attorney name | Short text | If you ran a comparison |
| Control attorney hits | Number | |
| Control attorney total cases | Number | |

### Practice Report Scorecard

| Field | Type | Notes |
|---|---|---|
| Highest dismissal rate (%) | Short text | Attorney name + rate, e.g. "Smith: 78.2%" |
| Their Ch. 13 caseload | Number | Total Ch. 13 cases for that attorney |
| Highest 109(g) rate per 1K | Short text | Attorney name + rate |
| Most repeat debtors | Short text | Attorney name + count |
| Median days to dismissal (highest-volume attorney) | Number | From practice report |
| % dismissed within 90 days (highest-volume attorney) | Short text | e.g., "15.3%" |

### Verification (Optional)

| Field | Type | Notes |
|---|---|---|
| Did you verify any hits by pulling petitions? | Multiple choice | `Yes` / `No` |
| How many verified as real violations? | Number | |
| How many were false positives? | Number | |
| Verification notes | Long text | Common patterns, Q9 answers, etc. |

### Meta

| Field | Type | Notes |
|---|---|---|
| Your Reddit or GitHub username | Short text | Optional, for credit |
| Anything unusual or interesting? | Long text | Patterns, outliers, surprises |
| Would you be willing to screen more districts? | Multiple choice | `Yes` / `Maybe` / `No` |

## Form Settings

- **Collect email addresses:** Off (anonymous submissions)
- **Response spreadsheet:** Link to a Google Sheet for aggregation
- **Confirmation message:** "Thanks! Your screening results have been recorded. Every district screened makes the national picture clearer."

## Aggregation

After collecting responses:
1. Compile a national summary table (district, cases screened, hits, top attorney, hit rate)
2. Identify districts with abnormally high hit rates
3. Post periodic updates to the Reddit thread
4. If a district shows a clear pattern, that's a lead for local journalists, bar associations, or legal aid orgs
