import re
import sys
from collections import defaultdict
from pathlib import Path

from loguru import logger

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "service" / "supabase" / "migrations"
WHITELIST_FILE = Path(__file__).resolve().parent / "migration_prefix_whitelist.txt"

PREFIX_RE = re.compile(r"^(\d+[a-z]?)_")


def load_whitelist() -> set[str]:
    if not WHITELIST_FILE.exists():
        return set()
    return {line.strip() for line in WHITELIST_FILE.read_text().splitlines() if line.strip()}


def main() -> int:
    whitelist = load_whitelist()

    prefix_groups: dict[str, list[str]] = defaultdict(list)
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = PREFIX_RE.match(sql_file.stem)
        if match:
            prefix_groups[match.group(1)].append(sql_file.name)

    failed = False
    for prefix, files in sorted(prefix_groups.items()):
        if len(files) <= 1:
            continue
        non_grandfathered = [f for f in files if f not in whitelist]
        if non_grandfathered:
            logger.error(
                "Duplicate migration prefix '{}' has non-grandfathered files: {}",
                prefix,
                non_grandfathered,
            )
            failed = True
        else:
            logger.info(
                "Duplicate prefix '{}' is fully grandfathered ({}), skipping.",
                prefix,
                files,
            )

    if failed:
        logger.error(
            "Migration prefix check FAILED. "
            "Rename conflicting files or add them to migration_prefix_whitelist.txt."
        )
        return 1

    logger.info("Migration prefix check PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
