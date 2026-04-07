"""
digdash_cloner/models/clone_result.py
Modèle pour représenter le résultat d'un clonage de congrès.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xml.etree.ElementTree as ET


class CloneResult:
    """
    Résultat du clonage d'un congrès.
    Suit le principe SRP : encapsule uniquement les données du résultat.
    """

    def __init__(
        self,
        congress: str,
        src_year: str,
        dst_year: str,
        cloned_models: list[ET.Element],
        cloned_flows: list[ET.Element],
        cloned_pages: list[ET.Element],
        id_map: dict[str, str],
        flow_uid_map: dict[str, str],
        page_uid_map: dict[str, str],
    ):
        self.congress = congress
        self.src_year = src_year
        self.dst_year = dst_year
        self.cloned_models = cloned_models
        self.cloned_flows = cloned_flows
        self.cloned_pages = cloned_pages
        self.id_map = id_map
        self.flow_uid_map = flow_uid_map
        self.page_uid_map = page_uid_map
