"""
CPM Network Diagram Generator

What this script does
---------------------
1) Reads activity data (ID, description, duration, predecessors) from a pandas DataFrame or CSV.
2) Computes Critical Path Method (CPM) fields for each activity:
   - ES (Earliest Start), EF (Earliest Finish), LS (Latest Start), LF (Latest Finish), TF (Total Float)
3) Draws a left-to-right network diagram using Graphviz with compact 3x3 node grids:

       ES |  Activity (ID + description)  | EF
       LS |           Duration             | LF
        -----------  TF: value  -----------

   - Critical activities (TF == 0) are shown in red.
4) Exports to PNG or SVG.

Dependencies
------------
- python >= 3.9
- pandas
- graphviz  (Python package) and Graphviz system binaries (dot)

Install:
    pip install pandas graphviz
    # On Ubuntu/Debian:
    sudo apt-get update && sudo apt-get install graphviz

Usage (CLI):
------------
    python cpm_network_diagram.py input.csv output.png

CSV format:
-----------
Required columns (case-insensitive):
- id : activity ID (string or int)
- description : short text
- duration : integer or float (days)
- predecessors : comma-separated list of predecessor IDs (empty if none)

Example CSV rows:
    id,description,duration,predecessors
    A,Kickoff,1,
    B,Design,5,A
    C,Procurement,4,A
    D,Implementation,7,B,C
    E,Testing,3,D

Programmatic use:
-----------------
from cpm_network_diagram import cpm_from_dataframe, draw_network

"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Iterable, Tuple, Optional, Set

import pandas as pd

try:
    from graphviz import Digraph
except ImportError as e:
    raise SystemExit(
        "Missing dependency: graphviz.\nInstall with `pip install graphviz` and ensure Graphviz binaries are installed (e.g., `sudo apt-get install graphviz`)."
    )


@dataclass
class Activity:
    id: str
    description: str
    duration: float
    predecessors: List[str] = field(default_factory=list)
    # CPM results (computed)
    ES: float = 0.0
    EF: float = 0.0
    LS: float = 0.0
    LF: float = 0.0
    TF: float = 0.0


def _normalize_id(x) -> str:
    return str(x).strip()


def cpm_from_dataframe(df: pd.DataFrame) -> Dict[str, Activity]:
    """
    Compute CPM metrics given a DataFrame with columns:
        id, description, duration, predecessors
    Returns a dict mapping activity id -> Activity (with ES, EF, LS, LF, TF populated).
    """
    # Normalize columns
    cols = {c.lower().strip(): c for c in df.columns}
    required = ["id", "description", "duration", "predecessors"]
    for r in required:
        if r not in cols:
            raise ValueError(f"Missing required column: {r}")

    # Build activities
    acts: Dict[str, Activity] = {}
    for _, row in df.iterrows():
        aid = _normalize_id(row[cols["id"]])
        desc = str(row[cols["description"]])
        dur = float(row[cols["duration"]])
        preds_raw = str(row[cols["predecessors"]]) if not pd.isna(row[cols["predecessors"]]) else ""
        preds = [
            _normalize_id(p)
            for p in preds_raw.split(",")
            if _normalize_id(p) != ""
        ]
        if aid in acts:
            raise ValueError(f"Duplicate activity id: {aid}")
        acts[aid] = Activity(id=aid, description=desc, duration=dur, predecessors=preds)

    # Validate predecessor references
    for a in acts.values():
        for p in a.predecessors:
            if p not in acts:
                raise ValueError(f"Activity {a.id} has unknown predecessor: {p}")

    # Build successors map
    successors: Dict[str, List[str]] = {aid: [] for aid in acts}
    for a in acts.values():
        for p in a.predecessors:
            successors[p].append(a.id)

    # Topological order (Kahn's algorithm)
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

    # Forward pass: ES, EF
    for aid in topo:
        a = acts[aid]
        if a.predecessors:
            a.ES = max(acts[p].EF for p in a.predecessors)
        else:
            a.ES = 0.0
        a.EF = a.ES + a.duration

    project_duration = max(a.EF for a in acts.values()) if acts else 0.0

    # Backward pass: LF, LS
    # Initialize terminal activities (no successors)
    terminal: Set[str] = {aid for aid, succs in successors.items() if len(succs) == 0}

    LF_map: Dict[str, float] = {aid: (project_duration if aid in terminal else math.inf) for aid in acts}
    LS_map: Dict[str, float] = {}

    for aid in reversed(topo):
        a = acts[aid]
        if aid not in terminal:
            # LF is min of successors' LS
            lf = min(LS_map[sid] for sid in successors[aid])
        else:
            lf = project_duration
        ls = lf - a.duration
        LF_map[aid] = lf
        LS_map[aid] = ls

    # Assign and compute TF
    for aid, a in acts.items():
        a.LF = LF_map[aid]
        a.LS = LS_map[aid]
        a.TF = a.LS - a.ES

    return acts


def _node_label_html(a: Activity) -> str:
    """Create an HTML-like label for Graphviz with a 3x3 grid + TF row."""
    es = _fmt(a.ES)
    ef = _fmt(a.EF)
    ls = _fmt(a.LS)
    lf = _fmt(a.LF)
    dur = _fmt(a.duration)
    tf = _fmt(a.TF)

    desc = (a.description or "").strip()
    # Keep description concise in node; Graphviz handles line breaks with <BR/>
    desc_html = _escape_html(desc)

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


def _escape_html(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


def _fmt(x: float) -> str:
    # Show integers without .0
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.2f}"


def draw_network(
    activities: Dict[str, Activity],
    filename: str = "network_diagram",
    file_format: str = "png",
    rankdir: str = "LR",
    highlight_critical: bool = True,
    fontname: str = "Helvetica",
    node_margin: str = "0.06,0.06",
) -> str:
    """
    Draw the CPM network using Graphviz and return the rendered file path.

    Parameters
    ----------
    activities : Dict[str, Activity]
        Activities with CPM fields computed (use cpm_from_dataframe first).
    filename : str
        Output path without extension (Graphviz appends extension based on format).
    file_format : str
        'png', 'svg', 'pdf', etc.
    rankdir : str
        'LR' for left-to-right (default) or 'TB' for top-to-bottom.
    highlight_critical : bool
        If True, color TF==0 nodes and edges in red.
    fontname : str
        Font for node labels.
    node_margin : str
        Node margin (width,height) for Graphviz to avoid cramped content.
    """
    # Build successors for edges
    successors: Dict[str, List[str]] = {aid: [] for aid in activities}
    for a in activities.values():
        for p in a.predecessors:
            successors[p].append(a.id)

    dot = Digraph("CPM", format=file_format)
    dot.attr(rankdir=rankdir)
    dot.attr("node", shape="plain", fontname=fontname, margin=node_margin)

    # Add nodes
    for aid, a in activities.items():
        color = "red" if highlight_critical and abs(a.TF) < 1e-9 else "black"
        dot.node(aid, label=_node_label_html(a), color=color)

    # Add edges
    for aid, a in activities.items():
        for p in a.predecessors:
            edge_color = "red" if highlight_critical and (abs(activities[p].TF) < 1e-9 and abs(a.TF) < 1e-9) else "black"
            dot.edge(p, aid, color=edge_color)

    outpath = dot.render(filename=filename, cleanup=True)
    return outpath


def dataframe_from_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    # Ensure required columns exist; create predecessors if absent
    if "predecessors" not in {c.lower(): c for c in df.columns}.keys():
        df["predecessors"] = ""
    return df


def run_from_csv(csv_path: str, out_path: str) -> str:
    df = dataframe_from_csv(csv_path)
    acts = cpm_from_dataframe(df)
    # Infer format from extension
    if "." in out_path:
        fname, fmt = out_path.rsplit(".", 1)
    else:
        fname, fmt = out_path, "png"
    return draw_network(acts, filename=fname, file_format=fmt)


# Example usage with inline data
if __name__ == "__main__":
    if len(sys.argv) >= 3:
        csv_in = sys.argv[1]
        out = sys.argv[2]
        final_path = run_from_csv(csv_in, out)
        print(f"Saved: {final_path}")
    else:
        # Demo dataset
        data = [
            {"id": "A", "description": "Kickoff", "duration": 1, "predecessors": ""},
            {"id": "B", "description": "Design", "duration": 5, "predecessors": "A"},
            {"id": "C", "description": "Procurement", "duration": 4, "predecessors": "A"},
            {"id": "D", "description": "Implementation", "duration": 7, "predecessors": "B,C"},
            {"id": "E", "description": "Testing", "duration": 3, "predecessors": "D"},
        ]
        df_demo = pd.DataFrame(data)
        acts_demo = cpm_from_dataframe(df_demo)
        path = draw_network(acts_demo, filename="network_demo", file_format="png")
        print(f"Demo saved to: {path}")
