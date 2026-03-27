# Setup Walkthrough, Step by Step

**PRIVATE, do NOT copy this file to the public repo.**

---

## Part 1: ProtonMail (anonymous email)

1. Go to `https://proton.me/mail`
2. Click **"Create a free account"**
3. Pick the free plan
4. **Username:** pick something neutral (e.g., `bkscreentools`, `pacerutils`, `dischargescreen`)
5. **Password:** use something strong, save it somewhere
6. It may ask for a verification method (CAPTCHA, email, or SMS). CAPTCHA is most anonymous.
7. Skip the display name / recovery email steps, leave blank
8. You now have `yourname@proton.me`
9. **Write down the email + password**, you'll need it for GitHub and Reddit

---

## Part 2: GitHub Account

1. Go to `https://github.com/signup`
2. Enter your ProtonMail address
3. Create a password
4. Pick a username, **different from the email prefix and from your Reddit username**
   - Ideas: `bk-screen-tools`, `discharge-screen`, `1328f-tools`, `pacer-screen`
5. Complete the CAPTCHA / email verification (check ProtonMail inbox)
6. Skip all the onboarding questions ("What kind of work do you do" etc.)
7. **Do NOT** add a profile photo, bio, location, or links
8. You're now signed in to GitHub

---

## Part 3: Create the Repo on GitHub

1. Click the **+** icon (top right) → **"New repository"**
2. Fill in:
   - **Repository name:** `1328f-screen`
   - **Description:** `Open-source toolkit for screening PACER data for Section 1328(f) discharge bar violations`
   - **Public** (not Private)
   - **Do NOT check** "Add a README file"
   - **Do NOT check** "Add .gitignore"
   - **Do NOT check** "Choose a license"
   - (We're pushing all of this from local, checking any of these creates conflicts)
3. Click **"Create repository"**
4. You'll see a page with "Quick setup" and some git commands, leave this open
5. **Copy the HTTPS URL**, it'll look like `https://github.com/YOURUSERNAME/1328f-screen.git`

---

## Part 4: Push the Code

Come back to me with the GitHub username and I'll run the commands. Or do it yourself:

```bash
cd /tmp/1328f-screen

# Fix the clone URL in README
sed -i 's/YOUR_USERNAME/YOURUSERNAME/g' README.md

# Initialize and push
git init
git add -A
git commit -m "Initial release: 1328(f) discharge bar screening toolkit"
git branch -M main
git remote add origin https://github.com/YOURUSERNAME/1328f-screen.git
git push -u origin main
```

It will ask for your GitHub username and a **personal access token** (NOT your password):
- Go to GitHub → Settings (click your avatar top right) → Developer settings (bottom of left sidebar) → Personal access tokens → Tokens (classic)
- Click "Generate new token (classic)"
- Note: `push token`
- Expiration: 30 days is fine
- Check the `repo` scope
- Click "Generate token"
- **Copy the token** (starts with `ghp_...`), this is your password for the git push
- Paste it when git asks for password

After push, refresh the GitHub repo page, you should see all your files.

---

## Part 5: Reddit Account

1. Go to `https://www.reddit.com/register`
2. Use your ProtonMail address (or a different one if you want more separation)
3. Pick a username, **different from GitHub username**
   - Ideas: `helpful_coder_2026`, `data_side_projects`, `stdlib_only`, something that reads like a Python dev
4. Complete setup, skip avatar/interests
5. **Do NOT post yet**, spend 3-7 days commenting on r/Python posts first
   - Sort by New, find questions you can answer about Python stdlib, CSV parsing, argparse, etc.
   - Be genuinely helpful. Build a comment history that looks like a real developer.
   - Aim for ~20+ comment karma before posting

---

## Part 6: Post to r/Python (first wave)

1. Go to `https://www.reddit.com/r/Python/`
2. Click "Create Post"
3. Title: `I used Python's standard library to find hundreds of cases where people paid lawyers for something that was arithmetically impossible`
4. Body: copy from `REDDIT_POST_RPYTHON.md` (the section between the `---` markers)
5. Replace `[link]` with your actual GitHub URL
6. Flair: "I Made This" if available
7. Post on a Tuesday, Wednesday, or Thursday morning (US time)

---

## Part 7: Post to r/bankruptcy (second wave, 1-2 weeks later)

1. Go to `https://www.reddit.com/r/bankruptcy/`
2. Click "Create Post"
3. Title: `I built an open-source tool to screen PACER data for Section 1328(f) discharge bar violations`
4. Body: copy from `REDDIT_POST_DRAFT.md` (the section between the `---` markers)
5. Replace `[GitHub link here]` with your actual GitHub URL

---

## OPSEC Reminders

- Never mention any specific firm, attorney, or case number in public
- Never connect these accounts to your real identity
- If asked "how did you find this": "I was researching bankruptcy outcomes and noticed the pattern"
- If asked about specific results: "The tool is general-purpose, run it on your own district"
- Developer voice at all times on r/Python. Slightly more legal-aware on r/bankruptcy but still "data analyst" not "debtor"
