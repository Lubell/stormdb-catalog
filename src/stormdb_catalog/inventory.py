"""Stage 2: summarize modalities per project from the extract API -> series.csv, inventory.csv."""

import json
import re
import time
from collections import defaultdict

import pandas as pd

from .extract import fetch_series, read_login_code


def summarize(project_name, series):
    by_subj = defaultdict(set)
    descs = defaultdict(set)
    for s in series:
        by_subj[s.get("subjectcode", "?")].add(s.get("modality", "?"))
        descs[s.get("modality", "?")].add(
            re.sub(r"^\d{4}_", "", s.get("seriename", ""))
        )
    mods = sorted({m for v in by_subj.values() for m in v})
    row = {
        "name": project_name,
        "modalities": "|".join(mods),
        "n_subjects_with_data": len(by_subj),
        "n_series": len(series),
    }
    for m in mods:
        row[f"n_subj_{m}"] = sum(m in v for v in by_subj.values())
    row["n_subj_MEG_and_MR"] = sum({"MEG", "MR"} <= v for v in by_subj.values())
    # a short sample of series names per modality helps tagging (e.g. 'rest', 'MPRAGE', 'emptyroom')
    row["series_names"] = json.dumps(
        {m: sorted(v)[:25] for m, v in descs.items()}, ensure_ascii=False
    )
    return row


def run(args):
    projects = pd.read_csv(args.out / "projects.csv")
    login = read_login_code(args.login_file)
    all_series, inv = [], []
    for i, name in enumerate(projects["name"], 1):
        try:
            ser = fetch_series(name, login, args.extract_url)
            for s in ser:
                s["project"] = name
            all_series += ser
            inv.append(summarize(name, ser))
        except Exception as e:  # noqa: BLE001 - record per-project failure, keep going
            inv.append({"name": name, "inventory_error": str(e)[:200]})
        if i % 25 == 0:
            print(f"  {i}/{len(projects)}")
        time.sleep(args.delay)
    keep = [
        "project",
        "subjectcode",
        "study",
        "modality",
        "serieno",
        "seriename",
        "path",
    ]
    pd.DataFrame(all_series).reindex(columns=keep).to_csv(
        args.out / "series.csv", index=False
    )
    pd.DataFrame(inv).to_csv(args.out / "inventory.csv", index=False)
    print(
        f"Wrote series.csv ({len(all_series)} series) and inventory.csv ({len(inv)} projects)"
    )
