---
name: desk-setup
description: Installs and checks the stock trader skills on this computer. Verifies Python, installs yfinance, pandas, requests and pypdf, stores the SEC contact user-agent and the default market, and tests each data source. Use before the first analysis, when the user asks to set up or install the skills, when something "doesn't work", or when another skill returns a setup error.
---

# Desk setup

The desk runs on the user's computer and downloads all data from free public sources. Nothing is bundled with the plugin.

## Steps

1. Run the check from this skill's folder:

   ```
   python scripts/check_setup.py
   ```

   It prints one line of JSON with `ready` and a list of checks. If `python` is not found, try `python3` or `py`.

2. If the `packages` check failed, ask the user whether to install the missing packages. On a yes:

   ```
   python scripts/check_setup.py --install
   ```

3. SEC filings need a contact User-Agent; SEC asks every automated client to identify itself. Ask the user for a name and an email address they are willing to send to SEC, then run:

   ```
   python scripts/check_setup.py --sec-user-agent "Their Name their@email"
   ```

   Do not make up an address or take one from elsewhere in the conversation without asking. Users who only want prices can skip this step.

4. To make Borsa Istanbul the default market, add `--market BIST`.

5. Tell the user which checks passed and, for each failure, the one thing to do about it. Do not paste the JSON.

## Notes

- Settings and cache are stored in `~/.stock-trader-skills/`. Set the `DESK_HOME` environment variable to use another folder. The plugin folder is never written to.
- If the yfinance check fails while the others pass, Yahoo is usually rate-limiting the computer for a few minutes. Wait and run the check again.
- Without internet access, `--offline` checks only Python, packages and the data folder.
