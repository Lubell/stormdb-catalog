"""Incremental update: refetch only projects whose project-list row changed.

1. Fetch the project list (one request) and diff it against projects.csv
   (see projects.compare_project_lists).
2. New and changed projects: refetch the info page and the series list.
   Removed projects: drop their rows. Unchanged projects keep their stored rows.
   --all-info also refetches every info page (about 2 min) to catch edits that
   don't show in the list row, e.g. a description; series are still refetched
   only for list changes.
3. Rewrite projects.csv, series.csv and inventory.csv, then rerun keyword tagging
   (local and fast) unless --no-tag.
"""

import os
import sys
import time
from types import SimpleNamespace

import pandas as pd

from . import tagging
from .extract import read_login_code
from .inventory import SERIES_COLUMNS, inventory_project
from .projects import (
    _session,
    compare_project_lists,
    fetch_info,
    fetch_project_list,
    format_changes,
)

# info-page fields compared to report edits found only by --all-info
INFO_FIELDS = ["description", "expired", "data_type"]


def _write_csv(df, path):
    """Write via a temp file so an interrupted run never leaves a half-written CSV."""
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


def _same(a, b):
    return (pd.isna(a) and pd.isna(b)) or str(a) == str(b)


def run(args):
    out = args.out
    paths = {f: out / f"{f}.csv" for f in ("projects", "series", "inventory")}
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        sys.exit(
            f"Missing {', '.join(missing)}; run the projects and inventory stages once first."
        )
    stored = pd.read_csv(paths["projects"])
    stored_by_id = {int(r["project_id"]): r for r in stored.to_dict("records")}

    s = _session(args.cookie)
    current, header = fetch_project_list(s, out)
    diff = compare_project_lists(stored_by_id.values(), current, header)
    print(format_changes(diff))

    series_ids = {r["project_id"] for r in diff["new"]} | {
        r["project_id"] for r, _ in diff["changed"]
    }
    info_ids = {r["project_id"] for r in current} if args.all_info else series_ids
    if not info_ids and not diff["removed"]:
        print("Catalog is up to date.")
        return

    # projects.csv: fresh list row + info page for refetched projects, stored row otherwise
    print(f"Fetching {len(info_ids)} info page(s)...")
    rows, info_only = [], []
    for p in current:
        pid = p["project_id"]
        if pid not in info_ids:
            rows.append(stored_by_id[pid])
            continue
        fetch_info(s, p)
        time.sleep(args.delay)
        old = stored_by_id.get(pid)
        if (
            pid not in series_ids
            and old is not None
            and any(not _same(old.get(f), p.get(f)) for f in INFO_FIELDS)
        ):
            info_only.append(p)
        rows.append(p)
    if info_only:
        print(f"Info page changed for {len(info_only)} project(s) with no list change:")
        print("\n".join(f"  {p['project_id']:>4}  {p['name']}" for p in info_only))
    projects = pd.DataFrame(rows)
    projects = projects.reindex(
        columns=list(stored.columns)
        + [c for c in projects.columns if c not in stored.columns]
    )

    # series.csv / inventory.csv: drop old rows (by stored name; names can change), add fresh ones
    stale = {stored_by_id[r["project_id"]]["name"] for r, _ in diff["changed"]}
    stale |= {r["name"] for r in diff["removed"]}
    series = pd.read_csv(paths["series"], dtype=str)  # str keeps e.g. serieno "001"
    inventory = pd.read_csv(paths["inventory"])
    series = series[~series["project"].isin(stale)]
    inventory = inventory[~inventory["name"].isin(stale)]
    new_series, new_inv = [], []
    if series_ids:
        print(f"Fetching series for {len(series_ids)} project(s)...")
        login = read_login_code(args.login_file)
        for p in current:
            if p["project_id"] in series_ids:
                ser, row = inventory_project(p["name"], login, args.extract_url)
                new_series += ser
                new_inv.append(row)
                time.sleep(args.delay)
    series = pd.concat(
        [series, pd.DataFrame(new_series, dtype=str).reindex(columns=SERIES_COLUMNS)],
        ignore_index=True,
    )
    inventory = pd.concat([inventory, pd.DataFrame(new_inv)], ignore_index=True)
    order = {name: i for i, name in enumerate(projects["name"])}
    inventory = inventory.sort_values("name", key=lambda c: c.map(order), kind="stable")

    _write_csv(projects, paths["projects"])
    _write_csv(series, paths["series"])
    _write_csv(inventory, paths["inventory"])
    errors = sum(
        "inventory_error" in r and pd.notna(r["inventory_error"]) for r in new_inv
    )
    print(
        f"Updated catalog: {len(projects)} projects, {len(series)} series"
        + (f" ({errors} inventory error(s))" if errors else "")
    )
    if not args.no_tag:
        tagging.run(SimpleNamespace(out=out, method="keywords", model=None))
