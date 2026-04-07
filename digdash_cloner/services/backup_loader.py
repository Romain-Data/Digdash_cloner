"""
digdash_cloner/services/backup_loader.py
Service pour charger un backup DigDash depuis un ZIP.
Suit les principes SRP (chargement uniquement) et DIP (dépend d'abstractions comme zipfile).
"""

import zipfile
from collections import defaultdict

from defusedxml.ElementTree import fromstring as safe_fromstring

from ..models.backup import Backup


class BackupLoader:
    """
    Responsable du chargement d'un backup DigDash.
    Suit OCP : peut être étendu pour d'autres formats sans modifier le code existant.
    """

    def load(self, backup_zip_path: str) -> Backup:
        """
        Extrait le contenu du ZIP source en mémoire.
        Retourne un objet Backup.
        """
        data = {}
        with zipfile.ZipFile(backup_zip_path, "r") as zf:
            for name in zf.namelist():
                data[name] = zf.read(name)

        # Identifier le rôle (dossier sous backup/config/roles/)
        role_files = defaultdict(set)
        for name in data:
            parts = name.split("/")
            if (
                len(parts) == 5
                and parts[1] == "config"
                and parts[2] == "roles"
                and parts[3]
                and parts[4]
            ):
                role_files[parts[3]].add(parts[4])

        role_ids = {
            rid
            for rid, files in role_files.items()
            if any("tabledatamodel" in f for f in files)
            and any(f.endswith(".iwt") for f in files)
            and any("dashboard" in f for f in files)
        }

        if len(role_ids) != 1:
            message = (
                "Impossible de détecter le rôle unique. "
                f"Rôles complets trouvés : {role_ids} "
                f"(rôles incomplets ignorés : {set(role_files) - role_ids})"
            )
            raise ValueError(message)
        role_id = next(iter(role_ids))

        # Chemins des fichiers clés
        role_prefix = f"backup/config/roles/{role_id}/"
        dm_key = next(
            k for k in data if k.startswith(role_prefix) and "tabledatamodelrepository" in k
        )
        wl_key = next(k for k in data if k.startswith(role_prefix) and k.endswith(".iwt"))
        db_key = next(k for k in data if k.startswith(role_prefix) and "dashboard" in k)
        bk_key = "backup/backup.xml"

        return Backup(
            role_id=role_id,
            dm_key=dm_key,
            wl_key=wl_key,
            db_key=db_key,
            bk_key=bk_key,
            all_files=data,
            dm_root=safe_fromstring(data[dm_key]),
            wl_root=safe_fromstring(data[wl_key]),
            db_root=safe_fromstring(data[db_key]),
            bk_root=safe_fromstring(data[bk_key]),
        )
