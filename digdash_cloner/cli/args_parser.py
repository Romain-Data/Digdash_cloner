"""
digdash_cloner/cli/args_parser.py
Parsing des arguments CLI.
Suit les principes SRP (parsing uniquement) et DIP (utilise argparse abstrait).
"""

import argparse

DEFAULTS = {
    "congress": [],  # Congrès à cloner (vide = mode mono-congrès)
    "src_year": "2025",  # Année source
    "dst_year": "2026",  # Année cible
    "csv_path": "replace",  # "replace" | "keep" | "empty"
    "output": "backup_clone.zip",
    "verbose": False,
}


def parse_args():
    p = argparse.ArgumentParser(
        description="Clone une section d'un rôle DigDash d'une année vers une autre.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
    # Clone EuroPCR/2025 → EuroPCR/2026 dans le rôle existant
    python3 -m digdash_cloner \\
        --backup-zip  backup_source.zip \\
        --congress    EuroPCR \\
        --src-year    2025 \\
        --dst-year    2026 \\
        --output      backup_clone.zip

    # Avec toutes les options
    python3 -m digdash_cloner \\
        --backup-zip  backup_source.zip \\
        --congress    EuroPCR PCRLondonValves \\
        --src-year    2025 \\
        --dst-year    2026 \\
        --csv-path    replace \\
        --output      backup_clone.zip \\
        --verbose
        """,
    )
    p.add_argument(
        "--backup-zip", required=True, help="Chemin vers le fichier ZIP source (backup DigDash)"
    )
    p.add_argument(
        "--congress",
        nargs="*",
        default=DEFAULTS["congress"],
        help=(
            "Nom(s) du/des congrès (ex: EuroPCR PCRLondonValves). "
            "Omettez ce paramètre pour les rôles mono-congrès dont les catégories "
            "sont au format '{Année}/...' sans préfixe congrès."
        ),
    )
    p.add_argument(
        "--src-year",
        default=DEFAULTS["src_year"],
        help=f"Année source (défaut : {DEFAULTS['src_year']})",
    )
    p.add_argument(
        "--dst-year",
        "--dist-year",
        dest="dst_year",
        default=DEFAULTS["dst_year"],
        help=f"Année cible (défaut : {DEFAULTS['dst_year']})",
    )
    p.add_argument(
        "--csv-path",
        choices=["replace", "keep", "empty"],
        default=DEFAULTS["csv_path"],
        help=(
            "Traitement des chemins CSV :\n"
            "  replace = remplacer src_year→dst_year dans les paths (défaut)\n"
            "  keep    = conserver les chemins sources tels quels\n"
            '  empty   = vider les chemins (Path="", à remplir manuellement)'
        ),
    )
    p.add_argument(
        "--output",
        default=DEFAULTS["output"],
        help=f"Chemin du fichier ZIP de sortie (défaut : {DEFAULTS['output']})",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        default=DEFAULTS["verbose"],
        help="Afficher les détails de chaque étape",
    )
    return p.parse_args()
