#!/usr/bin/env python3
"""
Compare two DigDash backup ZIPs and report Dashboard id/uid/parent collisions.

Usage:
  python tools/compare_dashboards.py backup_origine.zip backup_clone.zip

Outputs:
  - counts and lists of UID collisions
  - ID+parent collisions
  - UIDs present in both but with different id/parent
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from typing import Dict, List


def extract_dashboards(zip_path: str) -> Dict[str, List[Dict[str, str]]]:
    info: Dict[str, List[Dict[str, str]]] = defaultdict(list)
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
                    try:
                        data = raw.decode("utf-8", errors="ignore")
                    except Exception:
                        continue
                try:
                    root = ET.fromstring(data)
                except Exception as e:
                    # best-effort fallback: collect lines containing <Dashboard
                    snippets = [
                        l for l in data.splitlines() if "<Dashboard" in l or "</Dashboard>" in l
                    ]
                    info[name].append({"parse_error": str(e), "snippet": "\n".join(snippets[:20])})
                    continue
                for d in root.findall(".//Dashboard"):
                    info[name].append(
                        {
                            "id": d.get("id"),
                            "uid": d.get("uid"),
                            "parent": d.get("parent"),
                            "type": d.get("type"),
                            "name": d.get("name"),
                        }
                    )
    return info


def main():
    p = argparse.ArgumentParser()
    p.add_argument("orig")
    p.add_argument("clone")
    args = p.parse_args()

    orig = extract_dashboards(args.orig)
    clone = extract_dashboards(args.clone)

    def summarize(label, data):
        total = sum(len(v) for v in data.values())
        print(f"{label}: {len(data)} files, {total} Dashboard entries")

    summarize("Original", orig)
    summarize("Clone   ", clone)

    orig_uids = set()
    clone_uids = set()
    orig_pairs = set()
    clone_pairs = set()

    for items in orig.values():
        for it in items:
            if it.get("uid"):
                orig_uids.add(it.get("uid"))
            orig_pairs.add((it.get("id"), it.get("parent")))

    for items in clone.values():
        for it in items:
            if it.get("uid"):
                clone_uids.add(it.get("uid"))
            clone_pairs.add((it.get("id"), it.get("parent")))

    uid_collisions = orig_uids & clone_uids
    pair_collisions = orig_pairs & clone_pairs

    print("\nUID collisions (same uid in both zips):", len(uid_collisions))
    for u in sorted(uid_collisions):
        print(u)

    print(
        "\nID+parent collisions (same id under same parent exist in both zips):",
        len(pair_collisions),
    )
    for p in sorted(pair_collisions):
        print(p)

    # UID present in both but different id/parent
    orig_map = {}
    for items in orig.values():
        for it in items:
            if it.get("uid"):
                orig_map[it.get("uid")] = (it.get("id"), it.get("parent"))

    mismatched = []
    for items in clone.values():
        for it in items:
            uid = it.get("uid")
            if not uid:
                continue
            if uid in orig_map and (it.get("id"), it.get("parent")) != orig_map[uid]:
                mismatched.append(
                    {"uid": uid, "orig": orig_map[uid], "clone": (it.get("id"), it.get("parent"))}
                )

    print("\nUID present in both but different id/parent count:", len(mismatched))
    for m in mismatched:
        print(m)


if __name__ == "__main__":
    main()
