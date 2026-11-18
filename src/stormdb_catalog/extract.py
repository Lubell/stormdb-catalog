"""Client for the StormDb "extract" API: login, and series listings per project."""

import getpass
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, quote_plus

import requests

from .config import DEFAULT_LOGIN_FILE


class LoginError(Exception):
    """Login failed. Messages never contain the password or the request URL."""


def request_login_code(user, password, extract_url):
    """Exchange username/password for a login code, as stormdb-python's Query does."""
    url = f"{extract_url}login/username/{quote(user, safe='')}/password/{quote_plus(password)}"
    try:
        r = requests.get(url, timeout=60)
    except requests.RequestException:
        # requests' own messages include the URL, and with it the password
        raise LoginError(f"could not reach {extract_url}") from None
    if r.status_code != 200:
        raise LoginError(f"server returned HTTP {r.status_code}")
    txt = r.content.decode("utf-8").strip()
    if "could not login" in txt.lower():
        raise LoginError("invalid username or password")
    if not txt or "error" in txt.lower():
        raise LoginError(f"unexpected response from server: {txt[:200]!r}")
    return txt


def login(user, password, extract_url, login_file=DEFAULT_LOGIN_FILE, force=False):
    """Fetch a login code and store it owner-read-only in login_file. Returns the path."""
    p = Path(login_file).expanduser()
    if p.exists() and not force:
        raise LoginError(f"{p} already exists; use --force to replace it")
    code = request_login_code(user, password, extract_url)
    if p.exists():
        p.chmod(0o600)  # stored read-only; make it writable to replace it
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(code)
    p.chmod(0o400)
    return p


def run_login(args):
    p = Path(args.login_file).expanduser()
    if p.exists() and not args.force:
        sys.exit(f"{p} already exists; use --force to replace it.")
    user = args.user or getpass.getuser()
    password = getpass.getpass(f'StormDb password for "{user}": ')
    try:
        p = login(user, password, args.extract_url, p, force=args.force)
    except LoginError as e:
        sys.exit(f"Login failed: {e}")
    print(f"Wrote login code to {p}")


def read_login_code(path=DEFAULT_LOGIN_FILE):
    p = Path(path).expanduser()
    if not p.exists():
        sys.exit(f"{p} not found. Create it once with: stormdb-catalog login")
    return p.read_text().strip()


def parse_filteredseries(text):
    """Parse 'key:value$key:value' lines returned by the extract API."""
    out = []
    for line in filter(None, text.split("\n")):
        d = {}
        for kvp in line.split("$"):
            if ":" in kvp:
                k, v = kvp.split(":", 1)
                d[k.strip()] = v.strip()
        path = d.get("path", "")
        # .../raw/<subject>/<study>/<MODALITY>/<NNN>.<seriesname>/files
        m = re.search(r"/raw/([^/]+)/([^/]+)/([^/]+)/(\d{3})\.(.+?)/files", path)
        if m:
            d.setdefault("subjectcode", m.group(1))
            d.setdefault("study", m.group(2))
            d["modality"] = m.group(3)
            d["serieno"] = m.group(4)
            d["seriename"] = m.group(5)
        out.append(d)
    return out


def fetch_series(project_name, login_code, extract_url):
    params = (
        f"filteredseries?{login_code}&projectCode={project_name}&subjects=&studies="
        f"&modalities=&types=&anyWithType=0&description=&excluded=0&removeProjects="
    )
    r = requests.get(extract_url + params, timeout=120)
    r.raise_for_status()
    txt = r.content.decode("utf-8")
    if txt.lower().startswith("error"):
        if "your login is not working" in txt.lower():
            raise RuntimeError(
                "login code rejected; run: stormdb-catalog login --force"
            )
        raise RuntimeError(txt[:200])
    return parse_filteredseries(txt)
