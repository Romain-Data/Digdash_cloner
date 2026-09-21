"""
digdash_cloner/models/backup.py
Modèle pour représenter un backup DigDash chargé.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xml.etree.ElementTree as ET


class Backup:
    """
    Représente un backup DigDash chargé en mémoire.
    Suit le principe SRP : encapsule uniquement les données du backup.
    """

    def __init__(
        self,
        role_id: str,
        dm_key: str,
        wl_key: str,
        db_key: str,
        bk_key: str,
        all_files: dict[str, bytes],
        dm_root: ET.Element,
        wl_root: ET.Element,
        db_root: ET.Element,
        bk_root: ET.Element,
    ):
        self.role_id = role_id
        self.dm_key = dm_key
        self.wl_key = wl_key
        self.db_key = db_key
        self.bk_key = bk_key
        self.all_files = all_files
        self.dm_root = dm_root
        self.wl_root = wl_root
        self.db_root = db_root
        self.bk_root = bk_root
