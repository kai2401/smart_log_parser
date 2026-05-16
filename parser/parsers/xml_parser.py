import xml.etree.ElementTree as ET
from typing import Generator


def parse(content: str) -> Generator[dict, None, None]:
    """Yield raw record dicts from XML content.

    Supports two shapes:
      <logs><entry ...>...</entry></logs>
      <log><event><key>value</key>...</event></log>
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValueError(f"XML parse error: {e}")

    # Find repeating child elements (treat as records)
    children = list(root)
    if not children:
        return

    for child in children:
        record: dict = {}

        # Attributes of the element itself
        record.update(child.attrib)

        # Text content of sub-elements
        for sub in child:
            record[sub.tag] = sub.text or ""
            # Also grab sub-element attributes
            record.update({f"{sub.tag}_{k}": v for k, v in sub.attrib.items()})

        # If the element has direct text (no sub-elements)
        if child.text and child.text.strip() and not list(child):
            record.setdefault("message", child.text.strip())

        if record:
            yield record
