"""
digdash_cloner/services/congress_cloner.py
Service pour cloner un congrès d'une année à une autre.
Suit les principes SRP (clonage uniquement), OCP (extensible pour d'autres types d'éléments), DIP (dépend d'interfaces abstraites).
"""

import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Optional

from ..models.backup import Backup
from ..models.clone_result import CloneResult
from ..utils.uid_generators import uid_hex, uid_int
from ..utils.xml_utils import log
from .dependency_resolver import DependencyResolver


def confirm(warning: str, abort_msg: str = "Opération annulée.") -> bool:
    """
    Affiche un avertissement et demande confirmation à l'utilisateur.
    Retourne True si l'utilisateur confirme, sys.exit(1) sinon.
    """
    print(f"\n  ⚠️  {warning}")
    while True:
        reply = input("     Continuer quand même ? [o/N] : ").strip().lower()
        if reply in ("o", "oui", "y", "yes"):
            return True
        if reply in ("n", "non", "", "no"):
            print(f"  {abort_msg}")
            sys.exit(1)


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

        # ── Sécurité 1 : doublons dst_year dans les flux ─────────────────────────
        dst_prefix = f"{dst_congress}/{dst_year}/" if dst_congress else f"{dst_year}/"
        existing_dst_flows = [
            f for f in all_flows
            if (f.find("Category") is not None)
            and f.find("Category").get("Name", "").startswith(dst_prefix)
        ]
        if existing_dst_flows:
            confirm(
                f"{len(existing_dst_flows)} flux existent déjà pour "
                f"{'%s/' % dst_congress if dst_congress else ''}{dst_year}. "
                f"Le clonage va créer des doublons dans le backup.",
                abort_msg="Clonage annulé. Vérifiez le backup source.",
            )

        # Sécurité 1b : doublons dst_year dans le dashboard
        _congress_uid_check = ""
        if dst_congress:
            for _p in db_root.findall("Dashboard"):
                if (
                    _p.get("id") == dst_congress
                    and _p.get("type") == "container"
                    and not _p.get("parent")
                ):
                    _congress_uid_check = _p.get("uid", "")
                    break
        existing_dst_db = [
            p for p in db_root.findall("Dashboard")
            if p.get("id") == dst_year
            and p.get("type") == "container"
            and p.get("parent", "") == _congress_uid_check
        ]
        if existing_dst_db:
            confirm(
                f"Un container dashboard '{dst_year}' existe déjà sous "
                f"{'%s' % dst_congress if dst_congress else '(racine)'}. "
                f"Le backup contiendra deux containers '{dst_year}' après le clonage. "
                f"Pensez à supprimer les pages dashboard {dst_year} avant de faire ce backup.",
                abort_msg="Clonage annulé. Nettoyez les pages dashboard puis refaites le backup.",
            )

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
            f"[{label}] Modèles à cloner : {len(dm_to_clone)}, partagés : {len(dm_shared)}",
            verbose,
        )

        # ── 3. Mappings IDs ───────────────────────────────────────────────────────
        id_map = {old: uid_hex(old, salt) for old in dm_to_clone}
        for s in dm_shared:
            id_map[s] = s

        flow_uid_map = {f.get("uid"): uid_int(f.get("uid"), salt) for f, _, _ in flows_to_clone}

        # ── Sécurité 2 : collisions d'UID ────────────────────────────────────────
        existing_dm_ids = set(all_models.keys())
        collisions = [
            new for old, new in id_map.items()
            if old != new and new in existing_dm_ids
        ]
        if collisions:
            confirm(
                f"{len(collisions)} ID(s) générés entrent en collision avec des modèles "
                f"existants : {collisions[:3]}{'...' if len(collisions) > 3 else ''}. "
                f"Cela peut corrompre des modèles existants.",
                abort_msg="Clonage annulé. Modifiez le sel (salt) ou contactez le support.",
            )

        existing_flow_uids = {f.get("uid") for f in all_flows}
        flow_uid_collisions = [
            new for old, new in flow_uid_map.items()
            if new in existing_flow_uids
        ]
        if flow_uid_collisions:
            confirm(
                f"{len(flow_uid_collisions)} UID(s) de flux générés entrent en collision "
                f"avec des flux existants. DigDash ne pourra pas distinguer les flux. "
                f"Cause probable : des flux {dst_year} existent déjà dans ce backup.",
                abort_msg="Clonage annulé. Supprimez les flux existants pour l'année cible.",
            )

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

            # Renommage congrès si nécessaire
            if congress and dst_congress != congress:
                raw = raw.replace(congress, dst_congress)

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

            if congress and dst_congress != congress:
                raw = raw.replace(congress, dst_congress)

            f2 = ET.fromstring(raw)
            f2.set("lastedit", ts)
            f2.set("group", role_id)
            cloned_flows.append(f2)

        log(f"[{label}] Flux clonés : {len(cloned_flows)}", verbose)

        # ── 6. Pages dashboard (hiérarchie complète) ─────────────────────────────
        #
        # On clone l'intégralité du sous-arbre de l'année source
        # (containers + feuilles), en corrigeant :
        #   - uid de chaque page  → nouveau UID
        #   - parent= dans le sous-arbre → nouveau UID du parent cloné
        #   - parent= du container année → UID du container congrès existant (inchangé)
        #   - flowId= → nouveau UID de flux
        #   - portlets uid → nouveau UID

        all_db_pages = db_root.findall("Dashboard")
        uid_to_page = {p.get("uid"): p for p in all_db_pages}
        children_map: dict = defaultdict(list)
        for p in all_db_pages:
            par = p.get("parent", "")
            if par:
                children_map[par].append(p)

        # Trouver le container congrès (racine, pas de parent, id == dst_congress)
        congress_container = None
        if dst_congress:
            for p in all_db_pages:
                if (
                    p.get("id") == dst_congress
                    and p.get("type") == "container"
                    and not p.get("parent")
                ):
                    congress_container = p
                    break

        congress_uid = congress_container.get("uid") if congress_container is not None else ""

        # Trouver le container année source sous le congrès source
        src_congress_uid = ""
        if congress and congress != dst_congress:
            for p in all_db_pages:
                if (
                    p.get("id") == congress
                    and p.get("type") == "container"
                    and not p.get("parent")
                ):
                    src_congress_uid = p.get("uid", "")
                    break
        else:
            src_congress_uid = congress_uid

        year_container = None
        for p in all_db_pages:
            if (
                p.get("id") == src_year
                and p.get("type") == "container"
                and p.get("parent", "") == src_congress_uid
            ):
                year_container = p
                break

        # Collecter récursivement le sous-arbre entier de l'année source
        def collect_subtree(uid: str) -> list:
            page = uid_to_page.get(uid)
            if page is None:
                return []
            result = [page]
            for child in sorted(
                children_map.get(uid, []),
                key=lambda x: int(x.get("position", "0") or "0"),
            ):
                result.extend(collect_subtree(child.get("uid")))
            return result

        if year_container is not None:
            pages_to_clone = collect_subtree(year_container.get("uid"))
            log(
                f"[{label}] Sous-arbre dashboard : {len(pages_to_clone)} éléments "
                f"(containers + feuilles)",
                verbose,
            )
        else:
            # Fallback : détection par flux (pas de container année trouvé)
            log(
                f"[{label}] Container '{src_year}' introuvable — fallback détection par flux",
                verbose,
            )
            src_flow_uids_set = set(flow_uid_map.keys())
            seen: set = set()
            pages_to_clone = []
            for d in all_db_pages:
                for base in d.findall('.//Base[@type="flow"]'):
                    if base.get("flowId", "") in src_flow_uids_set:
                        uid = d.get("uid")
                        if uid not in seen:
                            seen.add(uid)
                            pages_to_clone.append(d)
                        break

        # Nouveaux UIDs pour tout le sous-arbre
        page_uid_map = {
            p.get("uid"): uid_int(p.get("uid"), f"page{salt}")
            for p in pages_to_clone
        }

        # Portlets
        portlet_uid_map: dict = {}
        for d in pages_to_clone:
            for base in d.findall(".//Base"):
                puid = base.get("uid", "")
                if puid:
                    portlet_uid_map[puid] = uid_int(puid, f"portlet{salt}")

        # Cloner chaque élément du sous-arbre
        cloned_pages = []
        for d in pages_to_clone:
            raw = ET.tostring(d, encoding="unicode")
            old_uid = d.get("uid")

            # Nouveau UID de cette page (1re occurrence uniquement)
            raw = raw.replace(f'uid="{old_uid}"', f'uid="{page_uid_map[old_uid]}"', 1)

            # Mettre à jour l'attribut parent=
            old_parent = d.get("parent", "")
            if old_parent and old_parent in page_uid_map:
                # Parent dans le sous-arbre → pointe vers le nouveau UID du parent cloné
                raw = raw.replace(
                    f'parent="{old_parent}"',
                    f'parent="{page_uid_map[old_parent]}"',
                    1,
                )
            # Sinon (parent = container congrès ou absent) → on conserve l'uid existant

            # Portlets
            for old, new in portlet_uid_map.items():
                raw = raw.replace(f'uid="{old}"', f'uid="{new}"')

            # Références aux flux clonés
            for old, new in flow_uid_map.items():
                raw = raw.replace(f'flowId="{old}"', f'flowId="{new}"')

            # Année
            raw = raw.replace(src_year, dst_year)

            # Renommage congrès si nécessaire
            if congress and dst_congress != congress:
                raw = raw.replace(congress, dst_congress)

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
