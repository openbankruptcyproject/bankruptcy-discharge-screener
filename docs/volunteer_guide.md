# How to Screen Your District

Run the screener on your local bankruptcy court. Find out if attorneys in your area are filing discharge-barred cases. Takes about 30 minutes start to finish.

## What You Need

- A PACER account (free to create at [pacer.uscourts.gov](https://pacer.uscourts.gov))
- Python 3.8+ (standard library only, no pip install)
- This repo cloned locally

PACER Case Locator searches are free. CSV exports are free. The only cost is if you pull individual petitions to verify hits ($0.10-3.00 per document).

## Step 1: Pick a district and attorney

Every federal district has a bankruptcy court. Pick yours, or pick one you're curious about.

To find high-volume filers, go to [PACER Case Locator](https://pcl.uscourts.gov) and search by court. Sort by attorney name. The biggest filers jump out fast, if someone has 500+ Ch. 13 cases, they're worth screening.

You can also search by attorney name if you already have someone in mind.

## Step 2: Download PACER CSVs

See [pacer_csv_guide.md](pacer_csv_guide.md) for detailed instructions.

Quick version:
1. Go to https://pcl.uscourts.gov
2. Search by attorney last name, select bankruptcy courts
3. Export results as CSV
4. Save to a folder (e.g., `./csv-exports/`)

Name your files like: `api_LastName_FirstName_court_date.csv`

**Tip:** Pull at least one high-volume filer and one or two smaller firms from the same district. The smaller firms are your control group, they establish the baseline rate.

## Step 3: Run the tools

### Discharge Bar Screener

```
python screen_1328f.py --data-dir ./csv-exports --target LastName_FirstName
```

Add `--control OtherAttorney_Name` to compare against a baseline.

Add `--output-json results.json` to save structured output.

The screener will:
- Load all CSVs from the directory
- Group cases by debtor name
- Flag any Ch. 13 filing within the 1328(f) statutory window after a prior discharge
- Print a summary with case numbers, dates, gap calculations, and per-attorney stats

### Practice Report (same CSVs, same flags)

```
python practice_report.py --data-dir ./csv-exports --target LastName_FirstName
python practice_report.py --data-dir ./csv-exports --target LastName_FirstName --oneline
python practice_report.py --data-dir ./csv-exports --all --oneline
python practice_report.py --data-dir ./csv-exports --all --markdown --oneline
python practice_report.py --data-dir ./csv-exports --by-district --leaderboard --username YOUR_USERNAME
```

Same data, bigger picture. Generates a full practice profile: volume, outcomes, case duration, statutory compliance, repeat debtors. The `--oneline` flag gives you a quick summary per attorney. `--all` profiles every attorney in your CSV directory.

Add `--control OtherAttorney_Name` to get a side-by-side comparison table with deltas.

**New in v1.1.0:**
- `--markdown`, outputs Reddit-ready markdown tables you can paste directly into a comment
- `--leaderboard`, generates a paste-ready submission block for the [leaderboard](../LEADERBOARD.md)
- `--username YOUR_NAME`, tags your submission with your Reddit/GitHub username
- `--by-district`, aggregates by court instead of by attorney (great for district-level screening)

## Step 4: Review the hits

The screener flags *potential* violations based on name matching. Not every hit is real:

- **Same name, different person**, the most common false positive. Check the court and dates. If the prior case is in a completely different state with no connection, it might be a different person.
- **Very common names**, "Michael Johnson" will match across the country. The screener notes this.
- **Legitimate explanations**, rare, but possible (hardship discharge, court waiver).

To verify a specific hit, pull Document 1 (the petition) from PACER and check Question 9 on page 7-8. Q9 asks whether the debtor had prior filings. If Q9 says "No" but your data shows a prior discharge inside the window, that's either a lie or attorney negligence.

## Step 5: Share what you find

Post your aggregate results, we're building a national picture:

**From the screener:**
- District screened
- Total Ch. 13 cases loaded
- Number of f(1) hits (4-year bar)
- Number of f(2) hits (2-year bar)
- Number you hand-verified (if any)
- Any attorneys with notably high hit rates

**From the practice report:**
- Highest dismissal rate found (and caseload size)
- Highest 109(g) refiling rate
- Most repeat debtors under one attorney
- Any attorney with 5%+ 1328(f) hit rate
- The `--oneline` output for your top-volume attorneys (quick to copy/paste)

**Easiest way:** Run `--leaderboard --username YOUR_NAME` and paste the output block. It formats everything automatically.

**What NOT to share publicly:** Debtor names. Use case numbers only. Attorney names are public record and fair game.

Post in the Reddit thread, open a GitHub issue, or submit via the Google Form (link in repo).

## What Counts as a Violation

All three must be true:

1. The debtor received a discharge in a prior case
2. The new Ch. 13 was filed within the statutory window (4 years for Ch. 7/11/12 → Ch. 13, or 2 years for Ch. 13 → Ch. 13)
3. It's the same person (not just same name)

## What Doesn't Count

- **Prior case was dismissed, not discharged**, no discharge = no bar
- **Gap is outside the window**, 4 years and 1 day is legal
- **Case filed before October 17, 2005**, 1328(f) didn't exist yet (BAPCPA)
- **Different person, same name**, false positive

## Why This Matters

When an attorney files a Ch. 13 that's discharge-barred, the client pays filing fees and attorney fees for a case that can never achieve its purpose. It's three dates and subtraction, the attorney is supposed to check this before filing. The tool automates the check across thousands of cases. If an attorney has a pattern of these, that's not a mistake.

## Questions?

Open an issue on this repo or comment in the Reddit thread.
