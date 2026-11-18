"""Stage 4: join the stage outputs and filter."""

import json
import shutil
import textwrap

import pandas as pd

# StormDb's own spelling ("Anomymized") is kept in the data; shortened for display
DATA_TYPE_SHORT = {
    "Human (Anomymized)": "anonymized",
    "Human (Anonymized)": "anonymized",
    "Human (Sensitive)": "sensitive",
    "Animal": "animal",
}

SAVE_COLUMNS = [
    "project_id",
    "name",
    "responsible",
    "start_date",
    "end_date",
    "expired",
    "data_type",
    "n_subjects",
    "modalities",
    "n_subj_MEG_and_MR",
    "domain",
    "description",
]


def load_catalog(out):
    df = pd.read_csv(out / "projects.csv")
    for f in ["inventory.csv", "tags.csv"]:
        if (out / f).exists():
            df = df.merge(pd.read_csv(out / f), on="name", how="left")
    return df


def run(args):
    df = load_catalog(args.out)
    mask = pd.Series(True, index=df.index)
    if args.domain:
        mask &= df["domain"].fillna("").str.contains(args.domain, case=False)
    for m in args.has or []:
        mask &= (
            df["modalities"].fillna("").str.split("|").apply(lambda xs, m=m: m in xs)
        )
    if args.both_meg_mr:
        mask &= df["n_subj_MEG_and_MR"].fillna(0) >= args.both_meg_mr
    if args.text:
        mask &= (
            df["name"].fillna("") + " " + df.get("description", "").fillna("")
        ).str.contains(args.text, case=False, regex=True)
    res = df.loc[mask].sort_values("project_id")
    width = args.width or shutil.get_terminal_size((100, 24)).columns
    if args.table:
        print(format_table(res, width))
    else:
        print("\n\n".join(format_card(r, width, args.full) for _, r in res.iterrows()))
    print(f"\n{len(res)} projects match")
    if args.save:
        res[[c for c in SAVE_COLUMNS if c in res]].to_csv(args.save, index=False)


def _get(r, col, default=""):
    v = r.get(col, default)
    return default if pd.isna(v) else v


def _int(r, col):
    v = _get(r, col, None)
    return "?" if v is None or v == "" else str(int(v))


def _tags(r):
    raw = _get(r, "domain")
    try:
        tags = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return str(raw)
    return ", ".join(tags) if isinstance(tags, list) else str(tags)


def _modalities(r):
    return ", ".join(m for m in str(_get(r, "modalities")).split("|") if m) or "none"


def format_card(r, width, full=False):
    """A few lines per project: header, people/size, data, wrapped description."""
    indent = "    "
    head = f"{_int(r, 'project_id'):>3}  {_get(r, 'name')}"
    if _get(r, "expired", False) is True:
        head += "  [expired]"
    facts = [
        str(_get(r, "responsible")) or "?",
        str(_get(r, "start_date")) or "?",
        f"{_int(r, 'n_subjects')} subjects",
    ]
    if _get(r, "n_subj_MEG_and_MR", 0):
        facts[-1] += f" ({_int(r, 'n_subj_MEG_and_MR')} MEG+MR)"
    if _get(r, "data_type"):
        facts.append(
            DATA_TYPE_SHORT.get(_get(r, "data_type"), str(_get(r, "data_type")))
        )
    lines = [head]
    fill = {
        "width": max(width, 40),
        "initial_indent": indent,
        "subsequent_indent": indent,
    }
    lines += textwrap.wrap(" · ".join(facts), **fill)
    data = f"Modalities: {_modalities(r)}"
    if _tags(r):
        data += f"   Tags: {_tags(r)}"
    lines += textwrap.wrap(data, **fill)
    desc = " ".join(str(_get(r, "description")).split())
    if desc:
        lines += textwrap.wrap(
            desc, **fill, max_lines=None if full else 3, placeholder=" …"
        )
    else:
        lines.append(indent + "(no description)")
    return "\n".join(lines)


def format_table(res, width):
    """One line per project; the name column absorbs the remaining width."""
    fixed = [
        ("ID", 4, "project_id"),
        ("Start", 7, "start_date"),
        ("Subj", 5, "n_subjects"),
        ("MEG+MR", 7, "n_subj_MEG_and_MR"),
    ]
    mod_w = 18
    name_w = max(12, width - sum(w + 1 for _, w, _ in fixed) - mod_w - 3)
    rows = [
        f"{'ID':>4} {'Name':<{name_w}} {'Start':<7} {'Subj':>5} {'MEG+MR':>7}  Modalities",
        "-" * min(width, 4 + name_w + 7 + 5 + 7 + 6 + mod_w),
    ]
    for _, r in res.iterrows():
        name = str(_get(r, "name"))
        if len(name) > name_w:
            name = name[: name_w - 1] + "…"
        mods = _modalities(r)
        if len(mods) > mod_w:
            mods = mods[: mod_w - 1] + "…"
        exp = "*" if _get(r, "expired", False) is True else " "
        rows.append(
            f"{_int(r, 'project_id'):>4} {name:<{name_w}} {str(_get(r, 'start_date'))[:7]:<7} "
            f"{_int(r, 'n_subjects'):>5} {_int(r, 'n_subj_MEG_and_MR') if _get(r, 'n_subj_MEG_and_MR', 0) else '':>7}"
            f" {exp}{mods}"
        )
    rows.append("(* = expired)")
    return "\n".join(rows)
