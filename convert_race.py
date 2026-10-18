#!/usr/bin/env python3
"""Convert a race's timing spreadsheet and SiWi start list XML into a race results JSON file."""

import argparse
import json
import sys
import xml.etree.ElementTree as ET

import openpyxl

NS = "{http://siwidata.com/Canoe123/Data.xsd}"
CLASSES = ["C1M", "C1W", "K1M", "K1W"]

# Category codes after the boat class, e.g. K1MU16, K1MOPN, K1MAST (Masters)
CATEGORY_CODES = {"U12": "U12", "U14": "U14", "U16": "U16", "U18": "U18", "U23": "U23",
                  "OPN": "Open", "MAST": "Masters", "AST": "Masters", "VET": "Veterans",
                  "VIN": "Vintage", "LGN": "Legends"}


def text(element, tag):
    child = element.find(NS + tag)
    return (child.text or "").strip() if child is not None else ""


def read_start_list(xml_path):
    root = ET.parse(xml_path).getroot()
    event = root.find(NS + "Events")
    paddlers = {}
    for p in root.findall(NS + "Participants"):
        cls = text(p, "ClassId")
        code = text(p, "CatId").removeprefix(cls)
        if code not in CATEGORY_CODES:
            sys.exit(f"Unknown age category code '{text(p, 'CatId')}'")
        paddlers[(cls, int(text(p, "EventBib")))] = {
            "firstname": text(p, "GivenName"),
            "surname": text(p, "FamilyName").upper(),
            "club": text(p, "Club"),
            "age_category": CATEGORY_CODES[code],
        }
    return paddlers, text(event, "StartDate")[:10], text(event, "Location")


def sheet_rows(ws):
    """Rows as dicts keyed by header, stopping at the first blank or repeated header row."""
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    for row in rows:
        if row[0] is None or row[0] == header[0]:
            break
        yield dict(zip(header, row))


def read_runs(xlsm_path):
    wb = openpyxl.load_workbook(xlsm_path, data_only=True)

    penalties = {}
    for row in sheet_rows(wb["Penalties"]):
        gates = [row[k] for k in row if k and str(k).startswith("G") and str(k)[1:].isdigit()]
        if any(g is None for g in gates):
            continue
        gates = [int(g) for g in gates]
        if sum(gates) != row["Penalty Sec."]:
            sys.exit(f"{row['Class']} bib {row['Bib']} run {row['Run']}: gates add up to {sum(gates)}, "
                     f"but 'Penalty Sec.' is {row['Penalty Sec.']}")
        penalties[(row["Class"], int(row["Bib"]), int(row["Run"]))] = gates

    runs = {}
    for row in sheet_rows(wb["Raw Timing"]):
        key = (row["Class"], int(row["Bib Number"]), int(row["Run Number"]))
        if row["Start Time"] is None:
            run = {"status": "DNS"}
        elif row["Finish Time"] is None:
            run = {"status": "DNF"}
            if key in penalties:
                run["penalty"] = sum(penalties[key])
        else:
            if key not in penalties:
                sys.exit(f"{key[0]} bib {key[1]} run {key[2]}: has a time but no penalties")
            gates = penalties[key]
            run = {"time": round(row["Run Time (seconds)"], 2), "penalty": sum(gates), "gates": gates}
        runs[key] = run
    return runs


def best_total(entry):
    totals = [r["time"] + r["penalty"] for r in entry["runs"] if "status" not in r]
    return min(totals) if totals else float("inf")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xlsm", help="Timing spreadsheet with 'Raw Timing' and 'Penalties' sheets")
    parser.add_argument("xml", help="SiWi XML export with the start list")
    parser.add_argument("output", help="Race results JSON file to write")
    parser.add_argument("--race", required=True, help='Race title, e.g. "Penrith Cup 2 - Whitewater"')
    parser.add_argument("--add", action="append", default=[], metavar="CLASS,BIB,FIRSTNAME,SURNAME,CLUB,CATEGORY",
                        help="A paddler missing from the start list (CATEGORY may be blank)")
    args = parser.parse_args()

    paddlers, date, venue = read_start_list(args.xml)
    for extra in args.add:
        cls, bib, firstname, surname, club, category = (s.strip() for s in extra.split(","))
        paddlers[(cls, int(bib))] = {"firstname": firstname, "surname": surname.upper(),
                                     "club": club, "age_category": category}

    runs = read_runs(args.xlsm)
    for cls, bib, _ in runs:
        if (cls, bib) not in paddlers:
            sys.exit(f"{cls} bib {bib} has timing but is not on the start list; add them with --add")

    classes = {}
    for cls in CLASSES:
        entries = [
            {"bib": bib, **info, "runs": [runs.get((cls, bib, n), {"status": "DNS"}) for n in (1, 2)]}
            for (c, bib), info in paddlers.items() if c == cls
        ]
        classes[cls] = sorted(entries, key=best_total)

    with open(args.output, "w") as f:
        json.dump({"race": args.race, "date": date, "venue": venue, "classes": classes}, f, indent=2)
        f.write("\n")

    for cls, entries in classes.items():
        print(f"{cls}: {len(entries)} paddlers")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
