"""Check fixture provenance and run plugin suites in isolated LuaJIT runtimes."""
from pathlib import Path
import os
import sys
import hashlib
import argparse

ROOT = Path(__file__).resolve().parents[1]
try:
    from lupa.luajit21 import LuaRuntime
except ImportError:
    raise SystemExit('Install test dependencies: python -m pip install -r requirements-dev.txt')

os.chdir(ROOT)
parser = argparse.ArgumentParser()
parser.add_argument('suites', nargs='*', choices=None)
parser.add_argument('--verbose', action='store_true')
args = parser.parse_args()
suites = ('stage1', 'stage2', 'loop', 'board', 'sleep_display', 'transport')
if any(name not in suites for name in args.suites):
    parser.error('Unknown suite; choose from ' + ', '.join(suites))
fixtures = ROOT / 'kindle-plugin/tests/fixtures/koreader'
for line in (fixtures / 'SHA256SUMS').read_text().splitlines():
    digest, name = line.split('  ', 1)
    assert hashlib.sha256((fixtures / name).read_bytes()).hexdigest() == digest, f'Fixture changed: {name}'
syntax = LuaRuntime()
for path in (ROOT / 'kindle-plugin/trmnl.koplugin').glob('*.lua'):
    syntax.execute('assert(loadfile(...))', path.relative_to(ROOT).as_posix())
for name in args.suites or suites:
    runtime = LuaRuntime(unpack_returned_tuples=True)
    lines = []
    runtime.globals().print = lambda *parts: lines.append('\t'.join(map(str, parts)))
    try:
        runtime.execute((ROOT/'kindle-plugin/tests'/f'{name}.lua').read_text(encoding='utf-8'))
    except Exception:
        print('\n'.join(lines[-20:]))
        raise
    print('\n'.join(lines) if args.verbose else lines[-1])
print(f'All {len(args.suites or suites)} plugin test suites passed; Lua syntax and fixture hashes verified')
