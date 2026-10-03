"""Author the annual garden's independent pen drawings as SVG + grayscale masks.

The source is vector geometry, not cropped screenshots. The screenshot references
inform the subjects and drawing vocabulary; these are reconstructed illustrations.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
import re

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'kindle-display/app/assets/annual-garden'
TAU = math.tau


class Pen:
    """Small absolute SVG path authoring surface, with matching Pillow output."""
    def __init__(self, number: int):
        self.rng = random.Random(48371 + number * 7919)
        self.stroke_rng = random.Random(7351 + number * 3571)
        self.svg: list[str] = []
        self.image = Image.new('L', (400, 480), 255)
        self.draw = ImageDraw.Draw(self.image)
        self.weight = 3.7

    def path(self, d: str, fill: str = 'none', weight: float | None = None):
        tokens = re.findall(r'[MLCQZ]|-?\d+(?:\.\d+)?', d)
        command, index, current, first = '', 0, (0., 0.), (0., 0.)
        points, subpaths, normalized = [], [], []
        # Vary pressure separately from geometry so the same subject keeps its
        # shape while fine details and the outer pen strokes gain clear weight.
        width = (weight * 1.34 if weight is not None else self.weight) * self.stroke_rng.uniform(.90,1.10)
        while index < len(tokens):
            token = tokens[index]
            if token.isalpha():
                command = token
                index += 1
                normalized.append(command)
                if command == 'Z':
                    points.append(first)
                    current = first
                    continue
            length = {'M':2, 'L':2, 'C':6, 'Q':4}.get(command)
            if length is None:
                raise ValueError(d)
            values = [float(v) for v in tokens[index:index+length]]
            index += length
            # Every stroke is authored once and receives tiny, reproducible pen
            # irregularities. No display-time randomness changes a day's drawing.
            values = [v + self.rng.uniform(-.32,.32) for v in values]
            # Reserve paper around the thicker round caps. The renderer trims
            # this margin to the real ink bounds, so it costs no garden space.
            values = [4+v*.92 if i%2==0 else 4.8+v*.92 for i,v in enumerate(values)]
            normalized.extend(f'{v:.2f}' for v in values)
            if command == 'M':
                if points: subpaths.append(points)
                current = first = tuple(values)
                points = [current]
            elif command == 'L':
                current = tuple(values)
                points.append(current)
            elif command == 'Q':
                x0,y0 = current
                x1,y1,x2,y2 = values
                for step in range(1,25):
                    t=step/24; u=1-t
                    points.append((u*u*x0+2*u*t*x1+t*t*x2,u*u*y0+2*u*t*y1+t*t*y2))
                current=(x2,y2)
            elif command == 'C':
                x0,y0=current
                x1,y1,x2,y2,x3,y3=values
                for step in range(1,33):
                    t=step/32; u=1-t
                    points.append((u**3*x0+3*u*u*t*x1+3*u*t*t*x2+t**3*x3,
                                   u**3*y0+3*u*u*t*y1+3*u*t*t*y2+t**3*y3))
                current=(x3,y3)
        if points: subpaths.append(points)
        self.svg.append(f'<path d="{" ".join(normalized)}" fill="{fill}" stroke-width="{width:.2f}"/>')
        for subpath in subpaths:
            scaled=[(x*4,y*4) for x,y in subpath]
            if fill!='none': self.draw.polygon(scaled,fill=255 if fill=='white' else 0)
            self.draw.line(scaled,fill=0,width=round(width*4),joint='curve')
            radius=width*2
            for x,y in (scaled[0],scaled[-1]):
                self.draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=0)

    def curve(self, points, close=False, fill='none', weight=None):
        points=list(points)
        if close:
            extended=[points[-1]]+points+[points[0],points[1]]
        else:
            extended=[points[0]]+points+[points[-1]]
        d=f'M {points[0][0]:.2f} {points[0][1]:.2f}'
        for i in range(1,len(extended)-2):
            a,b,c,e=extended[i-1:i+3]
            c1=(b[0]+(c[0]-a[0])/6,b[1]+(c[1]-a[1])/6)
            c2=(c[0]-(e[0]-b[0])/6,c[1]-(e[1]-b[1])/6)
            d+=f' C {c1[0]:.2f} {c1[1]:.2f} {c2[0]:.2f} {c2[1]:.2f} {c[0]:.2f} {c[1]:.2f}'
        if close:d+=' Z'
        self.path(d,fill,weight)

    def ellipse(self,x,y,rx,ry=None,fill='white',angle=0):
        ry=rx if ry is None else ry
        a=math.radians(angle)
        points=[]
        for i in range(20):
            t=TAU*i/20
            jitter=1+self.rng.uniform(-.025,.025)
            px=rx*math.cos(t)*jitter; py=ry*math.sin(t)*jitter
            points.append((x+px*math.cos(a)-py*math.sin(a),y+px*math.sin(a)+py*math.cos(a)))
        self.curve(points,True,fill)

    def dot(self,x,y,r=1.2):
        self.ellipse(x,y,r,fill='black')

    def leaf(self,x,y,dx,dy,width=8,vein=False):
        length=math.hypot(dx,dy); nx=-dy/length*width; ny=dx/length*width
        self.path(f'M {x} {y} Q {x+dx*.45+nx} {y+dy*.45+ny} {x+dx} {y+dy} Q {x+dx*.55-nx} {y+dy*.55-ny} {x} {y} Z','white')
        if vein:self.path(f'M {x} {y} Q {x+dx*.45} {y+dy*.6} {x+dx} {y+dy}',weight=1.7)

    def stem(self,x=50,top=42,bottom=112,bend=0,leaves=3):
        self.path(f'M {x} {bottom} C {x+bend+5} {bottom-20} {x+bend-7} {top+15} {x} {top}')
        for i in range(leaves):
            y=bottom-14-(bottom-top-28)*(i+.12)/max(1,leaves-.5)
            side=1 if i%2==0 else -1
            self.leaf(x+bend*.3,y,side*self.rng.uniform(23,31),-self.rng.uniform(12,20),self.rng.uniform(6.5,8.5),i%2==0)

    def face(self,x,y,size=7,smile=True):
        self.dot(x-size*.55,y,1)
        self.dot(x+size*.55,y-.5,1)
        if smile:self.path(f'M {x-size*.5} {y+4} Q {x} {y+9} {x+size*.6} {y+3}',weight=1.8)

    def flower(self,x,y,r=13,petals=6,kind='round',smile=False):
        extent=r*(1.75 if kind=='long' else 1.27)
        x=max(extent+4,min(x,96-extent))
        y=max(extent+4,min(y,116-extent))
        if kind=='long':
            for i in range(petals):
                t=TAU*i/petals+.2+self.rng.uniform(-.09,.09)
                length=r*self.rng.uniform(.72,.94)
                self.ellipse(x+math.cos(t)*r*.65,y+math.sin(t)*r*.65,length,r*self.rng.uniform(.2,.34),angle=math.degrees(t))
        else:
            points=[]
            sizes=[self.rng.uniform(.88,1.14) for _ in range(petals)]
            for i in range(petals*6):
                t=TAU*i/(petals*6)
                radius=r*(.8+.25*math.cos(petals*t))*sizes[(i//6)%petals]
                points.append((x+radius*math.cos(t),y+radius*math.sin(t)))
            self.curve(points,True,'white')
        self.ellipse(x,y,r*.36,r*.32)
        if smile:self.face(x,y,r*.28)
        elif r>10:
            for i in range(4):
                a=TAU*i/4
                self.dot(x+math.cos(a)*r*.16,y+math.sin(a)*r*.16,.65)

    def spiral(self,x,y,r=15,turns=2.3):
        points=[]
        for i in range(90):
            t=i/89*turns*TAU
            radius=r*(.1+.9*i/89)
            points.append((x+math.cos(t)*radius,y+math.sin(t)*radius))
        self.curve(points,weight=2.5)

    def output(self,path):
        path.with_suffix('.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 120" fill="none" stroke="#000" stroke-linecap="round" stroke-linejoin="round">\n'+ '\n'.join(self.svg)+'\n</svg>\n',encoding='utf-8')
        mask=ImageOps.invert(self.image.resize((200,240),Image.Resampling.LANCZOS))
        rgba=Image.new('RGBA',mask.size,(0,0,0,0)); rgba.putalpha(mask)
        rgba.save(path.with_suffix('.png'),optimize=True)
        return mask


def foliage(p: Pen,kind: str,v: int):
    if kind in ('daisy','sunflower','clover','rose','bell','tulip','lily','droop','spiralflower'):
        bend=(-1 if v%2 else 1)*(3+v%9)
        top=34+v%9
        p.stem(top=top,bend=bend,leaves=3+v%2)
        if kind in ('daisy','sunflower','clover'):
            layout=(v//4)%6
            head='long' if kind=='clover' else 'round'
            petals=5+v%7
            smile=kind=='sunflower' or v%5==0
            if layout==0:
                p.flower(50,top,21+v%3,petals,head,smile)
            elif layout==1:
                p.path('M 50 65 Q 29 47 25 29 M 52 66 Q 76 60 75 47')
                p.flower(25,29,14+v%3,petals,head,smile)
                p.flower(75,46,12+v%4,max(5,petals-1),head)
                p.leaf(50,85,-27,-18,8)
            elif layout==2:
                p.path('M 50 76 Q 20 55 21 46 M 51 76 Q 75 58 81 53')
                for x,y,r in [(22,44,12),(50,24,15),(80,50,10)]:p.flower(x,y,r,petals,head,smile and x==50)
                p.leaf(49,100,28,-12,8)
            elif layout==3:
                p.path('M 50 82 Q 72 62 69 45')
                p.flower(48,29,19+v%4,petals,head,smile)
                p.flower(69,55,10,5,head)
                p.leaf(48,89,-27,-24,10,True)
            elif layout==4:
                p.path('M 49 110 Q 27 76 26 52 M 52 99 Q 73 87 76 69')
                for x,y,r in [(50,24,17),(26,54,11),(77,69,9)]:p.flower(x,y,r,petals,head,smile and x==50)
                p.leaf(51,85,30,-25,8)
            else:
                p.flower(50,32,23,petals,head,True)
                p.leaf(50,72,-27,-17,10,True)
                p.leaf(52,90,27,-16,9,True)
            if kind=='sunflower':
                for i in range(8):
                    a=TAU*i/8;p.path(f'M {50+math.cos(a)*10} {top+math.sin(a)*10} L {50+math.cos(a)*14} {top+math.sin(a)*14}',weight=1.5)
        elif kind=='tulip':
            p.path(f'M 50 {top+9} C 27 {top-1} 30 {top-18} 34 {top-25} L 45 {top-16} L 50 {top-30} L 57 {top-15} L 66 {top-25} C 72 {top-2} 65 {top+7} 50 {top+9} Z','white')
            p.path(f'M 50 {top+5} L 50 {top-15}')
        elif kind=='bell':
            p.path(f'M 50 {top+4} C 60 {top-10} 73 {top-5} 71 {top+9} L 77 {top+19} Q 68 {top+22} 59 {top+16} L 61 {top+9} C 63 {top-3} 58 {top-7} 50 {top+4}')
            p.path(f'M 48 {top+4} C 34 {top-5} 26 {top+7} 27 {top+19} L 22 {top+24} Q 34 {top+29} 41 {top+22} C 35 {top+17} 43 {top+1} 48 {top+4}')
        elif kind=='droop':
            for dx,dy in [(-20,13),(-10,20),(7,23),(21,13)]:
                p.leaf(50,top,dx,dy,5)
            p.dot(50,top,3)
        elif kind=='rose':
            p.spiral(50,top,17,2.2)
            if v%3:
                p.path('M 51 90 Q 28 75 23 53')
                p.spiral(23,49,9,1.5)
                p.leaf(31,72,-15,-9,6)
        elif kind=='spiralflower':
            p.flower(50,top,18,7);p.spiral(50,top,10,1.7)
        else:
            p.path(f'M 50 {top+5} C 22 {top-1} 23 {top-21} 36 {top-18} C 41 {top-34} 62 {top-34} 64 {top-15} C 82 {top-17} 82 {top+3} 50 {top+5} Z','white')
            p.path(f'M 50 {top+4} C 58 {top-7} 50 {top-10} 45 {top-17}')
    elif kind=='berries':
        p.path('M 51 111 Q 55 66 47 43 M 50 87 Q 35 75 21 59 M 51 74 Q 70 61 76 43 M 47 52 Q 27 43 31 28')
        for x,y,r in [(21,53,10),(30,27,10),(49,38,11),(76,39,12)]:
            p.ellipse(x,y,r)
            for i in range(5):
                a=TAU*i/5;p.dot(x+math.cos(a)*r*.45,y+math.sin(a)*r*.45,.8)
        p.leaf(51,88,23,-9,7)
    elif kind in ('fern','vine','twig','sprout'):
        bend=-9+v%19
        p.stem(top=18+v%9,bend=bend,leaves=0)
        count=5+v%4 if kind=='fern' else 3+v%4
        for i in range(count):
            y=102-i*(72/max(1,count-1));side=1 if i%2==0 else -1
            x=50+bend*math.sin((y-20)/90*math.pi)
            dx=side*(17+(count-i)*1.8)
            if kind=='twig':
                p.path(f'M {x} {y} L {x+dx} {y-12} M {x+dx} {y-12} L {x+dx} {y-22} M {x+dx} {y-12} L {x+dx+side*10} {y-11}')
            elif kind=='vine':
                p.path(f'M {x} {y} Q {x+dx*.5} {y-9} {x+dx} {y-7}')
                if i%3==v%3:
                    p.spiral(x+dx,y-13,7,1.6)
                else:p.leaf(x+dx*.5,y-7,dx*.65,-16,5)
            else:p.leaf(x,y,dx,-15,5.5 if kind=='fern' else 8,kind=='fern')
        if kind=='sprout':p.ellipse(50,20+v%9,6)
    elif kind in ('grass','seaweed'):
        count=4+v%4
        for i in range(count):
            x=14+i*72/(count-1);height=26+(i*17+v*13)%61
            if kind=='seaweed':
                p.path(f'M {x} 110 C {x-8} 91 {x+10} {110-height+16} {x-2} {110-height}')
            else:
                p.path(f'M {x} 110 L {x-7} {110-height*.64} L {x+2} {110-height*.37} L {x+6} {110-height} L {x+7} 105')
    elif kind=='bamboo':
        for i in range(2+v%3):
            x=24+i*18;top=19+i*7
            p.path(f'M {x-3} 113 Q {x+5} 69 {x} {top} L {x+8} {top+1} Q {x+12} 63 {x+5} 113 Z','white')
            for y in range(top+16,110,21):p.path(f'M {x-1} {y} L {x+8} {y+1}')
    elif kind in ('tree','bush','shrub'):
        p.path('M 46 110 L 47 68 L 56 67 L 58 112 M 48 93 L 34 83 M 54 87 L 67 76')
        r=22+v%8 if kind=='tree' else 25+v%8
        points=[]
        for i in range(60):
            t=TAU*i/60;radius=r*(1+.12*math.sin((7+v%4)*t))
            points.append((51+math.cos(t)*radius,45+math.sin(t)*radius*(1 if kind=='tree' else .72)))
        p.curve(points,True,'white')
        if v%3==0:p.face(51,46,8)
        else:
            for x,y in [(36,44),(50,58),(59,34),(69,49),(43,35)]:p.path(f'M {x-2} {y} Q {x} {y+4} {x+3} {y-1}',weight=1.8)
        if kind=='shrub':
            p.path('M 25 112 Q 19 84 27 75 M 77 111 Q 88 90 79 70')
            p.leaf(26,92,-9,-14,5);p.leaf(79,93,11,-11,5)
        elif kind=='tree' and v%3==1:
            for x in (31,39,64,73):
                p.path(f'M {x} 62 C {x-5} 70 {x+6} 77 {x-2} 84',weight=1.9)
        elif kind=='bush' and v%3==2:
            for x in (25,40,64,80):
                p.path(f'M {x} 110 L {x} 84');p.flower(x,80,5,5)
    elif kind=='pine':
        p.path('M 51 113 L 51 92')
        p.path('M 51 14 L 39 35 L 45 33 L 26 52 L 36 51 L 18 71 L 30 70 L 14 91 Q 50 108 86 91 L 71 70 L 80 72 L 64 51 L 73 53 L 57 32 L 65 35 Z','white')
        p.path('M 51 30 L 51 95 M 51 56 L 34 45 M 51 72 L 29 62 M 51 81 L 74 69',weight=2)
    elif kind=='palm':
        p.path('M 38 114 Q 65 70 48 39 L 59 37 Q 77 77 48 114 Z','white')
        for y in (65,80,94):p.path(f'M {49+(y-65)*-.15} {y} L {64+(y-65)*-.3} {y+6}')
        for dx,dy in [(-34,-2),(-25,-20),(2,-28),(29,-18),(38,3),(-36,20),(29,22)]:p.leaf(54,38,dx,dy,6)
    elif kind=='cactus':
        p.path('M 43 114 L 44 71 Q 23 77 20 61 L 20 44 Q 24 35 30 43 L 30 59 L 44 60 L 44 26 Q 53 13 61 27 L 61 75 L 76 71 L 76 56 Q 83 48 87 57 L 86 76 Q 81 88 61 87 L 63 114','white')
        for x,y in [(49,42),(55,68),(53,96),(27,50),(79,68)]:p.path(f'M {x} {y} L {x+1} {y+7}',weight=1.7)
        for x,y in [(44,35),(60,50),(60,99),(24,60),(82,82)]:p.path(f'M {x-4} {y} L {x+4} {y}')
    elif kind=='succulent':
        for dx,dy in [(-33,-16),(-26,-38),(-12,-54),(5,-68),(20,-49),(34,-30),(37,-10)]:p.leaf(50,104,dx,dy,9,True)
        p.path('M 22 112 Q 50 121 82 112')
    else:return False
    return True


def mushroom(p:Pen,v:int):
    count=1+v%4
    for i in range(count):
        x=50+(i-(count-1)/2)*(58/max(1,count));top=24+(i*19+v*7)%26
        r=19 if count==1 else 12
        base=112-i%2*6
        p.path(f'M {x-3} {base} L {x-3} {top+24} L {x+4} {top+24} L {x+5} {base} Z','white')
        p.path(f'M {x-r} {top+24} C {x-r-1} {top-12} {x+r+5} {top-12} {x+r} {top+24} Q {x} {top+29} {x-r} {top+24} Z','white')
        for dx,dy in [(-r*.5,13),(r*.25,7),(r*.5,18)]:p.dot(x+dx,top+dy,1.2)


def fruit(p:Pen,kind:str,v:int):
    if kind in ('apple','orange','pepper','pear','pumpkin','onion'):
        if kind=='pear':
            p.path('M 50 31 C 30 25 37 59 24 70 C 9 107 33 110 50 109 C 76 111 94 96 78 73 C 68 62 67 31 50 31 Z','white')
        elif kind=='onion':
            p.path('M 51 20 C 53 54 24 59 21 81 C 17 117 87 119 82 81 C 80 60 53 55 51 20 Z','white')
            p.path('M 51 26 C 32 82 33 99 50 110 M 53 30 C 74 84 70 100 53 110')
            p.path('M 47 112 L 42 118 M 53 112 L 54 118 M 58 110 L 64 117',weight=1.7)
        else:
            p.path('M 50 43 C 23 29 10 54 19 78 C 25 107 39 115 52 107 C 70 119 91 87 83 59 C 79 37 60 37 50 43 Z','white')
            if kind=='pumpkin':
                p.path('M 47 45 C 25 68 28 104 49 107 M 53 45 C 72 72 71 102 55 108 M 50 45 L 51 108')
            elif kind=='pepper':p.path('M 37 51 C 25 65 34 92 37 96 M 63 51 Q 74 74 66 92')
            elif kind=='orange':
                for x,y in [(33,62),(67,75),(57,92),(31,82),(69,55)]:p.dot(x,y,.65)
            elif v%3==0:p.face(49,74,9)
        p.path('M 51 40 Q 48 25 60 22')
        p.leaf(52,36,18,-16,6)
    elif kind=='strawberry':
        p.path('M 21 42 C 12 70 37 102 50 109 C 64 105 91 70 80 44 Q 50 30 21 42 Z','white')
        p.path('M 28 43 L 23 25 L 39 34 L 49 20 L 56 33 L 74 23 L 72 41 L 61 48 L 51 37 L 39 49 Z','white')
        for x,y in [(29,59),(50,59),(71,58),(38,77),(62,77),(50,93)]:p.path(f'M {x} {y} L {x+1} {y+3}',weight=2)
    elif kind in ('grapes','raspberry'):
        for i in range(5):
            for j in range(5-i):p.ellipse(26+j*12+i*6,36+i*14,7)
        p.path('M 52 30 Q 45 15 59 12');p.leaf(51,23,21,-7,7)
    elif kind=='cherry':
        p.path('M 30 82 Q 32 49 55 27 Q 52 60 71 83')
        p.ellipse(29,91,18,18);p.ellipse(71,92,17,17)
        p.leaf(54,26,-26,-6,7);p.dot(26,87,1);p.dot(68,86,1)
    elif kind=='banana':
        for i in range(3):
            p.path(f'M {60+i*5} 29 C {58+i*4} 67 {41+i*6} 92 {20+i*9} 94 C {52+i*9} 116 {88+i} 75 {75+i*2} 31 Z','white')
        p.path('M 60 30 L 58 18 L 71 16 L 76 33')
    elif kind=='carrot':
        p.path('M 32 53 Q 50 42 69 53 Q 64 81 45 116 Q 36 95 32 53 Z','white')
        for y in [65,80,95]:p.path(f'M {35+(y-65)*.2} {y} L {52+(y-65)*.15} {y+2}',weight=2)
        for dx,dy in [(-20,-22),(-5,-39),(10,-33),(24,-20)]:p.leaf(50,48,dx,dy,5)
    elif kind=='acorn':
        for x,y,a in [(34,62,-20),(69,39,24)]:
            p.ellipse(x,y+18,18,22,angle=a)
            p.path(f'M {x-19} {y+7} Q {x-21} {y-14} {x} {y-14} Q {x+21} {y-14} {x+19} {y+7} Z','white')
            p.path(f'M {x} {y-14} L {x+3} {y-22}')
    else:return False
    return True


def animal(p:Pen,kind:str,v:int):
    if kind in ('snail','slug'):
        p.path('M 13 103 Q 26 96 48 99 L 77 96 C 75 79 86 77 86 96 L 88 106 Q 48 117 13 111 Z','white')
        if kind=='snail':
            p.ellipse(45,84,24,24);p.spiral(44,84,18,2.3)
        p.path('M 78 86 L 73 76 M 85 86 L 88 75')
        p.dot(72,75,1.6);p.dot(89,74,1.6);p.dot(84,98,.9)
    elif kind in ('bird','heron','duck'):
        p.path('M 44 42 C 30 44 19 65 21 75 C 33 98 70 96 78 69 L 48 67 Q 54 57 50 47 Z','white')
        p.ellipse(43,35,12,12)
        p.path('M 32 35 L 13 42 L 32 40 M 50 72 Q 30 80 30 62')
        p.dot(42,32,1)
        p.path('M 43 91 L 43 109 L 33 111 M 55 89 L 56 109 L 64 110')
        if kind=='heron':
            p.path('M 78 69 Q 77 43 64 49 L 54 65 M 43 91 L 33 99 L 43 107')
        if kind=='duck':p.path('M 64 88 Q 72 99 82 88')
    elif kind=='sheep':
        points=[]
        for i in range(64):
            t=TAU*i/64;r=1+.12*math.sin((8+v%3)*t)
            points.append((43+28*r*math.cos(t),64+20*r*math.sin(t)))
        p.curve(points,True,'white')
        p.path('M 27 82 L 25 104 M 37 84 L 38 107 M 56 83 L 58 103 M 66 78 L 70 98')
        p.ellipse(76,58,11,14);p.dot(81,55,1.3)
        p.path('M 73 44 Q 72 31 81 36 M 16 56 Q 7 48 13 43')
    elif kind=='cow':
        p.path('M 20 46 Q 15 58 20 85 L 20 107 L 30 107 L 34 87 L 59 89 L 65 107 L 73 107 L 74 69 L 87 60 L 83 42 L 65 50 Z','white')
        p.path('M 79 43 L 84 29 L 87 40 M 66 49 L 63 36 M 18 55 Q 7 66 10 85 M 72 54 L 85 54')
        p.dot(78,48,1.4)
        p.path('M 27 49 C 16 52 19 70 30 65 C 47 70 41 51 27 49 Z','black')
        p.path('M 53 53 C 46 63 45 70 53 77 L 65 80 L 67 62 Z','black')
    elif kind=='butterfly':
        p.path('M 48 53 C 36 27 6 24 14 62 C 16 79 30 91 45 87 M 54 53 C 63 27 93 24 87 63 C 82 88 68 96 55 88','white')
        p.path('M 47 49 Q 51 44 56 49 L 55 97 Q 50 112 47 98 Z','white')
        p.path('M 48 49 L 37 35 M 53 48 L 65 35 M 46 64 Q 30 41 24 47 Q 20 68 42 81 M 57 63 Q 74 44 77 51 Q 79 72 59 81')
    elif kind in ('ladybug','bee'):
        p.ellipse(51,72,23,30,angle=-20 if v%2 else 15)
        if kind=='ladybug':
            p.path('M 35 49 Q 50 43 70 51 M 51 48 Q 49 71 54 101')
            for x,y in [(37,66),(64,67),(42,86),(65,86)]:p.dot(x,y,3)
            for x,y in [(28,61),(27,78),(31,91),(74,63),(74,82),(70,99)]:p.path(f'M {x} {y} L {x+( -7 if x<50 else 7)} {y+1}')
        else:
            p.path('M 31 59 L 69 64 M 29 70 L 72 75 M 30 81 L 67 85 M 38 91 L 61 95')
            p.ellipse(30,52,10,17,angle=-40);p.ellipse(69,49,10,18,angle=35)
        p.path('M 45 43 L 37 31 M 57 43 L 65 32')
    elif kind=='snake':
        p.path('M 21 104 C 78 124 85 83 42 78 C 21 76 47 62 64 54 C 79 40 49 20 40 30 C 36 45 52 44 50 53 C 37 63 8 60 12 87 C 19 105 43 93 46 100 C 43 107 26 97 21 104 Z','white')
        p.dot(45,35,1.1);p.path('M 39 32 L 26 25 L 26 19 M 26 25 L 20 26')
    elif kind in ('caterpillar','worm'):
        for i in range(5):p.ellipse(22+i*14,74+math.sin(i*1.4)*6,10,13)
        p.ellipse(80,69,12,14);p.face(80,67,6)
        for x in [20,33,47,61,75]:p.path(f'M {x} 87 L {x-2} 98')
        p.path('M 78 56 L 73 44 M 84 56 L 89 45')
    elif kind=='tortoise':
        p.path('M 16 83 C 13 31 73 24 76 83 Z','white')
        p.path('M 19 75 L 75 75 M 20 62 L 72 63 M 29 48 L 34 63 L 30 75 M 49 43 L 47 62 L 57 75 M 68 48 L 62 62')
        p.ellipse(82,77,10,8);p.dot(87,74,1)
        p.path('M 28 83 L 22 97 L 34 97 L 39 84 M 60 83 L 57 97 L 68 97 L 71 84')
    elif kind=='hedgehog':
        points=[(10,84),(15,67),(10,63),(21,59),(18,48),(32,50),(32,40),(45,46),(52,36),(59,44),(70,41),(73,55),(84,62),(79,73),(94,85),(89,95),(11,97)]
        p.curve(points,True,'white');p.dot(82,84,1.6)
        for x,y in [(25,70),(37,58),(50,68),(65,58),(51,87)]:p.path(f'M {x} {y} L {x+4} {y+6}',weight=2)
        p.path('M 18 99 L 17 110 M 70 97 L 73 109')
    elif kind=='fish':
        p.path('M 21 70 C 39 34 68 37 78 65 L 95 51 L 92 82 L 78 74 C 64 105 34 103 21 70 Z','white')
        p.path('M 42 44 Q 54 71 45 95 M 39 45 L 48 30 L 66 41 M 51 96 L 59 107 L 72 88')
        p.dot(31,66,1.5)
        for x,y in [(54,61),(66,69),(56,81)]:p.path(f'M {x-3} {y-2} Q {x} {y+4} {x+3} {y-2}',weight=1.6)
    elif kind=='frog':
        p.ellipse(50,72,25,25);p.ellipse(33,50,9,10);p.ellipse(65,49,9,10)
        p.dot(33,50,2);p.dot(65,49,2);p.path('M 33 73 Q 50 87 70 71')
        p.path('M 28 80 Q 11 81 17 105 L 35 105 M 75 80 Q 90 88 84 108 L 65 107 M 35 105 L 29 116 M 72 107 L 80 116')
    elif kind=='owl':
        p.path('M 23 41 L 25 17 L 42 31 Q 52 26 65 32 L 80 18 L 79 52 C 94 117 12 117 23 41 Z','white')
        p.ellipse(39,52,12,13);p.ellipse(65,51,12,13);p.dot(40,51,2);p.dot(65,51,2)
        p.path('M 48 59 L 52 67 L 57 59 M 25 76 L 42 94 M 77 75 L 64 94 M 42 109 L 38 117 M 59 109 L 65 117')
    elif kind=='mouse':
        p.ellipse(48,77,27,23);p.ellipse(68,57,12);p.ellipse(28,59,11)
        p.dot(65,75,1.4);p.path('M 76 81 L 92 82 M 75 87 L 92 94 M 19 86 C 5 83 6 109 23 108')
    else:return False
    return True


# Individual objects keep their own silhouette rather than reusing a generic
# flower with a new name. White fills are cut out of the exported black mask.
OBJECT_PATHS = {
 'house': [('M 19 56 L 50 22 L 83 55 L 79 109 L 24 109 Z','white'),('M 16 55 L 50 17 L 88 55 M 40 109 L 40 79 Q 51 67 63 79 L 63 109 M 29 62 L 69 62','none')],
 'well': [('M 22 53 L 25 110 Q 50 118 78 110 L 78 53 Z','white'),('M 21 55 Q 50 43 80 54 Q 52 68 21 55 Z','white'),('M 28 55 L 29 23 L 69 23 L 72 54 M 28 36 L 72 36 M 53 36 L 53 64 M 25 74 L 77 73 M 26 91 L 76 91 M 40 67 L 40 74 M 57 74 L 57 91 M 44 91 L 44 113','none')],
 'signpost': [('M 44 111 L 47 35 L 55 35 L 54 113','none'),('M 16 42 L 62 38 L 76 48 L 62 58 L 16 57 Z','white'),('M 31 67 L 79 65 L 79 84 L 31 83 L 20 75 Z','white')],
 'wateringcan': [('M 24 61 L 64 60 L 66 107 Q 44 116 23 104 Z','white'),('M 25 65 C 1 50 4 97 23 95 M 64 87 L 78 53 L 85 44 L 91 49 L 84 61 L 77 107 L 66 107 M 38 60 L 38 44 L 54 44 L 54 61 M 37 68 L 38 103 M 49 68 L 49 107 M 57 68 L 59 103','none')],
 'spade': [('M 47 113 L 48 42 L 55 42 L 57 113','none'),('M 37 15 L 64 15 L 62 36 Q 52 48 39 36 Z','white'),('M 34 89 L 71 89 L 73 109 L 51 117 L 32 108 Z','white')],
 'rake': [('M 49 12 L 56 13 L 55 96 L 48 95 Z','white'),('M 22 97 L 81 99 M 23 98 L 22 114 M 33 98 L 33 114 M 44 99 L 44 116 M 55 99 L 55 116 M 66 99 L 66 116 M 78 99 L 78 115','none')],
 'sailboat': [('M 16 88 L 85 88 L 72 109 Q 39 119 23 102 Z','white'),('M 53 16 L 52 87 L 21 80 Z','white'),('M 57 27 L 81 81 L 57 80 Z','white'),('M 14 114 Q 28 107 40 114 Q 55 120 68 112 Q 80 107 89 113','none')],
 'camp': [('M 18 100 L 45 41 L 78 99 Z','white'),('M 46 43 L 85 62 L 97 100 L 78 99 M 37 100 L 46 61 L 62 100 M 45 42 L 38 29 M 46 42 L 53 29 M 15 103 L 9 112 M 83 103 L 92 113','none')],
 'gate': [('M 17 110 L 20 30 L 26 29 L 27 109 M 69 110 L 73 27 L 79 28 L 80 110 M 24 47 L 74 45 M 24 78 L 73 76 M 39 49 L 38 77 M 56 46 L 55 76','none')],
 'log': [('M 16 53 L 68 45 L 86 56 L 85 102 L 34 113 L 16 100 Z','white'),('M 17 53 Q 39 47 35 74 L 35 112 M 41 69 L 76 63 M 44 84 L 72 81 M 45 103 L 77 96 M 25 67 L 25 97','none')],
 'stump': [('M 21 58 L 31 47 L 71 47 L 79 57 L 76 99 L 88 110 L 59 111 L 49 102 L 41 112 L 12 110 L 23 99 Z','white'),('M 24 57 Q 49 40 75 56 Q 57 79 24 57 Z','white'),('M 30 76 L 33 98 M 61 77 L 64 101 M 46 73 L 43 92','none')],
 'witch': [('M 20 52 L 43 15 L 69 51 Z','white'),('M 13 53 L 82 53 L 75 60 L 22 62 Z','white'),('M 27 69 Q 52 53 69 70 L 64 87 L 76 104 L 19 104 L 30 86 Z','white'),('M 34 104 L 29 116 M 58 104 L 63 116 M 31 80 L 14 88 M 62 79 L 79 87','none')],
 'snowman': [('M 33 45 L 35 25 L 60 25 L 63 44 M 26 46 L 73 45','none'),('M 34 57 C 20 73 19 88 22 99 C 29 119 73 119 78 99 C 81 86 72 73 63 57 Z','white'),('M 27 59 C 27 31 72 30 73 56 Q 51 76 27 59 Z','white'),('M 26 82 L 12 72 L 12 63 M 76 80 L 90 69 L 91 61 M 48 46 L 59 53 L 47 54','none')],
 'moon': [('M 67 23 C 11 6 8 107 66 109 C 44 91 40 59 67 23 Z','white'),('M 72 49 L 75 41 L 79 47 L 88 47 L 82 53 L 84 61 L 76 57 L 69 61 L 72 53 Z','white')],
 'star': [('M 50 14 L 58 40 L 79 24 L 72 51 L 94 56 L 72 67 L 82 95 L 59 80 L 50 111 L 40 83 L 15 99 L 27 73 L 6 62 L 29 54 L 18 29 L 41 42 Z','white'),('M 50 27 L 50 97 M 26 53 L 72 77 M 26 78 L 70 52','none')],
 'sun': [('M 19 48 L 12 38 M 38 25 L 34 15 M 61 25 L 64 13 M 79 44 L 89 35 M 82 76 L 92 80 M 64 96 L 69 110 M 37 98 L 33 111 M 21 79 L 8 85','none')],
 'stones': [('M 11 105 C 12 95 33 94 50 97 C 68 93 88 94 88 105 Q 50 117 11 105 Z','white'),('M 21 89 C 19 72 75 69 78 84 Q 69 96 21 89 Z','white'),('M 33 66 C 31 52 67 52 72 62 Q 53 76 33 66 Z','white'),('M 41 43 C 32 22 67 20 62 39 Q 55 48 41 43 Z','white')],
 'waterlily': [('M 15 104 Q 10 83 48 83 L 61 100 L 66 82 Q 99 93 84 110 Q 52 122 15 104 Z','white'),('M 52 88 Q 21 60 20 43 Q 48 50 52 74 Q 50 37 56 20 Q 79 49 58 77 Q 74 44 89 48 Q 84 79 52 88 Z','white')],
 'spiderweb': [('M 51 16 L 88 37 L 92 76 L 61 110 L 20 95 L 8 54 L 30 25 Z','none'),('M 30 25 L 61 110 M 8 54 L 92 76 M 20 95 L 88 37 M 51 16 L 45 67 L 61 110 M 30 47 L 61 39 L 76 62 L 62 91 L 33 82 L 22 58 Z M 45 53 L 58 57 L 59 75 L 43 80 L 32 67 Z','none')],
 'honeycomb': [('M 32 27 L 49 17 L 66 27 L 65 47 L 49 57 L 33 46 Z','none'),('M 33 46 L 17 56 L 18 76 L 34 86 L 50 76 L 49 57 M 66 47 L 81 56 L 81 77 L 64 86 L 50 76 M 34 87 L 35 107 L 52 117 L 68 106 L 65 86','none')],
}


def objects(p:Pen,kind:str,v:int):
    if kind not in OBJECT_PATHS:return False
    for d,fill in OBJECT_PATHS[kind]:p.path(d,fill)
    if kind=='sun':p.ellipse(50,62,25,27);p.face(50,60,11)
    if kind=='snowman':
        p.dot(39,48,1);p.dot(59,48,1)
        for y in (82,93,103):p.dot(51,y,1.3)
    if kind=='witch':p.face(48,74,8)
    if kind=='moon':p.dot(25,51,1);p.path('M 24 66 Q 29 71 34 66',weight=1.8)
    # Some recurring objects really do occur in several drawings in the reference.
    # Their secondary strokes are independently authored, not identical copies.
    if v%2 and kind in ('house','well','camp','gate'):
        for x,y in [(15,114),(84,112)]:p.path(f'M {x} {y} L {x-4} {y-8} M {x} {y} L {x+5} {y-7}',weight=2)
    return True


ROWS = [
 'berries bell sunflower daisy tulip clover bell acorn sheep caterpillar star strawberry clover droop',
 'fern daisy tulip grapes twig berries bird grass lily vine daisy mushroom sprout rose',
 'pine slug heron vine daisy tulip succulent spiralflower daisy grass clover fern fern seaweed',
 'daisy seaweed shrub vine clover daisy bush bamboo grass twig daisy pine twig apple',
 'snake clover spiralflower twig bell grass snail berries snowman sunflower fern clover clover twig',
 'clover seaweed fern seaweed bush palm signpost berries sprout seaweed twig daisy tree stump',
 'spiralflower vine apple well cactus grass seaweed bush mushroom bush house clover fern daisy',
 'pepper sprout witch mushroom bush clover vine berries mushroom seaweed twig raspberry moon clover',
 'tree grass apple bush apple succulent vine daisy spiralflower daisy rose vine rose bee',
 'clover berries bamboo fern sunflower worm heron spiderweb seaweed clover spade bush spade log',
 'mushroom strawberry twig grapes tulip succulent sun berries daisy owl clover seaweed mushroom rainbow',
 'fish berries clover fig mushroom pumpkin clover fern clover clover fish spiralflower mushroom daisy',
 'succulent banana sprout cow succulent hedgehog clover bush grass vine grass rose tulip clover',
 'succulent spiralflower apple cactus spiralflower clover spiralflower sprout daisy tree onion mushroom daisy ladybug',
 'clover honeycomb clover mushroom clover grass sprout bird berries bush fig fish sunflower seaweed',
 'log bush tortoise fern tulip cactus fern camp clover bush spiralflower sprout mushroom grass',
 'snail tulip clover tulip clover bush bush carrot tulip clover tulip camp rake grass',
 'clover mushroom clover sunflower sailboat daisy butterfly vine clover berries clover waterlily clover apple',
 'bell cherry bamboo grass daisy succulent mushroom bamboo daisy tree tree apple bush daisy',
 'berries daisy fig succulent bush grass vine bamboo frog rose sprout rose clover lily',
 'wateringcan bell clover berries seaweed grass stones fish star worm twig fern clover clover',
 'succulent daisy daisy berries berries daisy bell rose sunflower grass clover clover rose stump',
 'daisy berries daisy raspberry berries vine clover berries bamboo grass clover succulent sprout twig',
 'tree butterfly sprout daisy succulent daisy daisy bush bell sprout mushroom rosemary clover berries',
 'bush mouse clover twig daisy clover clover droop mushroom bush clover daisy clover raspberry',
 'succulent snail clover tulip pumpkin bush seaweed bird clover fig bell vine clover hedgehog',
]


def special(p:Pen,kind:str,v:int):
    if kind=='rainbow':
        for i in range(4):
            p.path(f'M {16+i*7} 102 C {9+i*10} {20+i*12} {91-i*10} {20+i*12} {86-i*7} 102')
    elif kind=='fig':
        p.path('M 52 31 C 26 38 12 69 22 90 C 35 117 60 112 74 92 C 92 59 74 32 52 31 Z','white')
        p.path('M 52 37 Q 40 68 56 106')
        for x,y in [(42,52),(32,70),(38,89),(65,51),(67,70),(66,85)]:p.dot(x,y,1)
    elif kind=='rosemary':
        p.stem(top=17,leaves=0)
        for i in range(10):
            y=108-i*9;x=49+math.sin(i)*2
            p.path(f'M {x} {y} Q {x-10} {y-2} {x-13} {y-9} M {x} {y-2} Q {x+13} {y-5} {x+15} {y-13}')
    else:return False
    return True


def draw_asset(kind:str,number:int):
    pen=Pen(number)
    if not (foliage(pen,kind,number) or fruit(pen,kind,number) or animal(pen,kind,number)
            or objects(pen,kind,number) or special(pen,kind,number)):
        if kind=='mushroom':mushroom(pen,number)
        else:raise ValueError(f'Unimplemented subject {kind}')
    return pen


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
        pen=draw_asset(kind,index)
        mask=pen.output(DEST/'svg'/stem)
        # Pen writes siblings; move the raster into the matching raster directory.
        (DEST/'svg'/f'{stem}.png').replace(DEST/'png'/f'{stem}.png')
        svg_path=DEST/'svg'/f'{stem}.svg'
        png_path=DEST/'png'/f'{stem}.png'
        digest=hashlib.sha256(svg_path.read_bytes()).hexdigest()
        assert digest not in shapes
        shapes.add(digest)
        box=mask.getbbox()
        assert box and 1<=box[0]<box[2]<200 and 1<=box[1]<box[3]<240,stem
        records.append({'id':stem,'subject':kind,'reference_slot':index,
                        'svg':f'svg/{stem}.svg','png':f'png/{stem}.png',
                        'sha256':digest,'png_sha256':hashlib.sha256(png_path.read_bytes()).hexdigest(),
                        'ink_bbox':box})
    # A separate blossom prevents repeating an existing day on leap years.
    pen=Pen(366);pen.stem(top=43,leaves=3);pen.flower(49,39,18,8,smile=True)
    pen.flower(27,68,8,5);pen.flower(73,82,7,5)
    pen.output(DEST/'svg/leap-day')
    (DEST/'svg/leap-day.png').replace(DEST/'png/leap-day.png')
    manifest={'version':3,'count':365,'format':'individually authored SVG paths and matching transparent black masks',
              'provenance':'Reconstructed vector illustrations informed by the user-provided One Year garden screenshots; not the original application asset files.',
              'reference':'user-full-garden-2026.jpg','subjects':sorted(set(kinds)),
              'assets':records,'leap_day':{'svg':'svg/leap-day.svg','png':'png/leap-day.png'}}
    (DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    output=ROOT/'previews/generated/annual-garden'
    output.mkdir(parents=True,exist_ok=True)
    atlas=Image.new('L',(1800,2520),255);draw=ImageDraw.Draw(atlas)
    face=ImageFont.truetype(str(DEST/'fonts/ShantellSans.ttf'),14)
    face.set_variation_by_axes([500,40,20,0])
    for i,record in enumerate(records):
        x=(i%20)*90;y=(i//20)*132
        with Image.open(DEST/record['png']) as asset:
            asset=asset.resize((80,96),Image.Resampling.LANCZOS)
            atlas.paste(0,(x+5,y+6,x+85,y+102),asset.getchannel('A'))
        draw.text((x+45,y+108),f'{i+1:03d}',font=face,fill=0,anchor='mt')
    atlas.save(output/'365-assets.png',optimize=True)
    print(json.dumps({'assets':len(records),'unique_svg_hashes':len(shapes),'subject_families':len(set(kinds)),
                      'leap_day_bonus':1,'atlas':str(output/'365-assets.png')},ensure_ascii=False))


if __name__=='__main__':build()
