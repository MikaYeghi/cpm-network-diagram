"""
CPM Network Diagram Generator (Grid Layout)

This script:
1) Reads activity data (ID, description, duration, predecessors) from a CSV.
2) Computes Critical Path Method (CPM) values:
   - ES (Earliest Start), EF (Earliest Finish)
   - LS (Latest Start), LF (Latest Finish)
   - TF (Total Float)
3) Draws a network diagram with nodes placed in a grid-like layout:
   - Orthogonal (square-ish) edges
   - Consistent spacing between nodes
   - Critical path highlighted in red
4) Exports to PNG, SVG, or PDF.

Usage:
    python cpm_network_diagram.py input.csv output.png
"""

import sys
import math
from dataclasses import dataclass, field
from typing import List, Dict, Set
import pandas as pd
from graphviz import Digraph


@dataclass
class Activity:
    id: str
    description: str
    duration: float
    predecessors: List[str] = field(default_factory=list)
    ES: float = 0.0
    EF: float = 0.0
    LS: float = 0.0
    LF: float = 0.0
    TF: float = 0.0


def _normalize_id(x) -> str:
    return str(x).strip()


def cpm_from_dataframe(df: pd.DataFrame) -> Dict[str, Activity]:
    """Compute CPM metrics given a DataFrame with columns:
       id, description, duration, predecessors
    """
    cols = {c.lower().strip(): c for c in df.columns}
    required = ["id", "description", "duration", "predecessors"]
    for r in required:
        if r not in cols:
            raise ValueError(f"Missing required column: {r}")

    acts: Dict[str, Activity] = {}
    for _, row in df.iterrows():
        aid = _normalize_id(row[cols["id"]])
        desc = str(row[cols["description"]])
        dur = float(row[cols["duration"]])
        preds_raw = str(row[cols["predecessors"]]) if not pd.isna(row[cols["predecessors"]]) else ""
        preds = [_normalize_id(p) for p in preds_raw.split(",") if _normalize_id(p) != ""]
        if aid in acts:
            raise ValueError(f"Duplicate activity id: {aid}")
        acts[aid] = Activity(id=aid, description=desc, duration=dur, predecessors=preds)

    # Validate references
    for a in acts.values():
        for p in a.predecessors:
            if p not in acts:
                raise ValueError(f"Activity {a.id} has unknown predecessor: {p}")

    # Build successors
    successors: Dict[str, List[str]] = {aid: [] for aid in acts}
    for a in acts.values():
        for p in a.predecessors:
            successors[p].append(a.id)

    # Topological sort
    in_deg: Dict[str, int] = {aid: 0 for aid in acts}
    for a in acts.values():
        for p in a.predecessors:
            in_deg[a.id] += 1

    frontier: List[str] = [aid for aid, d in in_deg.items() if d == 0]
    topo: List[str] = []
    while frontier:
        n = frontier.pop(0)
        topo.append(n)
        for s in successors[n]:
            in_deg[s] -= 1
            if in_deg[s] == 0:
                frontier.append(s)

    if len(topo) != len(acts):
        raise ValueError("Cycle detected in activity network; CPM requires a DAG.")

    # Forward pass
    for aid in topo:
        a = acts[aid]
        a.ES = max((acts[p].EF for p in a.predecessors), default=0)
        a.EF = a.ES + a.duration

    project_duration = max(a.EF for a in acts.values()) if acts else 0.0

    # Backward pass
    LF_map: Dict[str, float] = {aid: (project_duration if not successors[aid] else math.inf) for aid in acts}
    LS_map: Dict[str, float] = {}

    for aid in reversed(topo):
        a = acts[aid]
        if successors[aid]:
            lf = min(LS_map[sid] for sid in successors[aid])
        else:
            lf = project_duration
        ls = lf - a.duration
        LF_map[aid] = lf
        LS_map[aid] = ls

    for aid, a in acts.items():
        a.LF = LF_map[aid]
        a.LS = LS_map[aid]
        a.TF = a.LS - a.ES

    return acts


def _escape_html(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _fmt(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.2f}"


def _node_label_html(a: Activity) -> str:
    es, ef, ls, lf, dur, tf = map(_fmt, [a.ES, a.EF, a.LS, a.LF, a.duration, a.TF])
    desc_html = _escape_html(a.description)
    return f"""<
<TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0">
  <TR>
    <TD>{es}</TD>
    <TD><B>{_escape_html(a.id)}</B><BR/>{desc_html}</TD>
    <TD>{ef}</TD>
  </TR>
  <TR>
    <TD>{ls}</TD>
    <TD>Dur: {dur}</TD>
    <TD>{lf}</TD>
  </TR>
  <TR>
    <TD COLSPAN="3">TF: {tf}</TD>
  </TR>
</TABLE>>"""


def draw_network(activities: Dict[str, Activity], filename: str, file_format: str = "png") -> str:
    """Draw the CPM network and return the rendered file path."""
    successors: Dict[str, List[str]] = {aid: [] for aid in activities}
    for a in activities.values():
        for p in a.predecessors:
            successors[p].append(a.id)

    dot = Digraph("CPM", format=file_format)
    dot.attr(rankdir="LR", splines="ortho", nodesep="0.6", ranksep="0.8")
    dot.attr("node", shape="plain", fontname="Helvetica")

    for aid, a in activities.items():
        color = "red" if abs(a.TF) < 1e-9 else "black"
        dot.node(aid, label=_node_label_html(a), color=color)

    for aid, a in activities.items():
        for p in a.predecessors:
            edge_color = "red" if abs(activities[p].TF) < 1e-9 and abs(a.TF) < 1e-9 else "black"
            dot.edge(p, aid, color=edge_color)

    return dot.render(filename=filename, cleanup=True)


def run_from_csv(csv_path: str, out_path: str) -> str:
    df = pd.read_csv(csv_path)
    if "predecessors" not in {c.lower() for c in df.columns}:
        df["predecessors"] = ""
    acts = cpm_from_dataframe(df)
    if "." in out_path:
        fname, fmt = out_path.rsplit(".", 1)
    else:
        fname, fmt = out_path, "png"
    return draw_network(acts, filename=fname, file_format=fmt)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        csv_in = sys.argv[1]
        out = sys.argv[2]
        final_path = run_from_csv(csv_in, out)
        print(f"Saved: {final_path}")
    else:
        # Demo
        demo_data = [
            {"id": "A", "description": "Kickoff", "duration": 1, "predecessors": ""},
            {"id": "B", "description": "Design", "duration": 5, "predecessors": "A"},
            {"id": "C", "description": "Procurement", "duration": 4, "predecessors": "A"},
            {"id": "D", "description": "Implementation", "duration": 7, "predecessors": "B,C"},
            {"id": "E", "description": "Testing", "duration": 3, "predecessors": "D"},
        ]
        df_demo = pd.DataFrame(demo_data)
        acts_demo = cpm_from_dataframe(df_demo)
        path = draw_network(acts_demo, filename="network_demo", file_format="png")
        print(f"Demo saved to: {path}")
