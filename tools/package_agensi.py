#!/usr/bin/env python3
"""Builds a standalone zip of one skill for marketplaces such as Agensi.

  python tools/package_agensi.py fundamentals
  python tools/package_agensi.py fundamentals technicals --out dist/agensi

In the plugin, every skill imports the shared deskcore library from
skills/desk-data/scripts. A marketplace zip holds one skill, so this script:

- copies the skill folder;
- copies only the deskcore modules the skill imports into its scripts folder
  and points the scripts there;
- adds scripts/setup.py, which checks Python and packages and saves the SEC
  contact (the plugin uses the desk-setup skill for this);
- writes requirements.txt with only the packages the copied code imports;
- appends Requirements, Setup, Network access and Files sections to SKILL.md,
  with every host the code can contact.

The result is checked: each copied .py file must compile, and the zip must
not mention desk-setup, desk-data or a sibling skill folder.
"""
import argparse
import ast
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
DESKCORE = SKILLS / "desk-data" / "scripts" / "deskcore"
# Skills that only make sense inside the plugin: the setup helper, the data
# layer itself, and committee, which runs the other skills.
NOT_STANDALONE = {"desk-setup", "desk-data", "committee"}
THIRD_PARTY = {"yfinance", "pandas", "requests", "pypdf"}
# yfinance talks to these hosts; they are not written in our code.
YFINANCE_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com", "fc.yahoo.com", "guce.yahoo.com"]
HOST_PURPOSE = {
    "finance.yahoo.com": "prices, statements and company profile (through yfinance)",
    "fc.yahoo.com": "session cookie that yfinance needs",
    "guce.yahoo.com": "consent page that yfinance may pass through",
    "www.sec.gov": "SEC ticker list and filing documents",
    "data.sec.gov": "SEC filings index and XBRL financial data",
    "fred.stlouisfed.org": "FRED macro series",
    "data.bis.org": "BIS consumer price data",
    "stats.bis.org": "BIS consumer price data",
    "en.wikipedia.org": "company history",
    "tr.wikipedia.org": "company history for Turkish companies",
    "query.wikidata.org": "matching a ticker to its Wikipedia page",
    "news.google.com": "news headlines (RSS)",
    "api.nasdaq.com": "earnings calendar",
}

SETUP_PY = '''#!/usr/bin/env python3
"""Checks that this skill can run and saves the SEC contact.

  python scripts/setup.py
  python scripts/setup.py --install
  python scripts/setup.py --sec-user-agent "Jane Doe jane@example.com"
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
PACKAGES = {packages}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--install", action="store_true", help="pip-install missing packages")
    p.add_argument("--sec-user-agent", help='"Your Name your@email", sent to SEC with each request')
    a = p.parse_args()
    out = {{"python": sys.version.split()[0]}}
    if sys.version_info < (3, 9):
        out.update(ready=False, fix="Python 3.9 or newer is needed.")
        print(json.dumps(out))
        return 1
    missing = [m for m in PACKAGES if importlib.util.find_spec(m) is None]
    if missing and a.install:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *missing], check=False)
        missing = [m for m in PACKAGES if importlib.util.find_spec(m) is None]
    if missing:
        out.update(ready=False, missing=missing,
                   fix=sys.executable + " -m pip install " + " ".join(missing))
        print(json.dumps(out))
        return 1
    from deskcore import config
    cfg = config.save({{"sec_user_agent": a.sec_user_agent.strip()}}) if a.sec_user_agent else config.load()
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out.update(ready=True, data_folder=str(config.HOME),
               sec_user_agent="set" if "@" in cfg.get("sec_user_agent", "") else "not set")
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def deskcore_imports(source):
    """Names of deskcore modules a file imports, absolute or relative."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom):
            continue
        mod = node.module or ""
        if node.level == 0 and mod == "deskcore" or node.level == 1 and not mod:
            names.update(a.name for a in node.names)
        elif node.level == 0 and mod.startswith("deskcore."):
            names.add(mod.split(".")[1])
        elif node.level == 1 and mod:
            names.add(mod.split(".")[0])
    return {n for n in names if (DESKCORE / f"{n}.py").exists()}


def third_party(source):
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found & THIRD_PARTY


def pinned_requirements(packages):
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    pins = {re.split(r"[<>=!~ ]", l, maxsplit=1)[0].strip(): l.strip() for l in lines if l.strip()}
    return [pins.get(p, p) for p in sorted(packages)]


def hosts_in(source):
    return set(re.findall(r"https?://([a-zA-Z0-9.-]+\.[a-z]{2,})", source))


def rewrite_script(text):
    """Point the sys.path line at the bundled deskcore and fix setup hints."""
    text = re.sub(r'sys\.path\.insert\(0, [^\n]*desk-data[^\n]*\)\n',
                  'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n', text)
    return re.sub(r"([Rr])un (?:the )?desk-setup(?: skill)?",
                  lambda m: m.group(1) + "un python scripts/setup.py", text)


def skill_md_extra(packages, hosts):
    host_lines = []
    for h in sorted(hosts):
        purpose = next((v for k, v in HOST_PURPOSE.items() if h == k or h.endswith("." + k)), "data download")
        host_lines.append(f"- `{h}`: {purpose}")
    sec_note = ""
    if any(h.endswith("sec.gov") for h in hosts):
        sec_note = ("\nSEC asks every automated client to name a contact. Ask the user for a name and an email "
                    "address they are willing to send to SEC, then run "
                    "`python scripts/setup.py --sec-user-agent \"Their Name their@email\"`. "
                    "Do not make one up. Without it, the parts that read SEC filings are skipped.\n")
    return f"""
## Requirements

- Python 3.9 or newer
- Python packages: {", ".join(packages)} (listed in `requirements.txt`)
- Internet access to the hosts below

## Setup

Run `python scripts/setup.py` from this skill's folder once. If it reports missing packages, ask the user before running `python scripts/setup.py --install`.
{sec_note}
## Network access

The scripts only read public data. They send no user data anywhere except the SEC contact above, which SEC requires. Hosts contacted:

{chr(10).join(host_lines)}

## Files written

Settings and a download cache go to `~/.stock-trader-skills/` (set `DESK_HOME` to use another folder). Nothing else on the computer is changed.
"""


def build(skill, out_dir):
    src = SKILLS / skill
    if skill in NOT_STANDALONE or not (src / "SKILL.md").exists():
        raise SystemExit(f"{skill}: not a standalone skill")
    stage = out_dir / skill
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(src, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    scripts = sorted((stage / "scripts").glob("*.py"))
    need, packages, hosts = set(), set(), set()
    for f in scripts:
        text = f.read_text(encoding="utf-8")
        need |= deskcore_imports(text)
        packages |= third_party(text)
        hosts |= hosts_in(text)
        f.write_text(rewrite_script(text), encoding="utf-8")

    # Follow imports inside deskcore until nothing new turns up.
    todo, mods = list(need), {"__init__"}
    while todo:
        m = todo.pop()
        if m in mods:
            continue
        mods.add(m)
        todo.extend(deskcore_imports((DESKCORE / f"{m}.py").read_text(encoding="utf-8")) - mods)
    (stage / "scripts" / "deskcore").mkdir()
    for m in sorted(mods):
        text = (DESKCORE / f"{m}.py").read_text(encoding="utf-8")
        packages |= third_party(text)
        hosts |= hosts_in(text)
        (stage / "scripts" / "deskcore" / f"{m}.py").write_text(rewrite_script(text), encoding="utf-8")
    if "yfinance" in packages:
        hosts |= set(YFINANCE_HOSTS)
    # Hosts that only appear in comments or docstrings still count: better to over-declare.

    (stage / "scripts" / "setup.py").write_text(
        SETUP_PY.format(packages=sorted(packages)), encoding="utf-8")
    (stage / "requirements.txt").write_text("\n".join(pinned_requirements(packages)) + "\n", encoding="utf-8")

    md = (stage / "SKILL.md").read_text(encoding="utf-8")
    md = md.replace("the desk-setup skill should run first",
                    "`python scripts/setup.py` should run first (see Setup)")
    (stage / "SKILL.md").write_text(md.rstrip() + "\n" + skill_md_extra(sorted(packages), hosts), encoding="utf-8")
    shutil.copy(ROOT / "LICENSE", stage / "LICENSE")

    problems = check(stage, skill)
    zip_path = out_dir / f"{skill}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(out_dir).as_posix())
    return {"skill": skill, "zip": str(zip_path), "deskcore_modules": sorted(mods - {"__init__"}),
            "packages": sorted(packages), "hosts": sorted(hosts), "problems": problems}


def check(stage, skill):
    problems = []
    siblings = {p.name for p in SKILLS.iterdir() if p.is_dir()} - {skill}
    for f in stage.rglob("*"):
        if not f.is_file() or f.suffix not in {".py", ".md", ".txt"}:
            continue
        text = f.read_text(encoding="utf-8")
        if f.suffix == ".py":
            try:
                compile(text, str(f), "exec")
            except SyntaxError as e:
                problems.append(f"{f.name}: {e}")
        for word in ["desk-setup", "desk-data"]:
            if word in text:
                problems.append(f"{f.relative_to(stage)} mentions {word}")
        if f.name == "SKILL.md":
            for s in sorted(siblings):
                if re.search(rf"\b{re.escape(s)} skill\b", text):
                    problems.append(f"SKILL.md refers to the {s} skill, which is not in this zip")
    return problems


def main():
    p = argparse.ArgumentParser()
    p.add_argument("skills", nargs="+")
    p.add_argument("--out", default=str(ROOT / "dist" / "agensi"))
    a = p.parse_args()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = False
    for skill in a.skills:
        r = build(skill, out_dir)
        failed |= bool(r["problems"])
        print(r)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
