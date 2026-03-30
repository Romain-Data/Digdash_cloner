"""
digdash_cloner/utils/uid_generators.py
Générateurs d'IDs déterministes pour DigDash.
Suit le principe SRP : responsabilité unique de génération d'IDs.
"""

import hashlib


def uid_hex(old_id: str, salt: str) -> str:
    """Génère un ID hexadécimal déterministe de 32 caractères (même format que DigDash)."""
    return hashlib.md5(f"{salt}_{old_id}".encode()).hexdigest()


def uid_int(old_id: str, salt: str) -> str:
    """Génère un entier positif déterministe (pour les UIDs de pages/portlets)."""
    h = hashlib.md5(f"{salt}_{old_id}".encode()).hexdigest()
    return str(int(h[:8], 16) % 2_000_000_000 + 100_000_000)
