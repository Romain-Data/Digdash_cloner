"""
digdash_cloner/services/backup_validator.py
Service pour valider le backup généré.
Suit les principes SRP (validation uniquement), OCP (extensible pour d'autres règles), DIP (dépend d'abstractions).
"""

import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from typing import List


class BackupValidator:
    """
    Valide la validité XML et les références du backup généré.
    Suit DIP en travaillant avec des abstractions.
    """

    def validate_output(self, output_path: str, congress_list: List[str], dst_year: str) -> bool:
        """Vérifie la validité XML et les références entre modèles et flux."""
        errors = []
        warnings = []

        with zipfile.ZipFile(output_path) as zf:
            # 1. Validité XML
            for name in zf.namelist():
                if name.endswith(".xml") or name.endswith(".iwt"):
                    try:
                        ET.fromstring(zf.read(name))
                    except Exception as e:
                        errors.append(f"XML invalide : {name} → {e}")

            # 2. Vérification des références DM dans les flux clonés
            dm_root = ET.fromstring(
                zf.read(next(n for n in zf.namelist() if "tabledatamodel" in n))
            )
            wl_root = ET.fromstring(zf.read(next(n for n in zf.namelist() if n.endswith(".iwt"))))

            dm_ids_by_year = defaultdict(set)
            for m in dm_root.findall("TableDataModel"):
                name = m.get("name", "")
                for year in ("2024", "2025", "2026", "2027"):
                    if year in name:
                        dm_ids_by_year[year].add(m.get("id"))

            dst_dm_ids = dm_ids_by_year[dst_year]
            other_dm_ids = set()
            for y, ids in dm_ids_by_year.items():
                if y != dst_year:
                    other_dm_ids |= ids

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

        ok = len(errors) == 0
        print("\n── Validation ──────────────────────────────────────────────────────")
        if ok:
            print("  ✅ Tous les fichiers XML/IWT sont valides")
        else:
            for e in errors:
                print(f"  ❌ {e}")
        for w in warnings:
            print(f"  ⚠️  {w}")
        return ok
