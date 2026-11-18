"""
stormdb-catalog: Phase 0 proof of concept for a searchable CFIN data catalog.

Builds a flat, metadata-only catalog of every StormDb project (including
expired ones) so you can ask questions like "MEG + MRI studies of vision".
It never reads or copies raw data.

Stages (run in order, each writes a file in --out, default ./catalog):

  0. login      Store an extract-API login code in ~/.stormdblogin (prompts
                for your StormDb password; needed once, before inventory).

  1. projects   Scrape the admin project list and each project's info page
                (name, PI, dates, #subjects, description) -> projects.csv
                Uses your logged-in browser session cookie, because the
                stormdb-python "extract" API has no "list all projects" or
                "project description" endpoint.

  2. inventory  For each project, call the extract API "filteredseries"
                endpoint once and summarize modalities per subject
                -> series.csv (one row per series) and inventory.csv
                (one row per project: modalities, subjects with MEG+MR, ...)
                Uses the login code in ~/.stormdblogin (see "login"; same
                file stormdb-python's Query object uses).

  3. tag        Assign topic tags to each project description.
                --method keywords : local keyword rules, nothing leaves AU
                --method llm      : Anthropic API (needs ANTHROPIC_API_KEY;
                                    check AU policy before sending text out)
                -> tags.csv

  4. query      Join everything and filter, e.g.
                stormdb-catalog query --domain vision --has MEG MR

Requirements: uv sync  (plus anthropic for --method llm, not yet a dependency)

NOTE: Written against stormdb-python (last commit 2020) and screenshots of the
web UI; not yet tested against the live server. The HTML parsing in stage 1
is the part most likely to need small adjustments.
"""

import argparse
import os
from pathlib import Path

from . import inventory, projects, query, tagging
from .config import DEFAULT_LOGIN_FILE, EXTRACT_URL
from .extract import run_login


def build_parser():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=Path("catalog"))
    ap.add_argument(
        "--delay", type=float, default=0.2, help="seconds between requests (be gentle)"
    )
    sub = ap.add_subparsers(dest="stage", required=True)

    lg = sub.add_parser("login", help="store an extract-API login code")
    lg.add_argument("--user", help="StormDb username (default: your OS username)")
    lg.add_argument("--login-file", default=DEFAULT_LOGIN_FILE)
    lg.add_argument("--extract-url", default=EXTRACT_URL)
    lg.add_argument(
        "--force", action="store_true", help="replace an existing login file"
    )
    lg.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from the first line of stdin instead of prompting",
    )
    lg.set_defaults(func=run_login, needs_out=False)

    a = sub.add_parser("projects", help="stage 1: scrape project list and info pages")
    a.add_argument("--cookie", default=os.environ.get("STORMDB_COOKIE"))
    a.set_defaults(func=projects.run)

    ch = sub.add_parser(
        "changes", help="read-only: compare the live project list with projects.csv"
    )
    ch.add_argument("--cookie", default=os.environ.get("STORMDB_COOKIE"))
    ch.set_defaults(func=projects.run_changes)

    b = sub.add_parser(
        "inventory", help="stage 2: series per project from the extract API"
    )
    b.add_argument("--login-file", default=DEFAULT_LOGIN_FILE)
    b.add_argument("--extract-url", default=EXTRACT_URL)
    b.set_defaults(func=inventory.run)

    c = sub.add_parser("tag", help="stage 3: topic tags per project")
    c.add_argument("--method", choices=["keywords", "llm"], default="keywords")
    c.add_argument("--model", default="claude-sonnet-5-5")
    c.set_defaults(func=tagging.run)

    d = sub.add_parser("query", help="stage 4: join and filter")
    d.add_argument("--domain", help="e.g. vision")
    d.add_argument("--has", nargs="*", help="required modalities, e.g. MEG MR")
    d.add_argument(
        "--both-meg-mr", type=int, default=0, help="min #subjects with both MEG and MR"
    )
    d.add_argument("--text", help="regex on name + description")
    d.add_argument("--save", help="write results to this CSV")
    d.add_argument("--table", action="store_true", help="one line per project")
    d.add_argument("--full", action="store_true", help="show whole descriptions")
    d.add_argument("--width", type=int, help="output width (default: terminal width)")
    d.set_defaults(func=query.run)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "needs_out", True):
        args.out.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
