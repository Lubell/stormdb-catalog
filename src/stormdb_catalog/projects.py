"""Stage 1: scrape the admin project list and per-project info pages -> projects.csv."""

import json
import re
import sys
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .config import INFO_URL, LIST_URL


def clean_cookie(cookie):
    """Normalize a pasted Cookie header value; exit with a hint if it can't be one."""
    c = (cookie or "").strip()
    if c.lower().startswith("cookie:"):
        c = c[len("cookie:") :].strip()
    if not c:
        sys.exit(
            "Need --cookie (or STORMDB_COOKIE): copy the Cookie header from a logged-in StormDb tab."
        )
    if any(not ch.isprintable() for ch in c) or "=" not in c:
        sys.exit(
            "The cookie doesn't look like a Cookie header (expected e.g. PHPSESSID=...; "
            "it is missing '=' or contains control characters such as arrow-key presses)."
        )
    return c


def _session(cookie):
    s = requests.Session()
    # cookie is the raw "Cookie" header copied from the browser dev tools
    s.headers["Cookie"] = clean_cookie(cookie)
    return s


def is_login_page(html):
    return bool(re.search(r"<title>\s*Login\s*</title>", html, re.IGNORECASE))


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
                "raw_cells": json.dumps(cells, ensure_ascii=False),
            }
        )
    return rows


def _mb(text):
    m = re.match(r"\s*([\d,.]+)\s*Mb", text)
    return float(m.group(1).replace(",", "")) if m else None


def parse_project_info(html):
    """Pull fields from the "Project information" panel of a projectinfo page.

    Layout (seen on the live server, 2026-11): a table of "Label: | value"
    rows (Id, Name, Responsible, Responsible Institution, Data, Start date,
    End date, Privileges), then full-width (colspan=2) rows holding either an
    alert (e.g. "this project is marked as expired!") or the free-text
    description; a second table holds "Disk usage <kind>: N Mb (...)".
    Fields already in the project list (id, name, dates, ...) are not repeated.
    """
    soup = BeautifulSoup(html, "html.parser")
    out = {"description": "", "expired": False}
    title = soup.find(
        lambda t: (
            t.name in ("h3", "h2") and t.get_text(strip=True) == "Project information"
        )
    )
    panel = title.find_parent(class_="panel") if title else None
    for tr in panel.find_all("tr") if panel else []:
        tds = tr.find_all("td", recursive=False)
        if len(tds) == 1:
            if tds[0].find(class_="alert"):
                if "expired" in tds[0].get_text(" ", strip=True).lower():
                    out["expired"] = True
            else:
                text = "\n".join(
                    line.strip()
                    for line in tds[0].get_text().splitlines()
                    if line.strip()
                )
                out["description"] = "\n".join(filter(None, [out["description"], text]))
        elif len(tds) == 2:
            label = tds[0].get_text(" ", strip=True)
            value = tds[1].get_text(" ", strip=True)
            if label == "Data:":
                out["data_type"] = value
            elif label == "Privileges:":
                for kind in ("Filesystem", "Database"):
                    m = re.search(rf"{kind}:\s*(\d+)", value)
                    out[f"n_users_{kind.lower()}"] = int(m.group(1)) if m else None
            elif m := re.fullmatch(r"Disk usage (\w+):", label):
                out[f"disk_{m.group(1)}_mb"] = _mb(value)
    m = re.search(r"Documents\s*\((\d+)\)", soup.get_text(" "))
    out["n_documents"] = int(m.group(1)) if m else None
    return out


def run(args):
    s = _session(args.cookie)
    r = s.get(LIST_URL, timeout=60)
    r.raise_for_status()
    if is_login_page(r.text):
        sys.exit(
            "StormDb returned its login page: the cookie was not accepted. Copy a fresh "
            "Cookie header (PHPSESSID=...) from a logged-in tab."
        )
    projects = parse_project_list(r.text)
    if not projects:
        (args.out / "listprojects_debug.html").write_text(r.text)
        sys.exit(
            "Parsed 0 projects; saved listprojects_debug.html for inspection (HTML layout changed?)."
        )
    print(f"{len(projects)} projects in list; fetching info pages...")
    for i, p in enumerate(projects, 1):
        try:
            ri = s.get(INFO_URL.format(pid=p["project_id"]), timeout=60)
            ri.raise_for_status()
            if is_login_page(ri.text):
                raise RuntimeError("got the login page (session expired?)")
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
