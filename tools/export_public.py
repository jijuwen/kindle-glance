"""Export an audited tree without personal Git history or runtime data."""
import argparse
from pathlib import Path
import shutil
from public_files import ROOT, source_files

parser = argparse.ArgumentParser()
parser.add_argument('destination', type=Path)
args = parser.parse_args()
destination = args.destination.resolve()
if destination == ROOT or ROOT in destination.parents and '.local' not in destination.relative_to(ROOT).parts:
    raise SystemExit('Use an empty directory outside the source tree or under .local')
destination.mkdir(parents=True, exist_ok=True)
if any(destination.iterdir()):
    raise SystemExit('Destination must be empty; never overwrite an existing checkout')
for path in source_files():
    target = destination / path.relative_to(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
print(f'Exported {len(source_files())} allowlisted files; no Git history copied')
