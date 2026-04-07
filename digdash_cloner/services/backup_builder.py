"""
digdash_cloner/services/backup_builder.py
Service pour assembler le backup final avec les éléments clonés.
Suit les principes SRP (assemblage uniquement), OCP (extensible pour d'autres intégrations), DIP (dépend d'abstractions).
"""

from __future__ import annotations

import copy
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import TYPE_CHECKING

from ..utils.xml_utils import log, serialize

if TYPE_CHECKING:
    from ..models.backup import Backup
    from ..models.clone_result import CloneResult


class BackupBuilder:
    """
    Assemble le ZIP final en intégrant les éléments clonés.
    Suit DIP en dépendant des modèles et utilitaires.
    """

    def _append_models(self, result, new_dm_root, dm_file):
        for m in result.cloned_models:
            new_dm_root.append(m)
        if dm_file is not None:
            for m in result.cloned_models:
                item = ET.SubElement(dm_file, "item")
                item.set("id", m.get("id"))
                item.set("name", m.get("name", ""))

    def _append_flows(self, result, new_wl_root, wl_file):
        for f in result.cloned_flows:
            new_wl_root.append(f)
        if wl_file is not None:
            for f in result.cloned_flows:
                cat = f.find("Category")
                cat_name = cat.get("Name", "") if cat is not None else ""
                item = ET.SubElement(wl_file, "item")
                item.set("id", f.get("uid"))
                item.set("name", f"{cat_name}/{f.get('name', '')}")

    def _append_pages(self, result, new_db_root, db_file):
        for p in result.cloned_pages:
            new_db_root.append(p)
        if db_file is not None:
            for p in result.cloned_pages:
                item = ET.SubElement(db_file, "item")
                item.set("id", p.get("uid"))
                item.set("name", p.get("id", ""))

    def build_backup(
        self,
        backup: Backup,
        clone_results: list[CloneResult],
        output_path: str,
        verbose: bool = False,
    ) -> str:
        """
        Assemble le ZIP final en intégrant tous les éléments clonés
        dans le rôle existant.
        """
        role_id = backup.role_id
        ts = str(int(time.time() * 1000))

        # ── Construire les nouveaux arbres XML ────────────────────────────────────
        new_dm_root = copy.deepcopy(backup.dm_root)
        new_wl_root = copy.deepcopy(backup.wl_root)
        new_db_root = copy.deepcopy(backup.db_root)
        new_bk_root = copy.deepcopy(backup.bk_root)

        new_dm_root.set("version", new_dm_root.get("version", ""))
        new_wl_root.set("lastedit", ts)
        new_db_root.set("lastedit", ts)
        new_bk_root.set("lastedit", ts)

        # Localiser les nœuds <file> dans backup.xml
        wl_file = db_file = dm_file = None
        for fnode in new_bk_root.findall(".//file"):
            dest = fnode.get("dest", "")
            if f"wallet_{role_id}" in dest:
                wl_file = fnode
            elif f"tabledatamodelrepository_{role_id}" in dest:
                dm_file = fnode
            elif f"dashboard_{role_id}" in dest:
                db_file = fnode

        # ── Intégrer chaque résultat de clonage ───────────────────────────────────
        for result in clone_results:
            if result is None:
                continue
            congress = result.congress
            dst_year = result.dst_year
            log(f"Intégration {congress}/{dst_year}...", verbose)

            self._append_models(result, new_dm_root, dm_file)
            self._append_flows(result, new_wl_root, wl_file)
            self._append_pages(result, new_db_root, db_file)

        # ── Sérialisation ─────────────────────────────────────────────────────────
        dm_bytes = serialize(
            new_dm_root,
            '<?xml-stylesheet type="text/xsl" href="staticwebcontent/tools/dminfo.xsl"?>',
        )
        wl_bytes = serialize(
            new_wl_root,
            '<?xml-stylesheet type="text/xsl" href="staticwebcontent/tools/walletinfo.xsl"?>',
        )
        db_bytes = serialize(new_db_root)
        bk_bytes = serialize(new_bk_root)

        # ── Construction du ZIP ───────────────────────────────────────────────────
        dm_key = backup.dm_key
        wl_key = backup.wl_key
        db_key = backup.db_key
        bk_key = backup.bk_key

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in backup.all_files.items():
                if name in (bk_key, dm_key, wl_key, db_key):
                    continue  # remplacés ci-dessous
                zf.writestr(name, content)

            zf.writestr(bk_key, bk_bytes)
            zf.writestr(dm_key, dm_bytes)
            zf.writestr(wl_key, wl_bytes)
            zf.writestr(db_key, db_bytes)

        log(f"ZIP écrit : {output_path}", verbose)
        return output_path
