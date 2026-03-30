"""
digdash_cloner/services/congress_cloner.py
Service pour cloner un congrès d'une année à une autre.
Suit les principes SRP (clonage uniquement), OCP (extensible pour d'autres types d'éléments), DIP (dépend d'interfaces abstraites).
"""

import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

from ..models.backup import Backup
from ..models.clone_result import CloneResult
from ..utils.uid_generators import uid_hex, uid_int
from ..utils.xml_utils import log
from .dependency_resolver import DependencyResolver


class CongressCloner:
    """
    Responsable du clonage d'un congrès.
    Utilise DIP en dépendant de DependencyResolver et des utilitaires.
    """

    def __init__(self, dependency_resolver: DependencyResolver):
        self.dependency_resolver = dependency_resolver

    def clone_congress(
        self,
        backup: Backup,
        congress: str,
        src_year: str,
        dst_year: str,
        csv_path_mode: str,  # "replace" | "keep" | "empty"
        verbose: bool = False,
    ) -> Optional[CloneResult]:
        """
        Clone tous les flux, modèles et pages d'un congrès d'une année source
        vers une année cible.

        Retourne un CloneResult ou None si aucun flux trouvé.
        """

        role_id = backup.role_id
        dm_root = backup.dm_root
        wl_root = backup.wl_root
        db_root = backup.db_root
        ts = str(int(time.time() * 1000))

        all_models = {m.get("id"): m for m in dm_root.findall("TableDataModel")}
        all_flows = wl_root.findall("Flow")

        salt = f"{congress}{dst_year}"  # sel déterministe par congrès/année

        # ── 1. Identifier les flux à cloner ──────────────────────────────────────
        if congress:
            src_prefix = f"{congress}/{src_year}/"
            label = f"{congress}/{src_year}"
        else:
            src_prefix = f"{src_year}/"
            label = src_year

        flows_to_clone = []
        for f in all_flows:
            cat = f.find("Category")
            cat_name = cat.get("Name", "") if cat is not None else ""
            if cat_name.startswith(src_prefix) or cat_name == src_year:
                dm_id = None
                for inp in f.findall("Input"):
                    if inp.get("id") == "1":
                        dm_id = inp.get("value", "").strip()
                        break
                flows_to_clone.append((f, cat_name, dm_id))

        log(f"[{label}] Flux à cloner : {len(flows_to_clone)}", verbose)
        if not flows_to_clone:
            target = f"{congress}/{src_year}/" if congress else f"{src_year}[/...] ou {src_year}"
            print(f"  ⚠️  Aucun flux trouvé pour {target}")
            return None

        # ── 2. Résolution des dépendances de modèles ─────────────────────────────
        all_dm_ids = set()
        for f, cat, dm_id in flows_to_clone:
            if dm_id:
                all_dm_ids |= self.dependency_resolver.resolve_deps(dm_id, all_models)

        dm_to_clone = {
            dm_id
            for dm_id in all_dm_ids
            if dm_id in all_models and src_year in all_models[dm_id].get("name", "")
        }
        dm_shared = all_dm_ids - dm_to_clone

        log(
            f"[{label}] Modèles à cloner : {len(dm_to_clone)}, partagés : {len(dm_shared)}", verbose
        )

        # ── 3. Mappings IDs ───────────────────────────────────────────────────────
        id_map = {old: uid_hex(old, salt) for old in dm_to_clone}
        for s in dm_shared:
            id_map[s] = s

        flow_uid_map = {f.get("uid"): uid_int(f.get("uid"), salt) for f, _, _ in flows_to_clone}

        # ── 4. Cloner les modèles ─────────────────────────────────────────────────
        cloned_models = []
        for old_id in dm_to_clone:
            if old_id not in all_models:
                continue
            raw = ET.tostring(all_models[old_id], encoding="unicode")

            raw = raw.replace(f'id="{old_id}"', f'id="{id_map[old_id]}"', 1)

            for old, new in id_map.items():
                if old != new:
                    raw = raw.replace(f'Link="{old}"', f'Link="{new}"')

            if csv_path_mode == "replace":
                raw = raw.replace(src_year, dst_year)
            elif csv_path_mode == "empty":
                raw = re.sub(r'Path="[^"]*"', 'Path=""', raw)
                raw = raw.replace(src_year, dst_year)
            elif csv_path_mode == "keep":
                paths = re.findall(r'(?:Path|Name)="[^"]*"', raw)
                placeholders = {p: f"__PATH_{i}__" for i, p in enumerate(paths)}
                for p, ph in placeholders.items():
                    raw = raw.replace(p, ph)
                raw = raw.replace(src_year, dst_year)
                for p, ph in placeholders.items():
                    raw = raw.replace(ph, p)

            m2 = ET.fromstring(raw)
            m2.set("lastedit", ts)
            cloned_models.append(m2)

        log(f"[{label}] Modèles clonés : {len(cloned_models)}", verbose)

        # ── 5. Cloner les flux ────────────────────────────────────────────────────
        dst_prefix = f"{congress}/{dst_year}/"
        cloned_flows = []
        for f, cat_name, dm_id in flows_to_clone:
            raw = ET.tostring(f, encoding="unicode")
            old_uid = f.get("uid")

            raw = raw.replace(f'uid="{old_uid}"', f'uid="{flow_uid_map[old_uid]}"')

            for old, new in id_map.items():
                if old != new:
                    raw = raw.replace(f'value="{old}"', f'value="{new}"')
                    raw = raw.replace(f'dmId="{old}"', f'dmId="{new}"')

            if congress:
                raw = raw.replace(f"{congress}/{src_year}/", f"{congress}/{dst_year}/")
            else:
                raw = raw.replace(f"{src_year}/", f"{dst_year}/")
                raw = raw.replace(f'Name="{src_year}"', f'Name="{dst_year}"')
            raw = raw.replace(src_year, dst_year)

            f2 = ET.fromstring(raw)
            f2.set("lastedit", ts)
            f2.set("group", role_id)
            cloned_flows.append(f2)

        log(f"[{label}] Flux clonés : {len(cloned_flows)}", verbose)

        # ── 6. Pages dashboard ────────────────────────────────────────────────────
        src_flow_uids = set(flow_uid_map.keys())

        pages_to_clone = []
        seen_page_uids = set()
        for d in db_root.findall("Dashboard"):
            for base in d.findall('.//Base[@type="flow"]'):
                if base.get("flowId", "") in src_flow_uids:
                    uid = d.get("uid")
                    if uid not in seen_page_uids:
                        seen_page_uids.add(uid)
                        pages_to_clone.append(d)
                    break

        page_uid_map = {d.get("uid"): uid_int(d.get("uid"), f"page{salt}") for d in pages_to_clone}
        portlet_uid_map = {}
        for d in pages_to_clone:
            for base in d.findall(".//Base"):
                puid = base.get("uid", "")
                if puid:
                    portlet_uid_map[puid] = uid_int(puid, f"portlet{salt}")

        cloned_pages = []
        for d in pages_to_clone:
            raw = ET.tostring(d, encoding="unicode")
            raw = raw.replace(f'uid="{d.get("uid")}"', f'uid="{page_uid_map[d.get("uid")]}"')
            for old, new in portlet_uid_map.items():
                raw = raw.replace(f'uid="{old}"', f'uid="{new}"')
            for old, new in flow_uid_map.items():
                raw = raw.replace(f'flowId="{old}"', f'flowId="{new}"')
            raw = raw.replace(src_year, dst_year)
            d2 = ET.fromstring(raw)
            d2.set("lastedit", ts)
            cloned_pages.append(d2)

        log(f"[{label}] Pages clonées : {len(cloned_pages)}", verbose)

        return CloneResult(
            congress=congress,
            src_year=src_year,
            dst_year=dst_year,
            cloned_models=cloned_models,
            cloned_flows=cloned_flows,
            cloned_pages=cloned_pages,
            id_map=id_map,
            flow_uid_map=flow_uid_map,
            page_uid_map=page_uid_map,
        )
