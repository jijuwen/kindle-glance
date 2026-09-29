"""Render public examples from current code, synthetic weather and isolated state.

Run with the server dependencies, CJK fonts and Chromium installed.
FONT_PATH/FONT_BOLD_PATH may point to local CJK fonts on Windows.
"""
import argparse
from datetime import datetime, timedelta
import html
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kindle-display'))


def sample_weather(now):
    codes = (2, 3, 61, 3, 2, 0, 1)
    return {
        'temperature': 27, 'apparent': 29, 'label': '多云', 'code': 2, 'is_day': False,
        'observed_at': now.isoformat(), 'wind': 11, 'wind_direction': 90,
        'gust': 17, 'rain_now': 0, 'low': 24, 'high': 30, 'rain': 20,
        'forecast': [{'date': (now.date()+timedelta(days=i)).isoformat(),
                      'high': (30,29,28,29,30,31,30)[i], 'low': 24,
                      'rain': (20,30,70,35,15,5,10)[i], 'code': code,
                      'label': ('多云','阴','小雨','阴','多云','晴朗','晴朗')[i]}
                     for i, code in enumerate(codes)],
        'hourly': [{'time': (now.replace(minute=0,second=0)+timedelta(hours=i+1)).isoformat(),
                    'temperature': (26,26,25,25,24,24,25,26,27,28,29,30)[i],
                    'apparent': 28, 'rain': 20, 'wind': 8+i, 'wind_direction': 90,
                    'code': 2, 'is_day': i>=5} for i in range(12)],
    }


def run(now, output):
    # Import only after binding DATA_DIR to a new temporary directory. Never read
    # a deployed account, token, weather cache or persistent configuration.
    from app import main, settings
    from app.shan_shui import _chromium_executable
    from playwright.sync_api import sync_playwright
    import uvicorn
    original_font=main.font
    def preview_font(size, bold=False):
        face=original_font(size,bold)
        # Variable CJK fonts may default to Thin; match the Regular/Bold
        # static faces used by the production Linux image.
        try:
            axes=face.get_variation_axes()
            face.set_variation_by_axes([700 if bold else 400 if a['name']==b'Weight' else a['default'] for a in axes])
        except (OSError, AttributeError):
            pass
        return face
    main.font=preview_font
    weather=sample_weather(now)
    renderers={
        'day-night': lambda: main.draw_day_night(now,main.font,24.4798,118.0894,'厦门市'),
        'weather-glance': lambda: main.draw_weather_glance(weather,now,main.font,'厦门市'),
        'simple-calendar': lambda: main.draw_calendar(now,main.font),
        'hourly-weather': lambda: main.draw_hourly_weather(weather,now,main.font,'厦门市'),
        'shan-shui': lambda: main.render_original(1648,1236,'2026-09-30:night'),
        'year-progress': lambda: main.draw_year_progress(now,main.font),
        'daily-overview': lambda: main.draw_overview(1648,1236,weather,now,main.font,'厦门市'),
        'time-scales': lambda: main.draw_time_scales(now,main.font),
    }
    for page_id, render in renderers.items():
        render().save(output/(page_id+'.png'),optimize=True)
        print('Rendered '+page_id,flush=True)

    settings.bootstrap(main.DATA_DIR)
    credentials=settings.credentials(main.DATA_DIR)
    credentials['ADMIN_PASSWORD_HASH']=settings.password_hash('public-demo-only')
    settings.atomic_json(main.DATA_DIR/'credentials.json',credentials)
    settings.save(main.DATA_DIR,{'location':{'name':'厦门市','id':'demo','latitude':24.4798,'longitude':118.0894},
        'timezone':'Asia/Shanghai','external_base_url':'https://kindleglance.example',
        'selected_pages':['simple-calendar'],'setup_state':'complete'},1)
    # Disable the periodic renderer only for this disposable screenshot server;
    # the UI and its API routes execute unchanged.
    server=uvicorn.Server(uvicorn.Config(main.app,host='127.0.0.1',port=0,lifespan='off',log_level='error'))
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(32)
    port=listener.getsockname()[1]
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.05)
        assert server.started
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=_chromium_executable(),headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1180},device_scale_factor=1)
            page.context.add_cookies([{'name':main.ADMIN_SESSION_COOKIE,'value':main.make_admin_session(),'url':f'http://127.0.0.1:{port}'}])
            page.goto(f'http://127.0.0.1:{port}/admin/settings',wait_until='networkidle')
            page.locator('#region-settings').wait_for()
            assert page.locator('#connection-info').is_hidden()
            page.screenshot(path=str(output/'setup-desktop.png'))
            cards=''.join(f'<figure><img src="{(output/(key+".png")).as_uri()}"/><figcaption><span>{i:02d}</span>{html.escape(main.PAGE_DEFINITIONS[key]["title"])}</figcaption></figure>' for i,key in enumerate(renderers,1))
            document='''<!doctype html><meta charset="utf-8"><style>
            *{box-sizing:border-box}body{margin:0;background:#edf0ec;color:#16211b;font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif}
            main{padding:56px;width:1600px}header{display:flex;align-items:end;justify-content:space-between;margin-bottom:34px}
            h1{font-size:42px;letter-spacing:-1px;margin:0 0 8px}p{margin:0;color:#59645c;font-size:19px}.version{font-size:20px;padding:10px 18px;border:1px solid #bdc8bd;border-radius:30px}
            .grid{display:grid;grid-template-columns:1fr 1fr;gap:26px}figure{margin:0;padding:12px 12px 0;background:white;border:1px solid #d5dbd3;border-radius:12px;overflow:hidden}
            img{display:block;width:100%;aspect-ratio:4/3;object-fit:contain;background:white}figcaption{padding:16px 8px 18px;font-size:23px;border-top:1px solid #e9ede6}figcaption span{font-size:16px;color:#778775;margin-right:14px}
            footer{margin-top:26px;font-size:16px;color:#657263}
            </style><main><header><div><h1>KindleGlance</h1><p>天气 · 日历 · 世界昼夜 · 山水 · 时间进度</p></div><div class="version">v0.2.0 正式版</div></header><div class="grid">'''+cards+'''</div><footer>当前版本原生渲染 · 示例日期 '''+now.date().isoformat()+''' · 天气为演示数据</footer></main>'''
            gallery=Path(os.environ['DATA_DIR'])/'gallery.html';gallery.write_text(document,encoding='utf-8')
            page.set_viewport_size({'width':1600,'height':1200})
            page.goto(gallery.as_uri(),wait_until='networkidle')
            assert page.locator('img').evaluate_all('(imgs)=>imgs.every(i=>i.complete&&i.naturalWidth>0)')
            page.screenshot(path=str(output/'showcase.png'),full_page=True)
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
    (output/'render-manifest.json').write_text(json.dumps({'version':'0.2.0','rendered_at':now.isoformat(),
        'weather':'synthetic demonstration','city':'厦门市','pages':list(renderers),'private_data':False},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--at',default='2026-09-30T00:05:00+08:00')
    args=parser.parse_args()
    now=datetime.fromisoformat(args.at).astimezone(ZoneInfo('Asia/Shanghai'))
    output=ROOT/'previews';output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='kindleglance-public-') as temporary:
        os.environ['DATA_DIR']=temporary
        os.environ['ADMIN_COOKIE_SECURE']='0'
        run(now,output)
