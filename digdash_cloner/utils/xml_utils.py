"""
digdash_cloner/utils/xml_utils.py
Utilitaires pour la manipulation XML.
Suit le principe SRP : responsabilité unique de sérialisation XML et logging.
"""

import xml.etree.ElementTree as ET


def serialize(root: ET.Element, processing_instruction: str = None) -> bytes:
    """Sérialise un arbre XML en bytes UTF-8 avec déclaration."""
    raw = ET.tostring(root, encoding="unicode", xml_declaration=False)
    header = '<?xml version="1.0" encoding="UTF-8"?>'
    if processing_instruction:
        header += f"\n{processing_instruction}"
    return (header + "\n" + raw).encode("utf-8")


def log(msg: str, verbose: bool = True):
    if verbose:
        print(f"  {msg}")
