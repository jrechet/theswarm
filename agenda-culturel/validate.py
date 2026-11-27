"""Valide agenda.json : schéma, id uniques, dates dans la semaine, règles « zéro invention ».
Usage : python validate.py [agenda.json]  (code 1 si erreur)"""
import json, sys, datetime as dt
from pathlib import Path

HERE = Path(__file__).parent


def check(data: dict) -> list[str]:
    errs: list[str] = []
    try:
        import jsonschema
        errs += [f"schéma: {'/'.join(map(str, e.path))}: {e.message}"
                 for e in jsonschema.Draft202012Validator(
                     json.loads((HERE / "schema.json").read_text())).iter_errors(data)]
    except ImportError:
        errs.append("jsonschema absent : pip install jsonschema")
    if errs:
        return errs
    m = data["meta"]
    start, end = dt.date.fromisoformat(m["week_start"]), dt.date.fromisoformat(m["week_end"])
    if start.weekday() != 0 or end != start + dt.timedelta(days=6):
        errs.append("la semaine doit aller du lundi au dimanche")
    seen = set()
    for e in data["events"]:
        i = e["id"]
        if i in seen:
            errs.append(f"{i}: id en double")
        seen.add(i)
        if not start <= dt.date.fromisoformat(e["date"]) <= end:
            errs.append(f"{i}: date hors semaine")
        if e["is_free"] != (e["price"].strip().lower().startswith("gratuit")):
            errs.append(f"{i}: is_free incohérent avec price")
        if e["status"] != "confirmed" and not e["notes"].strip():
            errs.append(f"{i}: statut {e['status']} sans note explicative")
        if e["time"] == "" or e["price"] == "":
            errs.append(f"{i}: heure/prix vide — écrire « Non précisée » / « Non précisé »")
    return errs


if __name__ == "__main__":
    p = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "agenda.json")
    problems = check(json.loads(p.read_text()))
    print("\n".join(problems) or "OK")
    sys.exit(1 if problems else 0)
