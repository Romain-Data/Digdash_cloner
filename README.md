# DigDash Role Cloner

Clone une section d'un rôle DigDash d'une année vers une autre et génère un fichier ZIP prêt à l'import.

## Installation

L'utilisation de [uv](https://github.com/astral-sh/uv) est recommandée pour une gestion rapide et robuste des dépendances.

```bash
# Installe les dépendances et le projet en mode éditable
uv sync --all-extras

# Ou avec pip
pip install -e .[dev]
```

## Utilisation

```bash
uv run python -m digdash_cloner \
  --backup-zip backup_source.zip \
  --congress EuroPCR \
  --src-year 2025 \
  --dst-year 2026 \
  --output backup_clone.zip

# Ou sans uv
python -m digdash_cloner --backup-zip backup_source.zip --congress EuroPCR --src-year 2025 --dst-year 2026 --output backup_clone.zip
```

## Développement

### Mise en forme et linting

Le projet utilise [Ruff](https://github.com/astral-sh/ruff) pour le linting et le formatage.

```bash
# Vérifier le code
python -m ruff check .

# Formater le code
python -m ruff format .

# Corriger automatiquement
python -m ruff check --fix .
```

### Structure

- `models/` : Classes de données (Backup, CloneResult).
- `services/` : Logique métier (BackupLoader, CongressCloner, etc.).
- `utils/` : Utilitaires (générateurs d'IDs, XML).
- `cli/` : Interface en ligne de commande.