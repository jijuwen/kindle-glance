"""Linux integration: real LuaSec handshakes against disposable local TLS."""
import http.server
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
lua=shutil.which('lua5.1') or shutil.which('lua')
if not lua:
    raise SystemExit('Install lua5.1, lua-sec and lua-socket to run live TLS verification')

with tempfile.TemporaryDirectory() as folder:
    folder=Path(folder)
    for name, hostname in [('valid','localhost'),('wrong','wrong.example.test'),('untrusted','localhost')]:
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(folder/f'{name}.key'),
                        '-out',str(folder/f'{name}.crt'),'-days','1','-subj',f'/CN={hostname}',
                        '-addext',f'subjectAltName=DNS:{hostname}'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    script=folder/'client.lua'
    script.write_text('''package.path="kindle-plugin/trmnl.koplugin/?.lua;"..package.path
local T=require("trmnl_transport")
local sink={}
local ok,status=T.request({url=arg[1],headers={["access-token"]="synthetic-test"},sink=require("ltn12").sink.table(sink)},arg[2])
print(tostring(ok).." "..tostring(status))
''')
    for name,path,expected in [('valid','/',200),('wrong','/',None),('untrusted','/',None),('valid','/redirect',302)]:
        received=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.path)
                self.send_response(302 if self.path=='/redirect' else 200)
                if self.path=='/redirect': self.send_header('Location','http://127.0.0.1:1/stolen')
                self.send_header('Content-Length','2')
                self.end_headers()
                self.wfile.write(b'ok')
            def log_message(self,*args): pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(folder/f'{name}.crt',folder/f'{name}.key')
        server.socket=context.wrap_socket(server.socket,server_side=True)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            trust=folder/('wrong.crt' if name=='wrong' else 'valid.crt')
            result=subprocess.run([lua,str(script),f'https://localhost:{server.server_port}{path}',str(trust)],cwd=ROOT,
                                  capture_output=True,text=True,timeout=15,check=True)
            if expected:
                assert result.stdout.strip()==f'1 {expected}', result.stdout+result.stderr
                assert received==[path], received
            else:
                assert result.stdout.startswith('nil '), result.stdout
                assert not received, 'HTTP headers were sent before verification'
        finally:
            server.shutdown();server.server_close();worker.join()
    print('PASS: real LuaSec trusted peer, wrong hostname, untrusted CA and blocked redirect')
