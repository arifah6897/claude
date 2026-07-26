#!/usr/bin/env python3
"""
Brunch Buddies survey matcher.

Reads survey responses (e.g. a Google Forms CSV export) and splits
respondents into small groups (default size 4) that maximize shared
interests, based on:

  - What are you hoping to find through Brunch Buddies? (multi-select)
  - What topics energise you? (multi-select)
  - What stage are you at in your career? (single-select)

Usage:
    python brunch_matcher.py responses.csv
    python brunch_matcher.py responses.csv --group-size 4 --output groups.csv
    python brunch_matcher.py --demo                # try it with synthetic data

No third-party dependencies required (stdlib only).
"""

import argparse
import csv
import io
import itertools
import json
import random
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Column auto-detection
# ---------------------------------------------------------------------------

COLUMN_HINTS = {
    "name": ["name"],
    "email": ["email"],
    "stage": ["career"],
    "goals": ["hoping to find", "brunch buddies"],
    "topics": ["topics", "energise", "energize"],
    "notes": ["anything else", "accessibility", "dietary"],
}


def detect_columns(fieldnames, overrides):
    detected = {}
    lower_fields = {f: f.lower() for f in fieldnames}
    for key, hints in COLUMN_HINTS.items():
        if overrides.get(key):
            detected[key] = overrides[key]
            continue
        match = None
        for field, lower in lower_fields.items():
            if any(hint in lower for hint in hints):
                match = field
                break
        detected[key] = match
    return detected


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

class Respondent:
    __slots__ = ("id", "label", "stage", "goals", "topics", "notes", "row")

    def __init__(self, id_, label, stage, goals, topics, notes, row):
        self.id = id_
        self.label = label
        self.stage = stage
        self.goals = goals
        self.topics = topics
        self.notes = notes
        self.row = row


def split_multiselect(raw, delimiter):
    if not raw:
        return set()
    return {part.strip() for part in raw.split(delimiter) if part.strip()}


def load_respondents(csv_text, delimiter, overrides):
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV appears to have no header row.")
    cols = detect_columns(reader.fieldnames, overrides)

    missing = [k for k in ("goals", "topics") if not cols.get(k)]
    if missing:
        raise ValueError(
            f"Could not auto-detect column(s): {', '.join(missing)}. "
            f"Pass them explicitly, e.g. --{missing[0]}-col \"exact header text\". "
            f"Headers found: {reader.fieldnames}"
        )

    respondents = []
    for i, row in enumerate(reader, start=1):
        name = (row.get(cols["name"]) or "").strip() if cols.get("name") else ""
        email = (row.get(cols["email"]) or "").strip() if cols.get("email") else ""
        label = name or email or f"Respondent {i}"
        stage = (row.get(cols["stage"]) or "").strip() if cols.get("stage") else ""
        goals = split_multiselect(row.get(cols["goals"], ""), delimiter)
        topics = split_multiselect(row.get(cols["topics"], ""), delimiter)
        notes = (row.get(cols["notes"]) or "").strip() if cols.get("notes") else ""
        respondents.append(Respondent(i, label, stage, goals, topics, notes, row))
    return respondents, cols


# ---------------------------------------------------------------------------
# Similarity scoring
# ---------------------------------------------------------------------------

def jaccard(a, b):
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def pair_score(a, b, weights):
    score = 0.0
    score += weights["topics"] * jaccard(a.topics, b.topics)
    score += weights["goals"] * jaccard(a.goals, b.goals)
    if a.stage and b.stage and a.stage == b.stage:
        score += weights["stage"]
    return score


def build_similarity_matrix(respondents, weights):
    sim = {}
    for a, b in itertools.combinations(respondents, 2):
        s = pair_score(a, b, weights)
        sim[(a.id, b.id)] = s
        sim[(b.id, a.id)] = s
    return sim


# ---------------------------------------------------------------------------
# Group sizing: split N people into groups as close to target_size as possible
# ---------------------------------------------------------------------------

def plan_group_sizes(n, target_size=4, min_size=2, max_size=6):
    if n <= 0:
        return []
    if n <= min_size:
        return [n]

    best = None
    lo = max(1, n // (target_size + 2))
    hi = max(1, n // max(1, target_size - 2)) + 1
    for k in range(lo, hi + 1):
        if k <= 0:
            continue
        q, r = divmod(n, k)
        if q < min_size and not (r and q + 1 >= min_size and k - r == 0):
            continue
        sizes = [q + 1] * r + [q] * (k - r)
        if any(s < min_size or s > max_size for s in sizes):
            continue
        deviation = sum(abs(s - target_size) for s in sizes)
        candidate = (deviation, -k)  # prefer lower deviation, then more groups
        if best is None or candidate < best[0]:
            best = (candidate, sizes)

    if best is None:
        # Fallback: as-even-as-possible split into ceil(n/target_size) groups
        k = max(1, round(n / target_size))
        q, r = divmod(n, k)
        return [q + 1] * r + [q] * (k - r)

    return sorted(best[1], reverse=True)


# ---------------------------------------------------------------------------
# Greedy group assignment
# ---------------------------------------------------------------------------

def assign_groups(respondents, sim, sizes, spread_ids=frozenset()):
    """Greedily build groups. If spread_ids is given, avoid putting more than
    one member of that set in the same group whenever an alternative exists
    (e.g. keeping committee members spread one-per-table)."""
    unassigned = {r.id: r for r in respondents}
    groups = []

    for size in sizes:
        if not unassigned:
            break
        if len(unassigned) <= size:
            groups.append(list(unassigned.values()))
            unassigned.clear()
            break

        ids = list(unassigned.keys())
        pairs = list(itertools.combinations(ids, 2))
        non_conflict = [p for p in pairs if not (p[0] in spread_ids and p[1] in spread_ids)]
        pool = non_conflict if non_conflict else pairs
        best_pair = max(pool, key=lambda pq: sim.get((pq[0], pq[1]), 0.0))
        group_ids = [best_pair[0], best_pair[1]]
        del unassigned[best_pair[0]]
        del unassigned[best_pair[1]]

        while len(group_ids) < size and unassigned:
            def avg_sim(candidate_id):
                return sum(sim.get((candidate_id, gid), 0.0) for gid in group_ids) / len(group_ids)

            group_has_spread = any(gid in spread_ids for gid in group_ids)
            if group_has_spread:
                candidates = [cid for cid in unassigned if cid not in spread_ids]
                if not candidates:
                    candidates = list(unassigned.keys())
            else:
                candidates = list(unassigned.keys())

            best_candidate = max(candidates, key=avg_sim)
            group_ids.append(best_candidate)
            del unassigned[best_candidate]

        groups.append([r for r in respondents if r.id in group_ids])

    return groups


def group_quality(group, sim):
    if len(group) < 2:
        return 0.0
    pairs = list(itertools.combinations([r.id for r in group], 2))
    return sum(sim.get(p, 0.0) for p in pairs) / len(pairs)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def format_group_text(idx, group, sim):
    lines = [f"Table {idx} ({len(group)} people) — compatibility score: {group_quality(group, sim):.2f}"]
    for r in group:
        stage = f" — {r.stage}" if r.stage else ""
        lines.append(f"  - {r.label}{stage}")
    shared_topics = set.intersection(*[r.topics for r in group]) if group else set()
    shared_goals = set.intersection(*[r.goals for r in group]) if group else set()
    if shared_topics:
        lines.append(f"    Shared topics: {', '.join(sorted(shared_topics))}")
    if shared_goals:
        lines.append(f"    Shared goals: {', '.join(sorted(shared_goals))}")
    notes = [f"{r.label}: {r.notes}" for r in group if r.notes]
    if notes:
        lines.append(f"    Notes for organizers: {'; '.join(notes)}")
    return "\n".join(lines)


def write_csv(path, groups):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["table", "name", "stage", "goals", "topics", "notes"])
        for idx, group in enumerate(groups, start=1):
            for r in group:
                writer.writerow([
                    idx, r.label, r.stage,
                    "; ".join(sorted(r.goals)),
                    "; ".join(sorted(r.topics)),
                    r.notes,
                ])


def write_json(path, groups, sim):
    data = []
    for idx, group in enumerate(groups, start=1):
        data.append({
            "table": idx,
            "compatibility_score": round(group_quality(group, sim), 3),
            "members": [
                {
                    "name": r.label,
                    "stage": r.stage,
                    "goals": sorted(r.goals),
                    "topics": sorted(r.topics),
                    "notes": r.notes,
                }
                for r in group
            ],
        })
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


STRATEGY_DESCRIPTION = (
    "How tables were matched: everyone's survey answers were compared pairwise to find who has the most "
    "in common — mainly the topics that energise them, and secondarily what they're hoping to get out of "
    "Brunch Buddies. People at the same career stage got a small extra boost to sit together. Tables were "
    "then built one at a time, starting from the strongest-matching pair and adding whoever fits best with "
    "the group so far, until each table reached its target size. This is a best-effort match, not a perfect "
    "one — with a limited set of topics/goals to choose from, some tables naturally land a stronger overlap "
    "than others; the Compatibility Score on the Table Summary tab shows how strong each table's match is "
    "(higher = more shared interests)."
)

# Pastel palette, one color per table, cycling if there are more tables than colors.
GROUP_COLORS = [
    "BDD7EE",  # blue
    "C6E0B4",  # green
    "D9D2E9",  # purple
    "F8CBAD",  # peach
    "F4CCCC",  # rose
    "D0E0E3",  # teal
    "FCE5CD",  # tan
    "CFE2F3",  # sky
    "D9EAD3",  # sage
    "EAD1DC",  # mauve
]


def write_xlsx(path, respondents, groups, sim, spread_ids=frozenset(), spread_label="Flagged"):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        raise SystemExit(
            "Writing .xlsx output requires openpyxl. Install it with: pip install openpyxl"
        )

    import datetime

    font_name = "Arial"
    header_fill = PatternFill("solid", fgColor="2F5496")
    header_font = Font(name=font_name, bold=True, color="FFFFFF", size=11)
    title_font = Font(name=font_name, bold=True, size=14)
    subtitle_font = Font(name=font_name, italic=True, size=9, color="595959")
    desc_font = Font(name=font_name, size=10, color="333333")
    group_fills = [PatternFill("solid", fgColor=c) for c in GROUP_COLORS]
    spread_fill = PatternFill("solid", fgColor="FFEB84")
    body_font = Font(name=font_name, size=10)
    spread_font = Font(name=font_name, size=10, bold=True)
    thin = Side(style="thin", color="BFBFBF")
    thick_yellow = Side(style="medium", color="BF9000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    spread_border = Border(left=thick_yellow, right=thick_yellow, top=thick_yellow, bottom=thick_yellow)

    wb = Workbook()

    ws = wb.active
    ws.title = "Table Assignments"
    ws["A1"] = "Brunch Buddies — Table Assignments"
    ws["A1"].font = title_font
    ws["A2"] = f"Generated {datetime.date.today().isoformat()} | {len(respondents)} attendees | {len(groups)} tables"
    ws["A2"].font = subtitle_font

    ws.merge_cells("A3:F6")
    desc_cell = ws["A3"]
    desc_cell.value = STRATEGY_DESCRIPTION
    desc_cell.font = desc_font
    desc_cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[3].height = 90

    legend_row = 7
    ws.cell(row=legend_row, column=1, value="Legend:").font = Font(name=font_name, bold=True, size=9)
    if spread_ids:
        ws.cell(row=legend_row, column=2, value=f"Yellow + bold = {spread_label} (spread one per table)")
        ws.cell(row=legend_row, column=2).font = subtitle_font
    else:
        ws.cell(row=legend_row, column=2, value="Each table has its own row color")
        ws.cell(row=legend_row, column=2).font = subtitle_font

    headers = ["Table", "Name", "Career Stage", "Goals", "Topics", "Notes"]
    header_row = 9
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=c, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
        cell.border = border

    r = header_row + 1
    for gi, group in enumerate(groups):
        fill = group_fills[gi % len(group_fills)]
        for member in group:
            is_spread = member.id in spread_ids
            font = spread_font if is_spread else body_font
            name = f"{member.label} ({spread_label})" if is_spread else member.label
            values = [gi + 1, name, member.stage,
                      "; ".join(sorted(member.goals)), "; ".join(sorted(member.topics)), member.notes]
            for c, v in enumerate(values, start=1):
                cell = ws.cell(row=r, column=c, value=v)
                cell.font = font
                cell.fill = spread_fill if is_spread else fill
                cell.border = spread_border if is_spread else border
                cell.alignment = Alignment(vertical="top", wrap_text=(c in (4, 5, 6)))
            r += 1

    ws.freeze_panes = f"A{header_row + 1}"
    ws.auto_filter.ref = f"A{header_row}:F{r - 1}"
    for col, w in {"A": 8, "B": 24, "C": 20, "D": 42, "E": 42, "F": 32}.items():
        ws.column_dimensions[col].width = w

    ws2 = wb.create_sheet("Table Summary")
    ws2["A1"] = "Brunch Buddies — Table Summary"
    ws2["A1"].font = title_font
    ws2["A2"] = "Each row is color-matched to its table on the Table Assignments tab."
    ws2["A2"].font = subtitle_font
    headers2 = ["Table", "Size", "Compatibility Score", "Shared Topics", "Shared Goals", "Organizer Notes"]
    for c, h in enumerate(headers2, start=1):
        cell = ws2.cell(row=4, column=c, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    r = 5
    for gi, group in enumerate(groups):
        score = group_quality(group, sim)
        shared_topics = set.intersection(*[m.topics for m in group]) if group else set()
        shared_goals = set.intersection(*[m.goals for m in group]) if group else set()
        org_notes = "; ".join(f"{m.label}: {m.notes}" for m in group if m.notes)
        row_vals = [gi + 1, len(group), round(score, 2),
                    "; ".join(sorted(shared_topics)) or "—",
                    "; ".join(sorted(shared_goals)) or "—",
                    org_notes or "—"]
        for c, v in enumerate(row_vals, start=1):
            cell = ws2.cell(row=r, column=c, value=v)
            cell.font = body_font
            cell.fill = group_fills[gi % len(group_fills)]
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=(c in (4, 5, 6)))
        r += 1

    ws2.freeze_panes = "A5"
    ws2.auto_filter.ref = f"A4:F{r - 1}"
    for col, w in {"A": 8, "B": 8, "C": 18, "D": 40, "E": 34, "F": 40}.items():
        ws2.column_dimensions[col].width = w

    wb.save(path)


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

DEMO_STAGES = [
    "Student", "Early career (0-3 yrs)", "Mid career (4-9 yrs)",
    "Senior (10+ yrs)", "Founder / entrepreneur", "Career break / returning",
]
DEMO_GOALS = [
    "Meet new friends within the same industry/line of work",
    "Learn from women in different industries",
    "Find a group with similar hobbies/interests",
    "Simply have meaningful conversations",
]
DEMO_TOPICS = [
    "Entrepreneurship", "Work-life balance", "Creativity & building something from scratch",
    "Travel", "Books / podcasts", "Women's health & well-being", "Fitness",
]
DEMO_NAMES = [
    "Ava", "Bee", "Cara", "Dana", "Elle", "Fay", "Gia", "Hana", "Ivy", "Jo",
    "Kai", "Lena", "Mia", "Nia", "Oya", "Pia", "Qi", "Ria", "Sana", "Tia",
    "Uma", "Via", "Wren", "Xia", "Yara",
]


def generate_demo_csv(n=25, seed=42):
    rng = random.Random(seed)
    rows = []
    header = [
        "Name",
        "What stage are you at in your career?",
        "What are you hoping to find through Brunch Buddies?",
        "What topics energise you?",
        "Anything else you'd want us to know? (e.g. accessibility needs, dietary preferences, etc.)",
    ]
    rows.append(header)
    for i in range(n):
        name = DEMO_NAMES[i % len(DEMO_NAMES)] + (str(i // len(DEMO_NAMES) + 1) if i >= len(DEMO_NAMES) else "")
        stage = rng.choice(DEMO_STAGES)
        goals = rng.sample(DEMO_GOALS, k=rng.randint(1, 3))
        topics = rng.sample(DEMO_TOPICS, k=rng.randint(2, 4))
        note = rng.choice(["", "", "", "Vegetarian", "Wheelchair accessible venue please", "Nut allergy"])
        rows.append([name, stage, ", ".join(goals), ", ".join(topics), note])

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Group Brunch Buddies survey respondents into tables.")
    parser.add_argument("csv_path", nargs="?", help="Path to survey responses CSV (e.g. Google Forms export)")
    parser.add_argument("--group-size", type=int, default=4, help="Target group size (default: 4)")
    parser.add_argument("--delimiter", default=",", help="Delimiter used within multi-select cells (default: ',')")
    parser.add_argument("--output", help="Write groups to this file (.csv, .json, or .xlsx based on extension)")
    parser.add_argument("--spread-tag", action="append", default=[],
                         help="Substring to match (case-insensitive) against each respondent's notes; "
                              "matching people are spread one-per-table where possible. Repeatable.")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Console output format")
    parser.add_argument("--topic-weight", type=float, default=1.5)
    parser.add_argument("--goal-weight", type=float, default=1.0)
    parser.add_argument("--stage-weight", type=float, default=0.5, help="Bonus for matching career stage")
    parser.add_argument("--name-col")
    parser.add_argument("--email-col")
    parser.add_argument("--stage-col")
    parser.add_argument("--goals-col")
    parser.add_argument("--topics-col")
    parser.add_argument("--notes-col")
    parser.add_argument("--demo", action="store_true", help="Run against generated synthetic sample data")
    parser.add_argument("--demo-n", type=int, default=25, help="Number of synthetic respondents for --demo")
    args = parser.parse_args()

    if not args.demo and not args.csv_path:
        parser.error("provide a CSV path or use --demo")

    if args.demo:
        csv_text = generate_demo_csv(n=args.demo_n)
    else:
        with open(args.csv_path, "r", encoding="utf-8-sig") as f:
            csv_text = f.read()

    overrides = {
        "name": args.name_col, "email": args.email_col, "stage": args.stage_col,
        "goals": args.goals_col, "topics": args.topics_col, "notes": args.notes_col,
    }
    try:
        respondents, cols = load_respondents(csv_text, args.delimiter, overrides)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if len(respondents) < 2:
        print("Need at least 2 respondents to form groups.", file=sys.stderr)
        sys.exit(1)

    spread_ids = set()
    if args.spread_tag:
        tags = [t.lower() for t in args.spread_tag]
        spread_ids = {r.id for r in respondents if any(t in r.notes.lower() for t in tags)}
        print(f"Spreading {len(spread_ids)} tagged respondent(s) one-per-table "
              f"(matched: {', '.join(args.spread_tag)})\n")

    weights = {"topics": args.topic_weight, "goals": args.goal_weight, "stage": args.stage_weight}
    sim = build_similarity_matrix(respondents, weights)
    sizes = plan_group_sizes(len(respondents), target_size=args.group_size)
    groups = assign_groups(respondents, sim, sizes, spread_ids=spread_ids)

    overall_avg = sum(group_quality(g, sim) for g in groups) / len(groups)
    print(f"Matched {len(respondents)} respondents into {len(groups)} tables "
          f"(sizes: {[len(g) for g in groups]}). Avg compatibility: {overall_avg:.2f}\n")

    if args.format == "json":
        print(json.dumps([
            {
                "table": idx,
                "compatibility_score": round(group_quality(g, sim), 3),
                "members": [r.label for r in g],
            }
            for idx, g in enumerate(groups, start=1)
        ], indent=2))
    else:
        for idx, group in enumerate(groups, start=1):
            print(format_group_text(idx, group, sim))
            print()

    if args.output:
        if args.output.endswith(".json"):
            write_json(args.output, groups, sim)
        elif args.output.endswith(".xlsx"):
            spread_label = args.spread_tag[0] if args.spread_tag else "Flagged"
            write_xlsx(args.output, respondents, groups, sim, spread_ids=spread_ids, spread_label=spread_label)
        else:
            write_csv(args.output, groups)
        print(f"Wrote groups to {args.output}")


if __name__ == "__main__":
    main()
