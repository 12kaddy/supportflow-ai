"""Check the filesystem holding Docker data before optional model downloads."""

import argparse
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path.cwd().anchor)
    parser.add_argument("--required-gib", type=float, default=20)
    args = parser.parse_args()
    if args.required_gib <= 0:
        parser.error("Required space must be positive")
    free = shutil.disk_usage(args.path).free / (1024**3)
    print(
        f"Filesystem: {args.path.resolve()}; available: {free:.2f} GiB; requested headroom: {args.required_gib:.2f} GiB"
    )
    if free < args.required_gib:
        print(
            "Insufficient space. Do not pull local-model images here. Free space or relocate Docker data first."
        )
        return 2
    print(
        "Filesystem headroom check passed; also check Docker's own disk/memory limits and model requirements."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
