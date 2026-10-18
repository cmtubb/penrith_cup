#!/usr/bin/env python3
"""Compute series ranking points from raw race results and write points.json."""

import argparse
import json
import os
import sys

MAX_POINTS = 1000
MIN_N = 5
CLASSES = ["C1M", "C1W", "K1M", "K1W"]
COMBINED = {"Men": ["C1M", "K1M"], "Women": ["C1W", "K1W"]}


def normalise(name):
    return " ".join(name.lower().split())


def person_key(p):
    return normalise(p["firstname"]), normalise(p["surname"])


def display_name(p):
    return f"{p['firstname']} {p['surname']}"


def round_half_up(x):
    return int(x + 0.5)


def get_points(rank, n):
    return round_half_up(MAX_POINTS - (rank - 1) * (MAX_POINTS / n))


def competition_ranks(values):
    """Rank values (already sorted best-first); equal values share a rank (1, 1, 3)."""
    ranks = []
    for i, v in enumerate(values):
        ranks.append(ranks[-1] if i > 0 and v == values[i - 1] else i + 1)
    return ranks


def best_total_hundredths(paddler):
    totals = [
        round((run["time"] + run["penalty"]) * 100)
        for run in paddler["runs"]
        if "status" not in run
    ]
    return min(totals) if totals else None


def race_points(entries):
    """Return {person key: points} for one class of one race."""
    ranked = [(best_total_hundredths(p), person_key(p)) for p in entries]
    ranked = sorted((t, key) for t, key in ranked if t is not None)
    n = max(MIN_N, len(ranked))
    ranks = competition_ranks([t for t, _ in ranked])
    return {key: get_points(rank, n) for (_, key), rank in zip(ranked, ranks)}


def standings(rows, key):
    rows.sort(key=lambda r: (-r[key], r["surname"], r["firstname"]))
    for row, rank in zip(rows, competition_ranks([-r[key] for r in rows])):
        row["rank"] = rank
    return rows


def min_edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (2 if a[i - 1] != b[j - 1] else 0))
        prev = cur
    return prev[-1]


def check_names(display_names):
    names = sorted(display_names)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if min_edit_distance(a.lower(), b.lower()) < 4:
                print(f"WARNING: possible duplicate names: '{a}' / '{b}'", file=sys.stderr)


def compute(series_dir, series):
    race_ids = []
    people = {}
    class_race_points = {cl: {} for cl in CLASSES}

    for race in series["races"]:
        if not race["results"]:
            continue
        with open(os.path.join(series_dir, race["results"])) as f:
            results = json.load(f)
        race_ids.append(race["id"])
        for cl in CLASSES:
            entries = results["classes"].get(cl, [])
            for p in entries:
                people.setdefault(person_key(p), {"firstname": p["firstname"], "surname": p["surname"]})
            for key, pts in race_points(entries).items():
                class_race_points[cl].setdefault(key, {})[race["id"]] = pts

    check_names(display_name(p) for p in people.values())

    classes = {}
    for cl in CLASSES:
        rows = [
            {**people[key], "points": pts, "total": sum(pts.values())}
            for key, pts in class_race_points[cl].items()
        ]
        classes[cl] = standings(rows, "total")

    class_totals = {cl: {person_key(r): r["total"] for r in rows} for cl, rows in classes.items()}
    combined = {}
    for group, cls in COMBINED.items():
        keys = {key for cl in cls for key in class_totals[cl]}
        rows = []
        for key in keys:
            per_class = {cl: class_totals[cl][key] for cl in cls if key in class_totals[cl]}
            total = round_half_up(sum(per_class.values()) / len(cls))
            rows.append({**people[key], "classes": per_class, "total": total})
        combined[group] = standings(rows, "total")

    return {"races": race_ids, "classes": classes, "combined": combined}


def published_changes(old, new):
    changes = []
    for cl, rows in old.get("classes", {}).items():
        new_rows = {person_key(r): r["points"] for r in new["classes"].get(cl, [])}
        for row in rows:
            for race_id, pts in row["points"].items():
                new_pts = new_rows.get(person_key(row), {}).get(race_id)
                if new_pts != pts:
                    changes.append(f"{race_id} {cl} {display_name(row)}: {pts} -> {new_pts}")
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series", help="Path to series.json")
    parser.add_argument("--force", action="store_true", help="Overwrite points already published")
    args = parser.parse_args()

    series_dir = os.path.dirname(os.path.abspath(args.series))
    with open(args.series) as f:
        series = json.load(f)

    result = compute(series_dir, series)
    out_path = os.path.join(series_dir, "points.json")

    if os.path.exists(out_path) and not args.force:
        with open(out_path) as f:
            changes = published_changes(json.load(f), result)
        if changes:
            print("Published points would change (use --force to overwrite):", file=sys.stderr)
            for c in changes:
                print(f"  {c}", file=sys.stderr)
            sys.exit(1)

    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")

    for cl, rows in list(result["classes"].items()) + list(result["combined"].items()):
        print(f"== {cl}")
        for r in rows:
            print(f"{r['rank']:3d}  {display_name(r):25s} {r['total']:5d}")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
