import csv
import io
from typing import Generator


def parse(content: str) -> Generator[dict, None, None]:
    """Yield raw record dicts from CSV/TSV content."""
    delimiter = "\t" if content.count("\t") > content.count(",") else ","
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    for row in reader:
        # Strip whitespace from keys and values
        yield {k.strip(): v.strip() for k, v in row.items() if k}
