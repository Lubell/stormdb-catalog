"""Stage 3: assign topic tags to projects -> tags.csv."""

import json
import re

import pandas as pd

KEYWORDS = {
    "vision": r"\bvisu|\bvision|occipital|retin|\bV1\b|gabor|saccad|\beye\b|blind|ocular|gaze",
    "audition": r"auditor|\bsound|\btone|music|hearing|cochle|mismatch negativity|\bMMN\b",
    "somatosensory": r"somatosens|tactile|\btouch|vibrotact|median nerve|thermo|pain|nocicep",
    "motor": r"\bmotor|movement|grasp|finger tap|button press|cerebell|parkinson|\bPD\b",
    "language": r"language|semantic|phonolog|speech|reading|word",
    "memory": r"memory|recall|encoding|hippocamp",
    "attention": r"attenti|cueing|warning signal",
    "resting_state": r"\brest(ing)?\b",
    "sleep": r"\bsleep",
    "clinical": r"patient|epilep|stroke|schizo|depress|parkinson|migraine|dementia|coma|\bPD\b|SCZ",
    "development": r"infant|child|fetal|foetal|neonat|ageing|aging",
}
TAG_FIELDS = ["domain", "paradigm", "population", "stimulus_modality"]


def keyword_tags(text):
    t = text or ""
    return {k: bool(re.search(v, t, re.IGNORECASE)) for k, v in KEYWORDS.items()}


def llm_tags(rows, model):
    import anthropic  # pip install anthropic

    client = anthropic.Anthropic()
    out = []
    for r in rows:
        prompt = (
            "Classify this neuroimaging project. Return only JSON with keys "
            "domain (list from: vision, audition, somatosensory, motor, language, memory, "
            "attention, emotion, decision, resting_state, sleep, other), paradigm (short list), "
            "population (list, e.g. healthy adults, late blind, Parkinson's, infants), "
            "stimulus_modality (list), confidence (low|medium|high).\n\n"
            f"Project name: {r['name']}\nDescription: {r.get('description') or '(none)'}\n"
            f"Series names: {r.get('series_names') or '(none)'}"
        )
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            txt = msg.content[0].text
            data = json.loads(txt[txt.find("{") : txt.rfind("}") + 1])
        except Exception as e:  # noqa: BLE001 - record per-project failure, keep going
            data = {"error": str(e)[:200]}
        out.append(
            {
                "name": r["name"],
                **{
                    k: json.dumps(data.get(k, ""))
                    if isinstance(data.get(k), list)
                    else data.get(k, "")
                    for k in TAG_FIELDS + ["confidence", "error"]
                },
            }
        )
    return out


def run(args):
    p = pd.read_csv(args.out / "projects.csv")
    inv_path = args.out / "inventory.csv"
    if inv_path.exists():
        p = p.merge(
            pd.read_csv(inv_path)[["name", "series_names"]], on="name", how="left"
        )
    p = p.fillna("")
    if args.method == "keywords":
        rows = []
        for _, r in p.iterrows():
            kw = keyword_tags(
                f"{r['name']} {r.get('description', '')} {r.get('series_names', '')}"
            )
            rows.append(
                {
                    "name": r["name"],
                    "domain": json.dumps([k for k, v in kw.items() if v]),
                }
            )
        tags = pd.DataFrame(rows)
    else:
        tags = pd.DataFrame(llm_tags(p.to_dict("records"), args.model))
    tags.to_csv(args.out / "tags.csv", index=False)
    print(f"Wrote tags.csv ({len(tags)} projects, method={args.method})")
