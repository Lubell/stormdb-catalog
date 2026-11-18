# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Phase 0 proof of concept for a searchable, **metadata-only** catalog of every StormDb project at CFIN (Aarhus University), including expired ones, so researchers can ask questions like "MEG + MRI studies of vision". It must never read or copy raw imaging data — only project metadata and series listings.

The code was written against stormdb-python (last commit 2020). Stage 1 has been run against the live server (2026-11-18: 502 projects); its parsers follow the real page layout described in their docstrings. Stages 2–4 have not yet been run against live data. Project descriptions are often in Danish, which the English-only `KEYWORDS` rules in `tagging.py` miss.

## Layout

src layout (`uv_build`); the `stormdb-catalog` console script is `stormdb_catalog.cli:main`. One module per stage, each exposing `run(args)`; `cli.py` only builds the argparse tree and dispatches via `set_defaults(func=...)`. `main(argv=None)` takes an argv list, so tests drive the CLI directly.

- `config.py`: server URLs and the default login-file path
- `extract.py`: extract-API client (`login`/`run_login`, `read_login_code`, `parse_filteredseries`, `fetch_series`)
- `projects.py`, `inventory.py`, `tagging.py`, `query.py`: stages 1–4

Pure parsers (`parse_*`, `summarize`, `keyword_tags`) are kept apart from the network calls so they can be tested on fixtures.

## Commands

Uses `uv` (Python 3.10, see `.python-version`).

```bash
uv sync                                   # install deps + dev group (pytest, ruff)
uv run stormdb-catalog --help             # run the pipeline (see stages below)
uv run ruff check .                       # lint
uv run ruff format .                      # format
uv run pytest                             # all tests (offline, ~1s)
uv run pytest tests/test_extract.py::test_login_writes_readonly_file  # single test
```

`anthropic` is not a declared dependency; it is only imported lazily for `tag --method llm` (`uv add anthropic` or `uv run --with anthropic ...`).

## Pipeline architecture

The CLI is a `login` command plus 4 stages (`argparse` subcommands). Each stage reads/writes CSVs in `--out` (default `./catalog`), and stages must run in order because each consumes the previous stage's files. Global options `--out` and `--delay` (seconds between HTTP requests, default 0.2) go **before** the subcommand.

0. **`login`** → `~/.stormdblogin` (`--login-file`). Prompts for the StormDb password and exchanges it at `{extract_url}login/username/<u>/password/<p>` for a login code, copying stormdb-python's `Query._get_login_code`; the file is written mode `0o400` and is compatible with stormdb-python. It refuses to overwrite without `--force`. Without a terminal (e.g. Claude Code's `!` commands, which have no TTY) it exits with a hint instead of prompting; `--password-stdin` reads the password from the first line of stdin instead. The password travels in the URL (that is how the API works), so `LoginError` messages and `requests` exceptions must never leak the URL. This step is needed only for `inventory`; stage 1's browser cookie is still supplied by hand.
1. **`projects`** → `projects.csv`. Scrapes the StormDb admin project list (`LIST_URL`, with expired projects) and each project's info page (`INFO_URL`) using a browser session cookie (`--cookie` or `STORMDB_COOKIE`): the full `Cookie` header, e.g. `PHPSESSID=...`. `clean_cookie` strips whitespace and a `Cookie:` prefix and rejects values without `=` or with control characters. A rejected cookie makes the server answer with its login page (`<title>Login</title>`); `run` detects that and stops, and an info page that turns into the login page mid-run is recorded as `info_error`. To set the variable without echoing it: paste `export STORMDB_COOKIE="$(xsel --clipboard --output | tr -d '\r\n')"`, copy the cookie in the browser, then press Enter. Info pages add `description` (the unlabeled full-width row), `expired` (from the warning alert, the only reliable expired signal), `data_type`, `n_users_*`, `disk_*_mb` and `n_documents`. Scraping is necessary because the stormdb-python extract API has no list-all-projects or description endpoint. If 0 projects parse from a non-login page, it dumps `listprojects_debug.html` to `--out`.
2. **`inventory`** → `series.csv` (one row per series) and `inventory.csv` (one row per project: modalities, per-modality subject counts, `n_subj_MEG_and_MR`, sample `series_names` JSON). Calls the extract API's `filteredseries` endpoint once per project, authenticated with the login code from `login`. Modality/subject/series are parsed from the path pattern `.../raw/<subject>/<study>/<MODALITY>/<NNN>.<seriesname>/files`. `--extract-url` overrides the endpoint (stormdb-python historically used `hyades00.pet.auh.dk`).
3. **`tag`** → `tags.csv`. Assigns topic tags from name + description + series names. `--method keywords` (default) uses the local regex table `KEYWORDS`; `--method llm` sends project text to the Anthropic API (`--model`, needs `ANTHROPIC_API_KEY`). The keyword method keeps everything inside AU; the LLM method sends project descriptions externally and AU data policy should be checked before using it.
4. **`query`** → stdout (optionally `--save` CSV). Left-joins `projects.csv` with `inventory.csv` and `tags.csv` on `name`, then filters by `--domain`, `--has` (modalities, e.g. `MEG MR`), `--both-meg-mr N`, `--text` (regex on name + description).

Conventions that span stages:
- The project **`name`** (not `project_id`) is the join key across all CSVs, and is what the extract API takes as `projectCode`.
- List-valued fields are stored inside CSV cells as `|`-joined strings (`modalities`) or JSON (`domain`, `series_names`, `raw_cells`, LLM tag fields). `query` relies on these encodings.
- Per-project failures are recorded in the row (`info_error`, `inventory_error`, `error`) rather than aborting the run.

Example: `uv run stormdb-catalog query --domain vision --has MEG MR`

## Tests

`tests/` uses only pytest and `monkeypatch`: `conftest.py` provides a `fake_get` fixture that replaces `requests.get`, plus `FakeResponse`. No test touches the network or the real `~/.stormdblogin` (login tests write under `tmp_path`). Inputs live in `tests/fixtures/` (HTML pages, a `filteredseries` response, and a small `catalog/` of stage CSVs). All fixture **content is invented**; the HTML structure of `listprojects.html` and `projectinfo.html` is copied from live pages, while `filteredseries.txt` is still a guess at the format. Real pages contain PI and subject information, so never commit them; save them under the git-ignored `catalog/` when inspecting the layout.
