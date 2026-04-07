"""
digdash_cloner/services/dependency_resolver.py
Service pour résoudre les dépendances entre modèles de données.
Suit les principes SRP (résolution de dépendances uniquement) et DIP (travaille avec des dicts abstraits).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xml.etree.ElementTree as ET


class DependencyResolver:
    """
    Résout récursivement les dépendances de modèles.
    Suit OCP : peut être étendu pour d'autres types de dépendances.
    """

    def resolve_deps(
        self, dm_id: str, all_models: dict[str, ET.Element], visited: set[str] = None
    ) -> set[str]:
        """
        Remonte récursivement toute la chaîne de dépendances d'un modèle
        (JOIN, MERGE, COLTRANS).
        """
        if visited is None:
            visited = set()
        if dm_id in visited or dm_id not in all_models:
            return visited
        visited.add(dm_id)
        m = all_models[dm_id]
        for tag in ("JOINDMDS", "MERGEDMDS", "COLTRANSDMDS"):
            ds = m.find(tag)
            if ds is not None:
                for ref in ds.findall("TableDataModelRef"):
                    self.resolve_deps(ref.get("Link", ""), all_models, visited)
        return visited
