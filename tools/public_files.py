"""Explicit source allowlist, shared by export and release packaging."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ['README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md',
              '.gitignore', '.gitattributes', '.env.example', 'compose.yaml', 'compose.codex.yaml', 'requirements-dev.txt']
DOCS = ['INSTALL.md', 'CONFIGURATION.md', 'UPGRADING.md', 'TROUBLESHOOTING.md', 'COMPATIBILITY.md',
        'OPEN_SOURCE_PLAN.md', 'IMPLEMENTATION_STATUS.md', 'RELEASE_CHECKLIST.md', 'DEVICE_CONNECTION.md']
TOOLS = ['build_release.py', 'build_public_release.py', 'public_files.py', 'export_public.py', 'test_plugin.py',
         'test_tls_live.py', 'smoke_install.py', 'check_public.py', 'render_public_previews.py']


def source_files(root=ROOT):
    files = [root / p for p in ROOT_FILES] + [root / 'docs' / p for p in DOCS]
    files += [root / 'tools' / p for p in TOOLS]
    missing = [str(p.relative_to(root)) for p in files if not p.is_file() or p.is_symlink()]
    if missing:
        raise ValueError('Required public sources missing: ' + ', '.join(missing))
    for folder in ('kindle-display', 'kindle-plugin', 'kindle-launcher-ab', 'previews', 'tools/codex-collector', '.github'):
        for path in (root / folder).rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root)
            if any(part in {'dist', 'data', '__pycache__', '.pytest_cache', 'generated'} for part in rel.parts):
                continue
            if path.name == '.env' or path.name.startswith('.env.') and path.name != '.env.example':
                continue
            if path.suffix in {'.pyc', '.log', '.zip'} or path.name == 'apikey.txt':
                continue
            # Old hash manifest describes the historical 1.0.2 baseline.
            if path.name in {'SOURCE_SHA256SUMS', 'BASELINE_SHA256SUMS'}:
                continue
            files.append(path)
    return sorted(set(p for p in files if p.is_file()))
