---
name: desk-setup
description: Sets up and diagnoses the AI equity research desk on this computer - checks Python, installs the free data packages (yfinance, pandas, requests), saves the SEC contact user-agent and default market, and tests each free data source. Use on first use of any desk skill, when the user says "set up the desk", "install", "it doesn't work", or when another desk skill returns a setup error.
---

# Desk setup

You get the desk ready to run on the user's own computer. All data is fetched from free public sources by the user's machine; nothing ships with the pack.

## Steps

1. Run the check (paths are relative to this skill's folder):

   ```
   python scripts/check_setup.py
   ```

   It prints one JSON line: `ready` plus a list of checks.

2. If `packages` failed, ask the user before installing, then run:

   ```
   python scripts/check_setup.py --install
   ```

   If `python` is not found, try `python3` or `py`.

3. SEC filings (US companies) need a contact User-Agent. SEC's own rules ask every client to identify itself. Ask the user for their name and an email they are happy to send to SEC, then:

   ```
   python scripts/check_setup.py --sec-user-agent "Their Name their@email"
   ```

   Never invent an email and never reuse one from elsewhere in the conversation without asking. Skip this if the user only wants prices.

4. Optional: `--market BIST` makes Borsa Istanbul the default market (prices only for now).

5. Report the result in a short checklist: what works, what does not, and the one fix for each failure. Do not paste the raw JSON.

## Notes

- Settings and cache live in `~/.ai-equity-desk/` (override with the `DESK_HOME` environment variable). Nothing is written into the plugin folder.
- yfinance is free and unofficial. If it fails while other checks pass, it is usually a temporary Yahoo rate limit: wait a few minutes and retry.
- Network checks need internet access. In environments that block network access, run with `--offline` to check only the local setup.
