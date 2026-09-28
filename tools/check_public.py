"""Fail on runtime artifacts or author infrastructure in the public tree."""
import re
from public_files import ROOT, source_files

errors=[]
files=source_files()
for p in files:
    rel=p.relative_to(ROOT).as_posix()
    if p.name in {'credentials.json','auth.json','setup-code.json','apikey.txt','.env'}:
        errors.append((rel,'runtime data'))
    if p.suffix in {'.png','.ttf','.ttc','.woff','.woff2'}:
        continue
    try:
        text=p.read_text(encoding='utf-8')
    except UnicodeError:
        continue
    for label,pattern in [('private key',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
                          ('GitHub token',r'gh[pousr]_[A-Za-z0-9]{30,}'),
                          ('author host',r'ai-pass\.top'),('personal path',r'[CD]:[\\/]Users[\\/]win[\\/]')]:
        if re.search(pattern,text): errors.append((rel,label))
    if p.suffix=='.md':
        for target in re.findall(r'\]\(([^)]+)\)',text):
            if '://' in target or target.startswith('#') or target.startswith('mailto:'):
                continue
            target=target.split('#')[0]
            if target and not (p.parent/target).exists():
                errors.append((rel,'broken link: '+target))
for rel,reason in errors:
    print(f'{rel}: {reason}')
if errors: raise SystemExit(1)
print(f'PASS: {len(files)} public files; restricted path/token patterns and local Markdown links')
