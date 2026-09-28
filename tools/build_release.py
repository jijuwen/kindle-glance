"""Package the current server source with an explicit, secret-free allowlist."""
from pathlib import Path
import hashlib
import tarfile

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'kindle-display'
files=[source/name for name in ('README.md','Dockerfile','compose.yaml','.env.example','.dockerignore',
                              'requirements.txt','requirements-dev.txt')]
files += list(source.glob('test_*.py'))
files += [p for p in (source/'app').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
out=source/'dist'
out.mkdir(exist_ok=True)
target=out/'kindle-display-source.tar.gz'
with tarfile.open(target,'w:gz') as archive:
    archive.add(ROOT/'LICENSE', arcname='LICENSE')
    for p in sorted(files): archive.add(p,arcname='kindle-display/'+p.relative_to(source).as_posix())
with tarfile.open(target) as archive:
    for p in files:
        assert archive.extractfile('kindle-display/'+p.relative_to(source).as_posix()).read()==p.read_bytes()
digest=hashlib.sha256(target.read_bytes()).hexdigest()
(out/'SHA256SUMS').write_text(f'{digest}  {target.name}\n',encoding='ascii')
print(f'Verified {len(files)} server files; {target.stat().st_size} bytes')
