# PulseBoard — Custom Daily News & Research Dashboard

A clean, responsive, single-file daily dashboard for morning and evening briefings, featuring visual news stories, research paper summaries, day-ahead schedules, morning/evening routines, and secular spiritual teachings.

## Files

- [index.html](file:///Users/arnabacharya/Documents/PulseApp/index.html) — Standalone application. Double-click in Finder to open in Safari, Chrome, or any browser.

---

## 1. Reaching the Dashboard from Your Phone

Right now, the app is a local file on your Mac at:
`file:///Users/arnabacharya/Documents/PulseApp/index.html`

Phones cannot open Mac `file:///` paths directly, but you have two simple ways to access it:

### Option A: Local Wi-Fi (Instant, 30 Seconds, No Cloud Setup)

1. Open **Terminal** on your Mac.
2. Run this command:
   ```bash
   cd ~/Documents/PulseApp && python3 -m http.server 8080
   ```
3. Make sure your phone is connected to the same home Wi-Fi network.
4. On your phone's browser (Safari or Chrome), go to:
   ```text
   http://192.168.1.10:8080
   ```
5. **Tip**: In Safari on iPhone, tap the **Share** button (box with arrow pointing up) and select **"Add to Home Screen"**. It will appear as a standalone app icon that launches in full-screen mode without browser toolbars.

### Option B: Free Cloud Hosting (Accessible Anywhere on 5G/Cellular)

To open it from anywhere in the world without keeping your Mac running:
- **GitHub Pages (Free)**: Create a free GitHub repository, drag and drop `index.html`, and turn on GitHub Pages in the repo settings. Your URL will be `https://<username>.github.io/<repo-name>/`.
- **Vercel / Netlify (Free)**: Drop the `PulseApp` folder into [vercel.com](https://vercel.com) or [netlify.com](https://netlify.com) for an instant HTTPS link (e.g. `https://arnab-pulseboard.vercel.app`).

---

## 2. How the Dashboard Updates Everyday

### Current In-App Architecture
- **Time Detection**: Every time you open or refresh the app, it checks the local device time and switches between the **Morning Edition** (5 AM – 6 PM) and **Night Edition** (6 PM – 5 AM).
- **Persistence (`localStorage`)**: Your routine check-offs, bookmarks, saved papers, and custom priority goals stay preserved across sessions.

### Adding Automated Daily News & Paper Feeds (Next Step)
To have fresh papers and news pulled automatically every morning and night:
1. **Client-Side Live Fetching (Browser APIs)**:
   - We connect standard public APIs directly inside JavaScript:
     - **arXiv API**: Free public XML/JSON feed that pulls the latest scientific preprints (e.g., machine learning, quantum physics, biology) published in the last 24 hours.
     - **Hacker News / Techmeme / Open News APIs**: Pulls the top-ranked tech and climate stories.
   - When you open the dashboard on your phone at 7 AM or 9 PM, it runs `fetch()` in the background and populates that day's fresh articles on the fly.
2. **Automated Daily Pipeline (GitHub Action Cron)**:
   - A free background script runs at 6:30 AM and 8:30 PM.
   - It fetches the latest abstracts and headlines, generates 1-sentence summaries, selects the daily Buddhist/secular teaching, and writes a fresh `daily_data.json` file automatically.
