"""Freeze the annual garden's numbered drawings as SVG + grayscale masks.

The drawings themselves live in the server's pen module; this builder writes the
committed library, its manifest and the review atlas.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'kindle-display/app/assets/annual-garden'
sys.path.insert(0, str(ROOT / 'kindle-display'))
from app.garden_drawings import ADDITIONS, FIRST_ADDITION, ROWS, Pen, draw_asset  # noqa: E402


def write_drawing(pen, svg_path, png_path):
    # The committed assets use CRLF; write the same bytes on every platform.
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 120" fill="none" stroke="#000" stroke-linecap="round" stroke-linejoin="round">\n'+ '\n'.join(pen.svg)+'\n</svg>\n',encoding='utf-8',newline='\r\n')
    mask=pen.mask()
    # PNG compression differs between zlib builds; keep a file whose pixels match.
    if png_path.exists():
        with Image.open(png_path) as existing:
            if existing.mode=='RGBA' and existing.getchannel('A').tobytes()==mask.tobytes():
                return mask
    rgba=Image.new('RGBA',mask.size,(0,0,0,0)); rgba.putalpha(mask)
    rgba.save(png_path,optimize=True)
    return mask


def record(pen,stem,shapes):
    svg_path=DEST/'svg'/f'{stem}.svg';png_path=DEST/'png'/f'{stem}.png'
    mask=write_drawing(pen,svg_path,png_path)
    digest=hashlib.sha256(svg_path.read_bytes()).hexdigest()
    assert digest not in shapes
    shapes.add(digest)
    box=mask.getbbox()
    assert box and 1<=box[0]<box[2]<200 and 1<=box[1]<box[3]<240,stem
    return {'svg':f'svg/{stem}.svg','png':f'png/{stem}.png','sha256':digest,
            'png_sha256':hashlib.sha256(png_path.read_bytes()).hexdigest(),'ink_bbox':box}


def build():
    (DEST/'svg').mkdir(parents=True,exist_ok=True)
    (DEST/'png').mkdir(exist_ok=True)
    kinds=[kind for row in ROWS for kind in row.split()]+['pine']
    assert len(ROWS)==26 and all(len(row.split())==14 for row in ROWS)
    assert len(kinds)==365
    records=[]
    shapes=set()
    for index,kind in enumerate(kinds,1):
        stem=f'{index:03d}-{kind}'
        records.append({'id':stem,'subject':kind,'reference_slot':index,**record(draw_asset(kind,index),stem,shapes)})
    # A separate blossom prevents repeating an existing day on leap years.
    pen=Pen(366);pen.stem(top=43,leaves=3);pen.flower(49,39,18,8,smile=True)
    pen.flower(27,68,8,5);pen.flower(73,82,7,5)
    write_drawing(pen,DEST/'svg/leap-day.svg',DEST/'png/leap-day.png')
    added=[]
    for offset,(kind,drawer,variant) in enumerate(ADDITIONS):
        number=FIRST_ADDITION+offset;stem=f'{number:03d}-{kind}'
        pen=Pen(number);drawer(pen,variant)
        added.append({'id':stem,'subject':kind,'variant':'AB'[variant],**record(pen,stem,shapes)})
    manifest={'version':4,'count':365,'format':'individually authored SVG paths and matching transparent black masks',
              'provenance':'Reconstructed vector illustrations informed by the user-provided One Year garden screenshots; not the original application asset files.',
              'reference':'user-full-garden-2026.jpg','subjects':sorted(set(kinds)),
              'assets':records,'leap_day':{'svg':'svg/leap-day.svg','png':'png/leap-day.png'},
              'additions_provenance':'Original drawings authored for KindleGlance with the same pen; not derived from the reference screenshots.',
              'additions':added}
    (DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8',newline='\r\n')
    output=ROOT/'previews/generated/annual-garden'
    output.mkdir(parents=True,exist_ok=True)
    atlas=Image.new('L',(1800,132*math.ceil((len(records)+len(added))/20)),255);draw=ImageDraw.Draw(atlas)
    face=ImageFont.truetype(str(DEST/'fonts/ShantellSans.ttf'),14)
    face.set_variation_by_axes([500,40,20,0])
    for i,item in enumerate(records+added):
        x=(i%20)*90;y=(i//20)*132
        with Image.open(DEST/item['png']) as asset:
            asset=asset.resize((80,96),Image.Resampling.LANCZOS)
            atlas.paste(0,(x+5,y+6,x+85,y+102),asset.getchannel('A'))
        draw.text((x+45,y+108),item['id'][:3],font=face,fill=0,anchor='mt')
    atlas.save(output/'365-assets.png',optimize=True)
    print(json.dumps({'assets':len(records),'additions':len(added),'unique_svg_hashes':len(shapes),
                      'subject_families':len(set(kinds)),'addition_subjects':len({a['subject'] for a in added}),
                      'leap_day_bonus':1,'atlas':str(output/'365-assets.png')},ensure_ascii=False))


if __name__=='__main__':build()
