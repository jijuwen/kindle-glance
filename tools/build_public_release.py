"""Build deterministic deployment/plugin packages and SHA256 sums."""
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
from public_files import ROOT, source_files
import subprocess
import sys

out = ROOT / 'dist'
out.mkdir(exist_ok=True)


def archive(path, entries):
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as zipfile:
        for source, name in sorted(entries, key=lambda x:x[1]):
            item = ZipInfo(name, (2026,9,28,0,0,0))
            item.compress_type = ZIP_DEFLATED
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            zipfile.writestr(item, source.read_bytes())
    with ZipFile(path) as zipfile:
        assert zipfile.testzip() is None
        assert sorted(zipfile.namelist()) == sorted(name for _,name in entries)
        for source, name in entries:
            assert zipfile.read(name) == source.read_bytes()


deploy = out/'kindleglance-deploy-0.2.0.zip'
archive(deploy, [(p,p.relative_to(ROOT).as_posix()) for p in source_files()])
plugin=ROOT/'kindle-plugin'
entries=[(p,'koreader/plugins/trmnl.koplugin/'+p.name) for p in (plugin/'trmnl.koplugin').glob('*.lua')]
assert len(entries)==13
entries.append((plugin/'LICENSE','koreader/plugins/trmnl.koplugin/LICENSE'))
plugin_zip = out/'kindleglance-plugin-1.1.0.zip'
archive(plugin_zip, entries)
subprocess.run([sys.executable,str(ROOT/'kindle-launcher-ab/build.py')], check=True)
launcher=ROOT/'kindle-launcher-ab/dist/kindleglance-launcher-1.1.0.zip'
(out/launcher.name).write_bytes(launcher.read_bytes())
(out/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in sorted((deploy, plugin_zip, out/launcher.name))), encoding='ascii')
print('Built and verified deployment, plugin and A/B launcher archives')
