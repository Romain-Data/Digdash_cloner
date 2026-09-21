"""
digdash_cloner/utils/xml_utils.py
Utilitaires pour la manipulation XML.
Suit le principe SRP : responsabilité unique de sérialisation XML et logging.
"""

import html
import re
import xml.etree.ElementTree as ET

_CDATA_ROOT_TAGS = ("RenderingModel", "Root")
_CDATA_PATTERN = re.compile(
    rf'<Input id="2">(&lt;(?:{"|".join(_CDATA_ROOT_TAGS)}).*?&lt;/(?:{"|".join(_CDATA_ROOT_TAGS)})&gt;)</Input>',
    re.DOTALL,
)


def _restore_cdata(raw: str) -> str:
    return _CDATA_PATTERN.sub(
        lambda m: '<Input id="2"><![CDATA[' + html.unescape(m.group(1)) + "]]></Input>",
        raw,
    )


def serialize(root: ET.Element, processing_instruction: str = None) -> bytes:
    raw = ET.tostring(root, encoding="unicode", xml_declaration=False)
    raw = _restore_cdata(raw)
    header = '<?xml version="1.0" encoding="UTF-8"?>'
    if processing_instruction:
        header += f"\n{processing_instruction}"
    return (header + "\n" + raw).encode("utf-8")


def log(msg: str, verbose: bool = True):
    if verbose:
        print(f"  {msg}")
