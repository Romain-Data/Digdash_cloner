#!/usr/bin/env python3
"""
Show the dashboard hierarchy inside a DigDash backup ZIP.

Usage:
  python tools/show_dashboard_hierarchy.py backup_clone.zip

Output: a readable tree of role -> year -> pages with uid and type.
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from typing import Dict, List


def extract_dashboards(zip_path: str) -> List[ET.Element]:
    dashboards: List[ET.Element] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if "dashboard" in name.lower():
                try:
                    raw = zf.read(name)
                except Exception:
                    continue
                try:
                    data = raw.decode("utf-8")
                except Exception:
                    data = raw.decode("utf-8", errors="ignore")
                try:
                    root = ET.fromstring(data)
                except Exception:
                    continue
                for d in root.findall(".//Dashboard"):
                    dashboards.append(d)
    return dashboards


def build_maps(dashboards: List[ET.Element]):
    uid_map: Dict[str, ET.Element] = {}
    children: Dict[str, List[str]] = defaultdict(list)
    refs: Dict[str, List[str]] = defaultdict(list)
    roots: List[str] = []

    for d in dashboards:
        uid = d.get("uid")
        if not uid:
            continue
        uid_map[uid] = d

    for uid, d in uid_map.items():
        parent = d.get("parent") or ""
        # If parent is empty or parent is not present in uid_map, treat as root (orphan)
        if not parent or parent not in uid_map:
            roots.append(uid)
        else:
            children[parent].append(uid)
        # collect DashboardRef links if present
        for ref in d.findall("DashboardRef"):
            link = ref.get("link")
            if link:
                refs[uid].append(link)

    return uid_map, children, refs, roots


def print_tree(uid_map, children, refs, roots):
    visited = set()

    def render(uid: str, indent: int = 0):
        if uid in visited:
            print("  " * indent + f"- [cycle] {uid}")
            return
        visited.add(uid)
        d = uid_map.get(uid)
        if d is None:
            print("  " * indent + f"- [missing] {uid}")
            return
        label = d.get("id") or "<no-id>"
        t = d.get("type") or ""
        parent = d.get("parent") or ""
        note = ""
        if parent and parent not in uid_map:
            note = " [parent missing]"
        print("  " * indent + f"- {label} (uid={uid}{', ' + t if t else ''}){note}")
        # prefer DashboardRef ordering when present, but also render any other children
        order = refs.get(uid) or []
        rendered = set()
        for child_uid in order:
            render(child_uid, indent + 1)
            rendered.add(child_uid)
        for child_uid in children.get(uid, []):
            if child_uid in rendered:
                continue
            render(child_uid, indent + 1)

    # print each root (top-level container)
    for r in roots:
        render(r)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("zip", help="path to backup zip")
    args = p.parse_args()

    dashboards = extract_dashboards(args.zip)
    if not dashboards:
        print("No dashboard files found in", args.zip)
        return
    uid_map, children, refs, roots = build_maps(dashboards)
    print(f"Found {len(dashboards)} Dashboard elements, {len(roots)} top-level containers")
    print_tree(uid_map, children, refs, roots)


if __name__ == "__main__":
    main()
