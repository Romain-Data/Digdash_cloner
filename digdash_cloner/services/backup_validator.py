"""
digdash_cloner/services/backup_validator.py
Service pour valider le backup généré.
Suit les principes SRP (validation uniquement), OCP (extensible pour d'autres règles), DIP (dépend d'abstractions).
"""

from __future__ import annotations

import re
import zipfile
from collections import defaultdict

from defusedxml.ElementTree import ParseError
from defusedxml.ElementTree import fromstring as safe_fromstring


class BackupValidator:
    """
    Valide la validité XML et les références du backup généré.
    Suit DIP en travaillant avec des abstractions.
    """

    def validate_output(self, output_path: str, congress_list: list[str], dst_year: str) -> bool:
        """Vérifie la validité XML et les références entre modèles et flux."""
        with zipfile.ZipFile(output_path) as zf:
            errors = self._validate_xml_files(zf)
            dm_root, wl_root = self._load_roots(zf)
            warnings = self._collect_warnings(dm_root, wl_root, congress_list, dst_year)

        ok = len(errors) == 0
        print("\n-- Validation ------------------------------------------------------")
        if ok:
            print("  [OK] Tous les fichiers XML/IWT sont valides")
        else:
            for e in errors:
                print(f"  [ERROR] {e}")
        for w in warnings:
            print(f"  [WARN] {w}")
        return ok

    def _validate_xml_files(self, zf) -> list[str]:
        errors = []
        for name in zf.namelist():
            if name.endswith((".xml", ".iwt")):
                try:
                    safe_fromstring(zf.read(name))
                except (ParseError, ValueError) as e:
                    errors.append(f"XML invalide : {name} → {e}")
        return errors

    def _load_roots(self, zf):
        dm_root = safe_fromstring(zf.read(next(n for n in zf.namelist() if "tabledatamodel" in n)))
        wl_root = safe_fromstring(zf.read(next(n for n in zf.namelist() if n.endswith(".iwt"))))
        return dm_root, wl_root

    def _collect_warnings(
        self, dm_root, wl_root, congress_list: list[str], dst_year: str
    ) -> list[str]:
        dm_ids_by_year = self._build_dm_ids_by_year(dm_root)
        other_dm_ids = self._other_dm_ids(dm_ids_by_year, dst_year)
        return self._find_bad_flow_references(wl_root, congress_list, dst_year, other_dm_ids)

    def _build_dm_ids_by_year(self, dm_root):
        dm_ids_by_year = defaultdict(set)
        for m in dm_root.findall("TableDataModel"):
            name = m.get("name", "")
            years = re.findall(r"\b20\d{2}\b", name)
            for year in years:
                dm_ids_by_year[year].add(m.get("id"))
        return dm_ids_by_year

    def _other_dm_ids(self, dm_ids_by_year, dst_year: str) -> set[str]:
        other_dm_ids = set()
        for y, ids in dm_ids_by_year.items():
            if y != dst_year:
                other_dm_ids |= ids
        return other_dm_ids

    def _find_bad_flow_references(
        self,
        wl_root,
        congress_list: list[str],
        dst_year: str,
        other_dm_ids: set[str],
    ) -> list[str]:
        warnings = []
        for congress in congress_list:
            dst_prefix = f"{congress}/{dst_year}/" if congress else f"{dst_year}/"
            bad_flows = []
            for f in wl_root.findall("Flow"):
                cat = f.find("Category")
                cat_name = cat.get("Name", "") if cat is not None else ""
                if not cat_name.startswith(dst_prefix):
                    continue
                for inp in f.findall("Input"):
                    if inp.get("id") == "1":
                        dm_ref = inp.get("value", "")
                        if dm_ref in other_dm_ids:
                            bad_flows.append(f.get("name", ""))
            if bad_flows:
                warnings.append(
                    f"{congress}/{dst_year} : {len(bad_flows)} flux pointent vers "
                    f"un DM d'une autre année (vérifier manuellement)"
                )
        return warnings
