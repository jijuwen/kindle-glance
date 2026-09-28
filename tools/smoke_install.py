"""Real HTTP smoke test for a disposable container; never target production."""
import argparse
import http.cookiejar
import json
import re
import urllib.request

parser=argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:3001')
parser.add_argument('--code-file', required=True)
args=parser.parse_args()
if not args.url.startswith('http://127.0.0.1:'):
    raise SystemExit('Smoke test requires a disposable localhost instance')
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
csrf=''
def call(path, data=None):
    request=urllib.request.Request(args.url+path, data=json.dumps(data).encode() if data is not None else None,
                                   headers={'Content-Type':'application/json','X-CSRF-Token':csrf})
    return opener.open(request,timeout=60)
code=json.load(open(args.code_file,encoding='utf-8'))['code']
call('/admin/api/setup/claim',{'code':code,'password':'disposable smoke password'})
html=call('/admin/settings').read().decode()
csrf=re.search('name="csrf-token" content="([^"]+)"',html)[1]
state=json.load(call('/admin/api/settings'))
state=json.load(call('/admin/api/settings',{'revision':state['revision'],'timezone':'Asia/Shanghai',
    'location':{'name':'示例城市','latitude':31.23,'longitude':121.47,'id':'smoke'},
    'external_base_url':args.url,'selected_pages':['simple-calendar']}))
call('/admin/api/setup/finish',{'revision':state['revision']})
call('/admin/api/pages/simple-calendar/render',{})
assert call('/admin/pages/simple-calendar/preview').headers['Content-Type']=='image/png'
token=json.load(call('/admin/api/device/token'))['token']
request=urllib.request.Request(args.url+'/api/display',headers={'access-token':token})
display=json.load(opener.open(request,timeout=30))
assert opener.open(display['image_url']).headers['Content-Type']=='image/png'
assert not json.load(call('/admin/api/codex/accounts'))['installed']
print('PASS: clean claim, setup, real CJK render, authenticated image roundtrip, optional collector absent')
