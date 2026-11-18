"""Stage 4: join the stage outputs and filter."""

import pandas as pd


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
    cols = [
        c
        for c in [
            "project_id",
            "name",
            "responsible",
            "start_date",
            "n_subjects",
            "modalities",
            "n_subj_MEG_and_MR",
            "domain",
            "description",
        ]
        if c in df
    ]
    res = df.loc[mask, cols].sort_values(cols[0])
    pd.set_option("display.max_colwidth", 80, "display.width", 200)
    print(res.to_string(index=False))
    print(f"\n{len(res)} projects match")
    if args.save:
        res.to_csv(args.save, index=False)
