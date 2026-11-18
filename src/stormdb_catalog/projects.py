"""Stage 1: scrape the admin project list and per-project info pages -> projects.csv."""

import json
import re
import sys
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .config import INFO_URL, LIST_URL


def _session(cookie):
    s = requests.Session()
    # cookie is the raw "Cookie" header copied from the browser dev tools
    s.headers["Cookie"] = cookie
    return s


def parse_project_list(html):
    """Return list of dicts from the admin listprojects table.

    Expected column order (from the UI): id, name, responsible, institution,
    #subjects, start, end, ... latest activity, human data, approvals.
    Rows are kept if the first cell is a numeric project id.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < 7 or not cells[0].isdigit():
            continue
        date_cells = [c for c in cells if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c)]
        rows.append(
            {
                "project_id": int(cells[0]),
                "name": cells[1],
                "responsible": cells[2],
                "institution": cells[3],
                "n_subjects": pd.to_numeric(cells[4], errors="coerce"),
                "start_date": date_cells[0] if len(date_cells) > 0 else "",
                "end_date": date_cells[1] if len(date_cells) > 1 else "",
                "latest_activity": date_cells[-1] if len(date_cells) > 2 else "",
                "expired_style": "grey" in (tr.get("class") or [])
                or "inactive" in str(tr.get("style", "")),
                "raw_cells": json.dumps(cells, ensure_ascii=False),
            }
        )
    return rows


def parse_project_info(html):
    """Pull labelled fields (Description, Human data, Anonymized, ...) from a projectinfo page."""
    soup = BeautifulSoup(html, "html.parser")
    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    wanted = {
        "Description:": "description",
        "Human data:": "human_data",
        "Anonymized:": "anonymized",
        "Expired:": "expired",
        "Missing approvals:": "missing_approvals",
        "Journal no used in ESDH:": "esdh_journal",
    }
    out = {}
    for i, line in enumerate(lines):
        if line in wanted and i + 1 < len(lines):
            nxt = lines[i + 1]
            out[wanted[line]] = "" if nxt in wanted else nxt
    m = re.search(r"Documents\s*\((\d+)\)", soup.get_text(" "))
    out["n_documents"] = int(m.group(1)) if m else None
    return out


def run(args):
    if not args.cookie:
        sys.exit(
            "Need --cookie (or STORMDB_COOKIE): copy the Cookie header from a logged-in StormDb tab."
        )
    s = _session(args.cookie)
    r = s.get(LIST_URL, timeout=60)
    r.raise_for_status()
    projects = parse_project_list(r.text)
    if not projects:
        (args.out / "listprojects_debug.html").write_text(r.text)
        sys.exit(
            "Parsed 0 projects; saved listprojects_debug.html for inspection (login or HTML layout?)."
        )
    print(f"{len(projects)} projects in list; fetching info pages...")
    for i, p in enumerate(projects, 1):
        try:
            ri = s.get(INFO_URL.format(pid=p["project_id"]), timeout=60)
            ri.raise_for_status()
            p.update(parse_project_info(ri.text))
        except Exception as e:  # noqa: BLE001 - record per-project failure, keep going
            p["info_error"] = str(e)
        if i % 50 == 0:
            print(f"  {i}/{len(projects)}")
        time.sleep(args.delay)
    df = pd.DataFrame(projects)
    df.to_csv(args.out / "projects.csv", index=False)
    print(
        f"Wrote {args.out / 'projects.csv'} ({len(df)} rows, "
        f"{(df.get('description', pd.Series(dtype=str)).fillna('') != '').sum()} with descriptions)"
    )
