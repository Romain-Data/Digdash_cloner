"""
digdash_cloner/main.py
Point d'entrée principal de l'application.
Suit les principes SRP (orchestration uniquement), DIP (dépend d'interfaces des services).
"""

import sys
from pathlib import Path

from .cli.args_parser import parse_args
from .services.backup_builder import BackupBuilder
from .services.backup_loader import BackupLoader
from .services.backup_validator import BackupValidator
from .services.congress_cloner import CongressCloner
from .services.dependency_resolver import DependencyResolver


def main():
    args = parse_args()

    print(f"\n{'═' * 60}")
    print("  DigDash Role Cloner")
    print(f"{'═' * 60}")
    print(f"  Source   : {args.backup_zip}")
    congress_display = (
        ", ".join(args.congress) if args.congress else "(mono-congrès, catégorie {Année}/...)"
    )
    if args.dst_congress:
        congress_display = f"{congress_display} → {args.dst_congress}"
    print(f"  Congrès  : {congress_display}")
    print(f"  Année    : {args.src_year} → {args.dst_year}")
    print(f"  Chemins  : {args.csv_path}")
    print(f"  Sortie   : {args.output}")
    print(f"{'═' * 60}\n")

    # Validation
    if args.dst_congress and len(args.congress) > 1:
        print("❌ Erreur : --dst-congress ne peut être utilisé qu'avec un seul congrès source.")
        sys.exit(1)

    # Injection de dépendances
    backup_loader = BackupLoader()
    dependency_resolver = DependencyResolver()
    congress_cloner = CongressCloner(dependency_resolver)
    backup_builder = BackupBuilder()
    backup_validator = BackupValidator()

    # ── Chargement ────────────────────────────────────────────────────────────
    print("Chargement du backup source...")
    try:
        backup = backup_loader.load(args.backup_zip)
    except ValueError as e:
        print(f"❌ Erreur au chargement : {e}")
        sys.exit(1)
    print(f"  Rôle détecté : {backup.role_id}")

    # ── Clonage ───────────────────────────────────────────────────────────────
    print("\nClonage en cours...")
    clone_results = []
    congress_list = args.congress if args.congress else [""]
    for congress in congress_list:
        dst_congress = args.dst_congress if args.dst_congress else congress
        label = congress if congress else "(mono-congrès)"
        if args.dst_congress:
            label += f" → {dst_congress}"
        print(f"\n  Congrès : {label}")
        result = congress_cloner.clone_congress(
            backup=backup,
            congress=congress,
            src_year=args.src_year,
            dst_year=args.dst_year,
            csv_path_mode=args.csv_path,
            dst_congress=dst_congress,
            verbose=args.verbose,
        )
        clone_results.append(result)

    # ── Assemblage ────────────────────────────────────────────────────────────
    print("\nAssemblage du backup final...")
    backup_builder.build_backup(
        backup=backup,
        clone_results=clone_results,
        output_path=args.output,
        verbose=args.verbose,
    )

    # ── Validation ────────────────────────────────────────────────────────────
    congresses_to_validate = []
    for congress in congress_list:
        dst_congress = args.dst_congress if args.dst_congress else congress
        congresses_to_validate.append(dst_congress)
    ok = backup_validator.validate_output(args.output, congresses_to_validate, args.dst_year)

    # ── Résumé ────────────────────────────────────────────────────────────────
    print("\n── Résumé ──────────────────────────────────────────────────────────")
    total_models = sum(len(r.cloned_models) for r in clone_results if r)
    total_flows = sum(len(r.cloned_flows) for r in clone_results if r)
    total_pages = sum(len(r.cloned_pages) for r in clone_results if r)
    print(f"  Modèles clonés  : {total_models}")
    print(f"  Flux clonés     : {total_flows}")
    print(f"  Pages clonées   : {total_pages}")
    size_mb = Path(args.output).stat().st_size / 1_048_576
    print(f"  Taille ZIP      : {size_mb:.1f} Mo")
    print(f"\n{'✅' if ok else '⚠️ '} Fichier généré : {args.output}\n")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
