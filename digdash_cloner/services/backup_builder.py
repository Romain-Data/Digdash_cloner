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
                cat = m.find("Category")
                cat_name = cat.get("Name", "").strip("/") if cat is not None else ""
                item_name = f"{cat_name}/{m.get('name', '')}" if cat_name else m.get("name", "")
                item = ET.SubElement(dm_file, "item")
                item.set("id", m.get("id"))
                item.set("name", item_name)

    def _append_flows(self, result, new_wl_root, wl_file):
        for f in result.cloned_flows:
            new_wl_root.append(f)
        if wl_file is not None:
            for f in result.cloned_flows:
                cat = f.find("Category")
                cat_name = cat.get("Name", "").strip("/") if cat is not None else ""
                item_name = f"{cat_name}/{f.get('name', '')}" if cat_name else f.get("name", "")
                item = ET.SubElement(wl_file, "item")
                item.set("id", f.get("uid"))
                item.set("name", item_name)

    def _append_pages(self, result, new_db_root, db_file):
        for p in result.cloned_pages:
            # Avoid appending pages that would collide by uid with existing pages
            uid = p.get("uid")
            if uid and any(
                existing.get("uid") == uid for existing in new_db_root.findall("Dashboard")
            ):
                log(f"Skipping append of page uid={uid} (already present)", False)
                continue
            new_db_root.append(p)
        if db_file is not None:
            # Build uid map of all dashboards in the new tree
            uid_to_dashboard = {
                d.get("uid"): d for d in new_db_root.findall("Dashboard") if d.get("uid")
            }

            def get_page_path(d_elem, uid_map=uid_to_dashboard) -> str:
                path_parts = []
                curr = d_elem
                visited = set()
                while curr is not None:
                    uid = curr.get("uid")
                    if not uid or uid in visited:
                        break
                    visited.add(uid)
                    path_parts.append(curr.get("id", ""))
                    parent_uid = curr.get("parent")
                    curr = uid_map.get(parent_uid) if parent_uid else None
                return "/".join(reversed(path_parts))

            for p in result.cloned_pages:
                uid = p.get("uid")
                name = get_page_path(p)
                # Avoid duplicating the item entry in the backup manifest
                if uid and any(item.get("id") == uid for item in db_file.findall("item")):
                    log(f"Skipping db manifest entry for uid={uid} (already present)", False)
                    continue
                item = ET.SubElement(db_file, "item")
                item.set("id", uid)
                item.set("name", name)

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
