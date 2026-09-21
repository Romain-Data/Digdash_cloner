"""
digdash_cloner/cli/args_parser.py
Parsing des arguments CLI.
Suit les principes SRP (parsing uniquement) et DIP (utilise argparse abstrait).
"""

import argparse
from pathlib import Path

DEFAULTS = {
    "congress": [],  # Congrès à cloner (vide = mode mono-congrès)
    "dst_congress": None,  # Congrès cible (si renommage)
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
    # Clone EuroPCR/2025 -> EuroPCR/2026 dans le rôle existant
    python3 -m digdash_cloner \\
        --backup-zip  backup_source.zip \\
        --congress    EuroPCR \\
        --src-year    2025 \\
        --dst-year    2026 \\
        --output      backup_clone.zip

    # Copier PCRLondonValves/2025 -> EuroPCR/2026 (renommage)
    python3 -m digdash_cloner \\
        --backup-zip  backup_source.zip \\
        --congress    PCRLondonValves \\
        --dst-congress EuroPCR \\
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
        "--backup-zip", required=False, help="Chemin vers le fichier ZIP source (backup DigDash)"
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
        "--dst-congress",
        default=DEFAULTS["dst_congress"],
        help="Nom du congrès cible (si différent du source, pour renommage)",
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
            "  replace = remplacer src_year->dst_year dans les paths (défaut)\n"
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


def prompt_user():
    """
    Mode interactif : demande à l'utilisateur de saisir les paramètres.
    Retourne un namespace argparse avec les valeurs remplies.
    """
    print("\n" + "=" * 60)
    print("  Mode Interactif - Clonage de Rôle DigDash")
    print("=" * 60 + "\n")

    # Demander le chemin du backup
    while True:
        backup_zip = input("Chemin du fichier backup ZIP : ").strip()
        if not backup_zip:
            print("   [WARN] Le chemin ne peut pas être vide.")
            continue
        if not Path(backup_zip).exists():
            print(f"   [ERROR] Le fichier '{backup_zip}' n'existe pas.")
            continue
        break

    # Demander le congrès source
    congress_input = input("\nNom du congrès à cloner [vide=mono-congrès] : ").strip()
    congress = congress_input.split() if congress_input else []

    # Demander le congrès cible (optionnel)
    dst_congress = None
    if congress:
        rename = input(
            f"\nRenommer le congrès ? (appuyez sur Entrée pour garder '{congress[0]}') : "
        ).strip()
        if rename:
            dst_congress = rename

    # Demander les années
    while True:
        src_year = (
            input(f"\nAnnée source [défaut: {DEFAULTS['src_year']}] : ").strip()
            or DEFAULTS["src_year"]
        )
        if src_year.isdigit():
            break
        print("   [WARN] L'année doit être un nombre.")

    while True:
        dst_year = (
            input(f"\nAnnée cible [défaut: {DEFAULTS['dst_year']}] : ").strip()
            or DEFAULTS["dst_year"]
        )
        if dst_year.isdigit():
            break
        print("   [WARN] L'année doit être un nombre.")

    # Demander le traitement des chemins CSV
    print("\nTraitement des chemins CSV :")
    print("   1. replace = remplacer {src_year} -> {dst_year} dans les paths (défaut)")
    print("   2. keep    = conserver les chemins sources tels quels")
    print("   3. empty   = vider les chemins (à remplir manuellement)")
    while True:
        csv_choice = input("   Choix [1/2/3, défaut=1] : ").strip() or "1"
        csv_map = {"1": "replace", "2": "keep", "3": "empty"}
        if csv_choice in csv_map:
            csv_path = csv_map[csv_choice]
            break
        print("   [WARN] Veuillez saisir 1, 2 ou 3.")

    # Demander le fichier de sortie
    output = (
        input(f"\nFichier de sortie [défaut: {DEFAULTS['output']}] : ").strip()
        or DEFAULTS["output"]
    )

    # Demander le mode verbose
    verbose_input = (
        input("\nAfficher les détails de chaque étape ? (o/n, défaut=n) : ").strip().lower()
    )
    verbose = verbose_input in ("o", "y", "yes", "oui")

    # Résumé
    print("\n" + "=" * 60)
    print("  Résumé de la configuration")
    print("=" * 60)
    print(f"  Backup         : {backup_zip}")
    congress_display = ", ".join(congress) if congress else "(mono-congrès, catégorie {Année}/...)"
    if dst_congress:
        congress_display = f"{congress_display} -> {dst_congress}"
    print(f"  Congrès        : {congress_display}")
    print(f"  Années         : {src_year} -> {dst_year}")
    print(f"  Chemins CSV    : {csv_path}")
    print(f"  Fichier sortie : {output}")
    print(f"  Mode verbose   : {'Oui' if verbose else 'Non'}")
    print("=" * 60 + "\n")

    # Confirmation
    while True:
        confirm = input("Confirmer et lancer le clonage ? (o/n) : ").strip().lower()
        if confirm in ("o", "y", "yes", "oui"):
            break
        if confirm in ("n", "non", "no"):
            print("[ERROR] Opération annulée.")
            raise SystemExit(0)
        print("   [WARN] Veuillez saisir 'o' ou 'n'.")

    # Retourner un namespace type argparse
    import argparse as _argparse

    return _argparse.Namespace(
        backup_zip=backup_zip,
        congress=congress,
        dst_congress=dst_congress,
        src_year=src_year,
        dst_year=dst_year,
        csv_path=csv_path,
        output=output,
        verbose=verbose,
    )
