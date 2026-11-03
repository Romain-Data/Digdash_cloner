"""
digdash_cloner/services/congress_cloner.py
Service pour cloner un congrès d'une année à une autre.
Suit les principes SRP (clonage uniquement), OCP (extensible pour d'autres types d'éléments), DIP (dépend d'interfaces abstraites).
"""

from __future__ import annotations

import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import TYPE_CHECKING

from defusedxml.ElementTree import fromstring as safe_fromstring

from ..models.clone_result import CloneResult
from ..utils.uid_generators import uid_hex, uid_int
from ..utils.xml_utils import log

if TYPE_CHECKING:
    from ..models.backup import Backup
    from .dependency_resolver import DependencyResolver


def confirm(warning: str, abort_msg: str = "Opération annulée.") -> bool:
    """
    Affiche un avertissement et demande confirmation à l'utilisateur.
    Retourne True si l'utilisateur confirme, sys.exit(1) sinon.
    """
    print(f"\n  [WARN] {warning}")
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

    def _compute_source_prefix(self, congress, src_year):
        if congress:
            return f"{congress}/{src_year}/", f"{congress}/{src_year}"
        return f"{src_year}/", src_year

    def _select_flows_to_clone(self, all_flows, congress, src_year):
        """
        Sélectionne les flux à cloner selon l'ordre de priorité des séparateurs :
        1. Séparateur slash '/' (ex: EuroPCR/2026, EuroPCR/2026/Registration)
        2. Séparateur tiret '-' (ex: EuroPCR-2026, EuroPCR-2026/Registration)
        Pour mono-congrès : '2026', '2026/...', '2026-...'
        """
        if congress:
            # Priorité 1 : Séparateur Slash '/'
            slash_flows = []
            prefix_slash = f"{congress}/{src_year}"
            for f in all_flows:
                cat = f.find("Category")
                cat_name = cat.get("Name", "") if cat is not None else ""
                if cat_name == prefix_slash or cat_name.startswith(f"{prefix_slash}/"):
                    dm_id = None
                    for inp in f.findall("Input"):
                        if inp.get("id") == "1":
                            dm_id = inp.get("value", "").strip()
                            break
                    slash_flows.append((f, cat_name, dm_id))
            if slash_flows:
                return slash_flows, "/"

            # Priorité 2 : Séparateur Tiret '-'
            dash_flows = []
            prefix_dash = f"{congress}-{src_year}"
            for f in all_flows:
                cat = f.find("Category")
                cat_name = cat.get("Name", "") if cat is not None else ""
                if (
                    cat_name == prefix_dash
                    or cat_name.startswith((f"{prefix_dash}/", f"{prefix_dash}-"))
                ):
                    dm_id = None
                    for inp in f.findall("Input"):
                        if inp.get("id") == "1":
                            dm_id = inp.get("value", "").strip()
                            break
                    dash_flows.append((f, cat_name, dm_id))
            if dash_flows:
                return dash_flows, "-"

            return [], "/"

        mono_flows = []
        for f in all_flows:
            cat = f.find("Category")
            cat_name = cat.get("Name", "") if cat is not None else ""
            if (
                cat_name == src_year
                or cat_name.startswith((f"{src_year}/", f"{src_year}-"))
            ):
                dm_id = None
                for inp in f.findall("Input"):
                    if inp.get("id") == "1":
                        dm_id = inp.get("value", "").strip()
                        break
                mono_flows.append((f, cat_name, dm_id))
        return mono_flows, "/"

    def _confirm_existing_destination_flows(self, all_flows, dst_congress, dst_year):
        if dst_congress:
            prefix_slash = f"{dst_congress}/{dst_year}"
            prefix_dash = f"{dst_congress}-{dst_year}"
            existing_dst_flows = [
                f
                for f in all_flows
                if (f.find("Category") is not None)
                and (
                    f.find("Category").get("Name", "") == prefix_slash
                    or f.find("Category").get("Name", "").startswith(f"{prefix_slash}/")
                    or f.find("Category").get("Name", "") == prefix_dash
                    or f.find("Category").get("Name", "").startswith(f"{prefix_dash}/")
                    or f.find("Category").get("Name", "").startswith(f"{prefix_dash}-")
                )
            ]
        else:
            existing_dst_flows = [
                f
                for f in all_flows
                if (f.find("Category") is not None)
                and (
                    f.find("Category").get("Name", "") == dst_year
                    or f.find("Category").get("Name", "").startswith(f"{dst_year}/")
                    or f.find("Category").get("Name", "").startswith(f"{dst_year}-")
                )
            ]
        if existing_dst_flows:
            confirm(
                f"{len(existing_dst_flows)} flux existent déjà pour "
                f"{dst_congress + '/' if dst_congress else ''}{dst_year}. "
                f"Le clonage va créer des doublons dans le backup.",
                abort_msg="Clonage annulé. Vérifiez le backup source.",
            )

    def _confirm_existing_destination_dashboard(self, db_root, dst_congress, dst_year):
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
            p
            for p in db_root.findall("Dashboard")
            if p.get("id") == dst_year
            and p.get("type") == "container"
            and p.get("parent", "") == _congress_uid_check
        ]
        if existing_dst_db:
            confirm(
                f"Un container dashboard '{dst_year}' existe déjà sous "
                f"{dst_congress if dst_congress else '(racine)'}. "
                "Les pages clonées seront ajoutées à cette branche et peuvent créer "
                "des doublons fonctionnels.",
                abort_msg="Clonage annulé. Vérifiez le dashboard cible avant de relancer.",
            )

    def _resolve_model_dependencies(self, flows_to_clone, all_models):
        all_dm_ids = set()
        for _, _, dm_id in flows_to_clone:
            if dm_id:
                all_dm_ids |= self.dependency_resolver.resolve_deps(dm_id, all_models)
        return all_dm_ids

    def _split_dm_ids(self, all_dm_ids, all_models, src_year):
        dm_to_clone = set()
        for dm_id in all_dm_ids:
            if dm_id in all_models:
                m = all_models[dm_id]
                m_name = m.get("name", "")
                cat = m.find("Category")
                cat_name = cat.get("Name", "") if cat is not None else ""
                if src_year in m_name or src_year in cat_name:
                    dm_to_clone.add(dm_id)
        dm_shared = all_dm_ids - dm_to_clone
        return dm_to_clone, dm_shared

    def _confirm_id_collisions(self, id_map, existing_dm_ids):
        collisions = [new for old, new in id_map.items() if old != new and new in existing_dm_ids]
        if collisions:
            confirm(
                f"{len(collisions)} ID(s) générés entrent en collision avec des modèles "
                f"existants : {collisions[:3]}{'...' if len(collisions) > 3 else ''}. "
                f"Cela peut corrompre des modèles existants.",
                abort_msg="Clonage annulé. Modifiez le sel (salt) ou contactez le support.",
            )

    def _confirm_flow_uid_collisions(self, flow_uid_map, all_flows, dst_year):
        existing_flow_uids = {f.get("uid") for f in all_flows}
        flow_uid_collisions = [new for _, new in flow_uid_map.items() if new in existing_flow_uids]
        if flow_uid_collisions:
            confirm(
                f"{len(flow_uid_collisions)} UID(s) de flux générés entrent en collision "
                f"avec des flux existants. DigDash ne pourra pas distinguer les flux. "
                f"Cause probable : des flux {dst_year} existent déjà dans ce backup.",
                abort_msg="Clonage annulé. Supprimez les flux existants pour l'année cible.",
            )

    def _clone_models(
        self,
        dm_to_clone,
        all_models,
        id_map,
        csv_path_mode,
        src_year,
        dst_year,
        congress,
        dst_congress,
        ts,
    ):
        cloned_models = []
        for old_id in dm_to_clone:
            if old_id not in all_models:
                continue
            raw = ET.tostring(all_models[old_id], encoding="unicode")
            raw = self._transform_model_raw(
                raw,
                old_id,
                id_map,
                csv_path_mode,
                src_year,
                dst_year,
                congress,
                dst_congress,
            )
            m2 = safe_fromstring(raw)
            m2.set("lastedit", ts)
            cloned_models.append(m2)
        return cloned_models

    def _transform_model_raw(
        self,
        raw,
        old_id,
        id_map,
        csv_path_mode,
        src_year,
        dst_year,
        congress,
        dst_congress,
    ):
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
            placeholders = {}

            def repl(match):
                csvds_tag = match.group(0)
                attrs = re.findall(r'(?:Path|Name)="[^"]*"', csvds_tag)
                for attr in attrs:
                    ph = f"__CSVDS_ATTR_{len(placeholders)}__"
                    placeholders[ph] = attr
                    csvds_tag = csvds_tag.replace(attr, ph)
                return csvds_tag

            raw = re.sub(r"<CSVDS\s+[^>]*>", repl, raw)
            raw = raw.replace(src_year, dst_year)
            for ph, attr in placeholders.items():
                raw = raw.replace(ph, attr)
        if congress and dst_congress != congress:
            raw = raw.replace(congress, dst_congress)
        return raw

    def _clone_flows(
        self,
        flows_to_clone,
        flow_uid_map,
        id_map,
        congress,
        src_year,
        dst_year,
        dst_congress,
        ts,
        role_id,
        matched_sep: str = "/",
    ):
        cloned_flows = []
        for f, _, _ in flows_to_clone:
            raw = ET.tostring(f, encoding="unicode")
            old_uid = f.get("uid")
            raw = raw.replace(f'uid="{old_uid}"', f'uid="{flow_uid_map[old_uid]}"')
            for old, new in id_map.items():
                if old != new:
                    raw = raw.replace(f'value="{old}"', f'value="{new}"')
                    raw = raw.replace(f'dmId="{old}"', f'dmId="{new}"')
            raw = raw.replace(src_year, dst_year)
            if congress and dst_congress != congress:
                raw = raw.replace(congress, dst_congress)
            f2 = safe_fromstring(raw)
            f2.set("lastedit", ts)
            f2.set("group", role_id)

            # Normaliser la catégorie pour toujours utiliser '/' à l'export
            cat = f2.find("Category")
            if cat is not None:
                cname = cat.get("Name", "")
                if congress:
                    prefix_dash = f"{dst_congress}-{dst_year}"
                    prefix_slash = f"{dst_congress}/{dst_year}"
                    if cname == prefix_dash:
                        cat.set("Name", prefix_slash)
                    elif cname.startswith((f"{prefix_dash}/", f"{prefix_dash}-")):
                        sub = cname[len(prefix_dash) + 1 :]
                        cat.set("Name", f"{prefix_slash}/{sub}")
                elif cname.startswith(f"{dst_year}-"):
                    sub = cname[len(dst_year) + 1 :]
                    cat.set("Name", f"{dst_year}/{sub}")

            cloned_flows.append(f2)
        return cloned_flows

    def _build_pages_to_clone(
        self,
        db_root,
        dst_congress,
        dst_year,
        congress,
        src_year,
        flow_uid_map,
        label,
        verbose,
    ):
        all_db_pages = db_root.findall("Dashboard")
        uid_to_page = {p.get("uid"): p for p in all_db_pages}
        children_map = self._build_children_map(all_db_pages)
        congress_uid = self._find_congress_container_uid(all_db_pages, dst_congress)
        src_congress_uid = self._find_src_congress_uid(
            all_db_pages, congress, dst_congress, congress_uid
        )
        year_container = self._find_year_container(all_db_pages, src_year, src_congress_uid)

        if year_container is not None:
            pages_to_clone = self._collect_subtree(
                year_container.get("uid"), children_map, uid_to_page
            )
            log(
                f"[{label}] Sous-arbre dashboard : {len(pages_to_clone)} éléments "
                f"(containers + feuilles)",
                verbose,
            )
        else:
            log(
                f"[{label}] Container '{src_year}' introuvable — fallback détection par flux",
                verbose,
            )
            pages_to_clone = self._collect_fallback_pages(all_db_pages, flow_uid_map)
            if pages_to_clone:
                dest_year_container = self._find_year_container(
                    all_db_pages, dst_year, congress_uid
                )
                if dest_year_container is not None:
                    dest_uid = dest_year_container.get("uid")
                    new_pages = []
                    for d in pages_to_clone:
                        d_clone = safe_fromstring(ET.tostring(d, encoding="unicode"))
                        d_clone.set("parent", dest_uid)
                        new_pages.append(d_clone)
                    pages_to_clone = new_pages
                else:
                    fake_year_uid = str(
                        uid_int(f"fallback_{dst_year}_{int(time.time() * 1000)}", "fallback")
                    )
                    year_container_elem = ET.Element("Dashboard")
                    year_container_elem.set("accessible", "true")
                    year_container_elem.set("desktop", "true")
                    year_container_elem.set("id", dst_year)
                    year_container_elem.set("lastedit", str(int(time.time() * 1000)))
                    year_container_elem.set("mobile", "true")
                    year_container_elem.set("parent", congress_uid or src_congress_uid or "")
                    year_container_elem.set("position", "0")
                    year_container_elem.set("type", "container")
                    year_container_elem.set("uid", fake_year_uid)
                    year_container_elem.set("visible", "true")
                    year_container_elem.set("vizType", "tab")
                    sn_elem = ET.SubElement(year_container_elem, "SpeakableNames")
                    sn_elem.set("global", "false")
                    sn_elem.set("id", dst_year)
                    new_pages = [year_container_elem]
                    for d in pages_to_clone:
                        d_clone = safe_fromstring(ET.tostring(d, encoding="unicode"))
                        d_clone.set("parent", fake_year_uid)
                        new_pages.append(d_clone)
                    pages_to_clone = new_pages
        return pages_to_clone

    def _build_children_map(self, all_db_pages):
        children_map = defaultdict(list)
        for p in all_db_pages:
            par = p.get("parent", "")
            if par:
                children_map[par].append(p)
        return children_map

    def _find_congress_container_uid(self, all_db_pages, dst_congress):
        if not dst_congress:
            return ""
        for p in all_db_pages:
            if p.get("type") == "container" and not p.get("parent") and p.get("id") == dst_congress:
                return p.get("uid", "")
        return ""

    def _find_src_congress_uid(self, all_db_pages, congress, dst_congress, congress_uid):
        if congress:
            for p in all_db_pages:
                if p.get("id") == congress and p.get("type") == "container" and not p.get("parent"):
                    return p.get("uid", "")
        return congress_uid

    def _find_year_container(self, all_db_pages, year, congress_uid):
        if congress_uid:
            for p in all_db_pages:
                if (
                    p.get("id") == year
                    and p.get("type") == "container"
                    and p.get("parent", "") == congress_uid
                ):
                    return p
            for p in all_db_pages:
                if p.get("id") == year and p.get("parent", "") == congress_uid:
                    return p
            return None

        # Fallback pour mono-congrès
        match_fallback = None
        for p in all_db_pages:
            if p.get("id") == year:
                if p.get("type") == "container" and not p.get("parent"):
                    return p
                if match_fallback is None:
                    match_fallback = p
        return match_fallback

    def _collect_subtree(self, uid: str, children_map, uid_to_page):
        page = uid_to_page.get(uid)
        if page is None:
            return []
        result = [page]
        for child in sorted(
            children_map.get(uid, []),
            key=lambda x: int(x.get("position", "0") or "0"),
        ):
            result.extend(self._collect_subtree(child.get("uid"), children_map, uid_to_page))
        return result

    def _collect_fallback_pages(self, all_db_pages, flow_uid_map):
        src_flow_uids_set = set(flow_uid_map.keys())
        seen = set()
        pages_to_clone = []
        for d in all_db_pages:
            for base in d.findall('.//Base[@type="flow"]'):
                if base.get("flowId", "") in src_flow_uids_set:
                    uid = d.get("uid")
                    if uid not in seen:
                        seen.add(uid)
                        pages_to_clone.append(d)
                    break
        return pages_to_clone

    def _build_page_maps(
        self,
        pages_to_clone,
        salt,
        existing_uids: set | None = None,
        extra_mappings: dict | None = None,
    ):
        """
        Build maps for page and portlet UIDs while avoiding collisions with existing UIDs.

        Tries deterministic derivation first, then appends an incremental suffix to the
        salt until a non-colliding UID is found.
        """
        existing_uids = set(existing_uids or set())
        page_uid_map: dict[str, str] = {}
        for p in pages_to_clone:
            old = p.get("uid")
            if not old:
                continue
            i = 0
            while True:
                candidate = str(uid_int(old, f"page{salt}" if i == 0 else f"page{salt}_{i}"))
                if candidate not in existing_uids and candidate not in page_uid_map.values():
                    page_uid_map[old] = candidate
                    break
                i += 1

        portlet_uid_map: dict[str, str] = {}
        for d in pages_to_clone:
            for base in d.findall(".//Base"):
                puid = base.get("uid", "")
                if not puid or puid in portlet_uid_map:
                    continue
                i = 0
                while True:
                    candidate = str(
                        uid_int(puid, f"portlet{salt}" if i == 0 else f"portlet{salt}_{i}")
                    )
                    if (
                        candidate not in existing_uids
                        and candidate not in page_uid_map.values()
                        and candidate not in portlet_uid_map.values()
                    ):
                        portlet_uid_map[puid] = candidate
                        break
                    i += 1
        # apply any extra mappings (e.g., map source-year uid -> existing dst-year uid)
        if extra_mappings:
            for k, v in extra_mappings.items():
                page_uid_map[k] = v
        return page_uid_map, portlet_uid_map

    def _clone_pages(
        self,
        pages_to_clone,
        page_uid_map,
        portlet_uid_map,
        flow_uid_map,
        id_map,
        src_year,
        dst_year,
        congress,
        dst_congress,
        ts,
    ):
        cloned_pages = []
        for d in pages_to_clone:
            raw = ET.tostring(d, encoding="unicode")
            old_uid = d.get("uid")
            raw = raw.replace(f'uid="{old_uid}"', f'uid="{page_uid_map[old_uid]}"', 1)
            old_parent = d.get("parent", "")
            if old_parent and old_parent in page_uid_map:
                raw = raw.replace(
                    f'parent="{old_parent}"',
                    f'parent="{page_uid_map[old_parent]}"',
                    1,
                )
            for old, new in portlet_uid_map.items():
                raw = raw.replace(f'uid="{old}"', f'uid="{new}"')
            for old, new in flow_uid_map.items():
                raw = raw.replace(f'flowId="{old}"', f'flowId="{new}"')
            for old, new in id_map.items():
                if old != new:
                    raw = raw.replace(f'value="{old}"', f'value="{new}"')
                    raw = raw.replace(f'datasource="{old}"', f'datasource="{new}"')
                    raw = raw.replace(f'dmId="{old}"', f'dmId="{new}"')
                    raw = raw.replace(f'Link="{old}"', f'Link="{new}"')
            # Update DashboardRef link attributes to point to new page UIDs
            for old, new in page_uid_map.items():
                raw = raw.replace(f'link="{old}"', f'link="{new}"')
            raw = raw.replace(src_year, dst_year)
            if congress and dst_congress != congress:
                raw = raw.replace(congress, dst_congress)
            d2 = safe_fromstring(raw)
            d2.set("lastedit", ts)
            # Ensure parent is correctly set: prefer mapped parent, otherwise keep original parent
            orig_parent = d.get("parent", "")
            new_parent = None
            if orig_parent:
                if orig_parent in page_uid_map:
                    new_parent = page_uid_map[orig_parent]
                else:
                    new_parent = orig_parent
            if new_parent:
                d2.set("parent", new_parent)
            # remove parent attribute if empty
            elif d2.get("parent"):
                d2.attrib.pop("parent", None)
            cloned_pages.append(d2)
        return cloned_pages

    def clone_congress(
        self,
        backup: Backup,
        congress: str,
        src_year: str,
        dst_year: str,
        csv_path_mode: str,  # "replace" | "keep" | "empty"
        dst_congress: str | None = None,
        verbose: bool = False,
    ) -> CloneResult | None:
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

        dst_congress = dst_congress or congress

        all_models = (
            {m.get("id"): m for m in dm_root.findall("TableDataModel")} if dm_root is not None else {}
        )
        all_flows = wl_root.findall("Flow") if wl_root is not None else []
        salt = f"{dst_congress}{dst_year}"

        label = f"{congress}/{src_year}" if congress else src_year
        if backup.dashboard_only:
            flows_to_clone, matched_sep = [], "/"
        else:
            flows_to_clone, matched_sep = self._select_flows_to_clone(
                all_flows, congress, src_year
            )

        log(f"[{label}] Flux à cloner : {len(flows_to_clone)}", verbose)
        if not flows_to_clone and not backup.dashboard_only:
            target = f"{congress}/{src_year} ou {congress}-{src_year}" if congress else f"{src_year}[/...] ou {src_year}"
            print(f"  [WARN] Aucun flux trouvé pour {target}")
            return None

        if not backup.dashboard_only:
            self._confirm_existing_destination_flows(all_flows, dst_congress, dst_year)
        self._confirm_existing_destination_dashboard(db_root, dst_congress, dst_year)

        all_dm_ids = self._resolve_model_dependencies(flows_to_clone, all_models)
        dm_to_clone, dm_shared = self._split_dm_ids(all_dm_ids, all_models, src_year)

        log(
            f"[{label}] Modèles à cloner : {len(dm_to_clone)}, partagés : {len(dm_shared)}",
            verbose,
        )

        id_map = {old: uid_hex(old, salt) for old in dm_to_clone}
        for s in dm_shared:
            id_map[s] = s

        flow_uid_map = {f.get("uid"): uid_int(f.get("uid"), salt) for f, _, _ in flows_to_clone}

        self._confirm_id_collisions(id_map, set(all_models.keys()))
        self._confirm_flow_uid_collisions(flow_uid_map, all_flows, dst_year)

        cloned_models = self._clone_models(
            dm_to_clone,
            all_models,
            id_map,
            csv_path_mode,
            src_year,
            dst_year,
            congress,
            dst_congress,
            ts,
        )
        log(f"[{label}] Modèles clonés : {len(cloned_models)}", verbose)

        cloned_flows = self._clone_flows(
            flows_to_clone,
            flow_uid_map,
            id_map,
            congress,
            src_year,
            dst_year,
            dst_congress,
            ts,
            role_id,
            matched_sep,
        )
        log(f"[{label}] Flux clonés : {len(cloned_flows)}", verbose)

        pages_to_clone = self._build_pages_to_clone(
            db_root,
            dst_congress,
            dst_year,
            congress,
            src_year,
            flow_uid_map,
            label,
            verbose,
        )
        if backup.dashboard_only and not pages_to_clone:
            message = (
                f"Aucune page dashboard trouvée pour la source "
                f"{congress + '/' if congress else ''}{src_year}."
            )
            raise ValueError(message)
        all_db_pages = db_root.findall("Dashboard")
        existing_uids = {p.get("uid") for p in all_db_pages if p.get("uid")}

        congress_uid = self._find_congress_container_uid(all_db_pages, dst_congress)
        src_congress_uid = self._find_src_congress_uid(
            all_db_pages, congress, dst_congress, congress_uid
        )

        extra_mappings = {}
        new_congress_page = None

        if dst_congress:
            if not congress_uid:
                congress_uid = str(uid_int(f"congress_{dst_congress}", salt))
                while congress_uid in existing_uids:
                    congress_uid = str(int(congress_uid) + 1)
                existing_uids.add(congress_uid)

                new_congress_page = ET.Element("Dashboard")
                new_congress_page.set("accessible", "true")
                new_congress_page.set("desktop", "true")
                new_congress_page.set("id", dst_congress)
                new_congress_page.set("lastedit", ts)
                new_congress_page.set("mobile", "true")
                new_congress_page.set("type", "container")
                new_congress_page.set("uid", congress_uid)
                new_congress_page.set("visible", "true")
                new_congress_page.set("vizType", "tab")
                sn_elem = ET.SubElement(new_congress_page, "SpeakableNames")
                sn_elem.set("global", "false")
                sn_elem.set("id", dst_congress)

            if src_congress_uid:
                extra_mappings[src_congress_uid] = congress_uid

        src_year_container = self._find_year_container(all_db_pages, src_year, src_congress_uid)
        src_year_uid = src_year_container.get("uid") if src_year_container is not None else None

        dest_year_container = self._find_year_container(all_db_pages, dst_year, congress_uid)
        dest_year_uid = dest_year_container.get("uid") if dest_year_container is not None else None

        # If both source year container and destination year container exist AND are different,
        # avoid cloning the source container itself and map its uid to the existing dest uid
        if src_year_uid and dest_year_uid and src_year_uid != dest_year_uid:
            pages_to_clone = [p for p in pages_to_clone if p.get("uid") != src_year_uid]
            extra_mappings[src_year_uid] = dest_year_uid

        page_uid_map, portlet_uid_map = self._build_page_maps(
            pages_to_clone, salt, existing_uids, extra_mappings
        )
        cloned_pages = self._clone_pages(
            pages_to_clone,
            page_uid_map,
            portlet_uid_map,
            flow_uid_map,
            id_map,
            src_year,
            dst_year,
            congress,
            dst_congress,
            ts,
        )

        if congress_uid:
            for p in cloned_pages:
                if p.get("id") == dst_year and p.get("type") == "container":
                    p.set("parent", congress_uid)

        if new_congress_page is not None:
            cloned_pages.insert(0, new_congress_page)

        root_positions = [
            int(p.get("position", "0").strip() or "0") for p in all_db_pages if not p.get("parent")
        ]
        max_root_position = max(root_positions, default=-1)
        for p in cloned_pages:
            if not p.get("parent"):
                max_root_position += 1
                p.set("position", str(max_root_position))

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
