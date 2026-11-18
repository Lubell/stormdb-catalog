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


# Fallback names for list columns, used when the page has no <th> header row.
# Positions confirmed on the live page (2026-11-18); the others are unlabeled.
LIST_COLUMN_FALLBACK = {
    0: "Id",
    1: "Name",
    2: "Responsible",
    3: "Institution",
    4: "#Subjects",
    5: "Start",
    6: "End",
    12: "Latest activity",
    13: "Personal data",
    14: "Approvals",
}


def parse_list_header(html):
    """Column labels from the first <th> row with at least 7 cells, else []."""
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        ths = [th.get_text(" ", strip=True) for th in tr.find_all("th")]
        if len(ths) >= 7:
            return ths
    return []


def _label(header, i):
    if i < len(header) and header[i]:
        return header[i]
    return LIST_COLUMN_FALLBACK.get(i, f"column {i + 1}")


def compare_project_lists(stored, current, header=()):
    """Diff two parsed project lists (dicts with project_id, name, raw_cells).

    Returns {"new": [rows], "removed": [rows], "changed": [(row, [(label, old, new)])]},
    matching projects by project_id (the name can change, and it is the join key).
    """
    old = {int(r["project_id"]): r for r in stored}
    new = {int(r["project_id"]): r for r in current}
    changed = []
    for pid in sorted(old.keys() & new.keys()):
        a, b = json.loads(old[pid]["raw_cells"]), json.loads(new[pid]["raw_cells"])
        diffs = [
            (_label(header, i), x, y)
            for i, (x, y) in enumerate(
                zip(a + [""] * (len(b) - len(a)), b + [""] * (len(a) - len(b)))
            )
            if x != y
        ]
        if diffs:
            changed.append((new[pid], diffs))
    return {
        "new": [new[pid] for pid in sorted(new.keys() - old.keys())],
        "removed": [old[pid] for pid in sorted(old.keys() - new.keys())],
        "changed": changed,
    }


def format_changes(diff):
    lines = []
    for title, key in (("New projects", "new"), ("Removed from the list", "removed")):
        if diff[key]:
            lines.append(f"{title} ({len(diff[key])}):")
            lines += [f"  {r['project_id']:>4}  {r['name']}" for r in diff[key]]
    if diff["changed"]:
        lines.append(f"Changed ({len(diff['changed'])}):")
        for r, diffs in diff["changed"]:
            lines.append(f"  {r['project_id']:>4}  {r['name']}")
            lines += [
                f"          {label}: {old!r} -> {new!r}" for label, old, new in diffs
            ]
    return "\n".join(lines) or "No changes in the project list."


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


def fetch_info(s, p):
    """Add a project's info-page fields to the list row p (in place); errors go to info_error."""
    try:
        ri = s.get(INFO_URL.format(pid=p["project_id"]), timeout=60)
        ri.raise_for_status()
        if is_login_page(ri.text):
            raise RuntimeError("got the login page (session expired?)")
        p.update(parse_project_info(ri.text))
    except Exception as e:  # noqa: BLE001 - record per-project failure, keep going
        p["info_error"] = str(e)
    return p


def fetch_project_list(s, out):
    """Fetch and parse the admin project list; returns (rows, header)."""
    r = s.get(LIST_URL, timeout=60)
    r.raise_for_status()
    if is_login_page(r.text):
        sys.exit(
            "StormDb returned its login page: the cookie was not accepted. Copy a fresh "
            "Cookie header (PHPSESSID=...) from a logged-in tab."
        )
    projects = parse_project_list(r.text)
    if not projects:
        (out / "listprojects_debug.html").write_text(r.text)
        sys.exit(
            "Parsed 0 projects; saved listprojects_debug.html for inspection (HTML layout changed?)."
        )
    return projects, parse_list_header(r.text)


def run_changes(args):
    """Read-only: compare the live project list with the stored projects.csv."""
    path = args.out / "projects.csv"
    if not path.exists():
        sys.exit(f"{path} not found; run the projects stage first.")
    stored = pd.read_csv(path, usecols=["project_id", "name", "raw_cells"]).to_dict(
        "records"
    )
    current, header = fetch_project_list(_session(args.cookie), args.out)
    print(format_changes(compare_project_lists(stored, current, header)))


def run(args):
    s = _session(args.cookie)
    projects, _ = fetch_project_list(s, args.out)
    print(f"{len(projects)} projects in list; fetching info pages...")
    for i, p in enumerate(projects, 1):
        fetch_info(s, p)
        if i % 50 == 0:
            print(f"  {i}/{len(projects)}")
        time.sleep(args.delay)
    df = pd.DataFrame(projects)
    df.to_csv(args.out / "projects.csv", index=False)
    print(
        f"Wrote {args.out / 'projects.csv'} ({len(df)} rows, "
        f"{(df.get('description', pd.Series(dtype=str)).fillna('') != '').sum()} with descriptions)"
    )
