"""The annual garden's pen: every drawing is authored here as vector strokes.

The source is vector geometry, not cropped screenshots. The screenshot references
inform the subjects and drawing vocabulary; these are reconstructed illustrations.
The asset builder freezes numbered drawings into the committed library; the same
code can draw further hands of each subject.
"""
from __future__ import annotations

import math
import random
import re

from PIL import Image, ImageDraw, ImageOps

TAU = math.tau

def map_path(d: str, T) -> str:
    """Apply a point map to every coordinate pair of an absolute path."""
    tokens = re.findall(r'[MLCQZ]|-?\d+(?:\.\d+)?', d)
    out, pair = [], []
    for token in tokens:
        if token.isalpha():
            out.append(token)
            continue
        pair.append(float(token))
        if len(pair) == 2:
            out.append('%.2f %.2f' % T(*pair))
            pair = []
    return ' '.join(out)


class Pen:
    """Small absolute SVG path authoring surface, with matching Pillow output."""
    # Optional point map (move, turn, mirror) for later paths; stroke width stays.
    T = None
    # Optional outer map for a whole new hand of a subject, applied after T,
    # and the matching stroke scale so a smaller hand is not a bolder one.
    frame = None
    stroke_scale = 1.0
    def __init__(self, number: int, fast: bool = False):
        # The frozen library keeps Pillow's exact curved joints; new hands round
        # only the visible corners, which looks the same and draws far faster.
        self.fast = fast
        self.rng = random.Random(48371 + number * 7919)
        self.stroke_rng = random.Random(7351 + number * 3571)
        self.svg: list[str] = []
        self.image = Image.new('L', (400, 480), 255)
        self.draw = ImageDraw.Draw(self.image)
        self.weight = 3.7

    def path(self, d: str, fill: str = 'none', weight: float | None = None):
        if self.T:
            d = map_path(d, self.T)
        if self.frame:
            d = map_path(d, self.frame)
        tokens = re.findall(r'[MLCQZ]|-?\d+(?:\.\d+)?', d)
        command, index, current, first = '', 0, (0., 0.), (0., 0.)
        points, subpaths, normalized = [], [], []
        # Vary pressure separately from geometry so the same subject keeps its
        # shape while fine details and the outer pen strokes gain clear weight.
        width = (weight * 1.34 if weight is not None else self.weight) * self.stroke_rng.uniform(.90,1.10) * self.stroke_scale
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
            radius=width*2
            if self.fast:
                self.draw.line(scaled,fill=0,width=round(width*4))
                # Round a corner once its outer notch would reach a pixel. Pillow's
                # ellipse covers its whole box, a pixel wider than the line.
                limit=.6/radius;r=radius-.5
                angles=[math.atan2(b[1]-a[1],b[0]-a[0]) for a,b in zip(scaled,scaled[1:])]
                for b,before,after in zip(scaled[1:],angles,angles[1:]):
                    if abs((after-before+math.pi)%TAU-math.pi)>limit:
                        self.draw.ellipse((b[0]-r,b[1]-r,b[0]+r,b[1]+r),fill=0)
            else:
                self.draw.line(scaled,fill=0,width=round(width*4),joint='curve')
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

    def mask(self) -> Image.Image:
        """The drawing as a 200x240 alpha mask: ink is opaque, paper clear."""
        return ImageOps.invert(self.image.resize((200,240),Image.Resampling.LANCZOS))


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


# Additions: original drawings authored for KindleGlance with the same pen. They
# are not derived from the reference screenshots. Each takes a variant (0 or 1).
def transform(scale=1, deg=0, dx=0, dy=0, cx=50, cy=60, mirror=False):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    def T(x, y):
        x, y = x-cx, y-cy
        if mirror: x = -x
        return cx+dx+scale*(x*c-y*s), cy+dy+scale*(x*s+y*c)
    return T


def P(points, close=True):
    return 'M '+' L '.join(f'{x:.2f} {y:.2f}' for x, y in points)+(' Z' if close else '')


def oval(p, x, y, rx, ry, angle=0, weight=None, fill='white'):
    a = math.radians(angle); pts = []
    for i in range(16):
        t = TAU*i/16; px, py = rx*math.cos(t), ry*math.sin(t)
        pts.append((x+px*math.cos(a)-py*math.sin(a), y+px*math.sin(a)+py*math.cos(a)))
    p.curve(pts, True, fill, weight)


def heart(p, cx, cy, s, point_dir):
    """Heart whose tip points along point_dir (degrees, screen coordinates)."""
    rot = math.radians(point_dir-90); pts = []
    for i in range(24):
        t = TAU*i/24
        x = 16*math.sin(t)**3; y = -(13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t))
        x, y = x*s/16, (y+2)*s/16
        pts.append((cx+x*math.cos(rot)-y*math.sin(rot), cy+x*math.sin(rot)+y*math.cos(rot)))
    p.curve(pts, True, 'white')


def at(cx, cy, r, deg):
    a = math.radians(deg)
    return cx+math.cos(a)*r, cy+math.sin(a)*r



def dandelion(p, v):
    p.path('M 48 112 L 33 107 L 36 103 L 24 100 L 28 96 L 17 91 Q 36 92 48 106', 'white')
    p.path('M 53 112 L 67 106 L 64 102 L 76 98 L 72 94 L 83 89 Q 64 91 53 106', 'white')
    p.path('M 50 112 C 53 92 46 70 52 52')
    cx, cy, r = 52, 36, 18
    for i in range(18):
        a = TAU*i/18+.1
        if v and math.cos(a) > .3:
            continue
        x2, y2 = cx+math.cos(a)*r, cy+math.sin(a)*r
        p.path(f'M {cx+math.cos(a)*5:.2f} {cy+math.sin(a)*5:.2f} L {x2:.2f} {y2:.2f}', weight=1.2)
        p.dot(x2, y2, 1.3)
    p.ellipse(cx, cy, 4.5)
    if v:
        for x, y in [(76, 26), (87, 12), (91, 38)]:
            p.path(f'M {x} {y} L {x-2} {y+9}', weight=1.1)
            for dx in (-4, 0, 4):
                p.path(f'M {x} {y} L {x+dx} {y-4}', weight=1.1)
            p.dot(x-2, y+9, 1.1)


def fuzzy_head(p, tx, ty, side, length=32):
    """A bristly spike hanging from the arched stem tip."""
    T, C, E = (tx, ty), (tx+side*length*.4, ty+2), (tx+side*length*.5, ty+length*.9)
    centre, normal, width = [], [], []
    for i in range(13):
        t = i/12; u = 1-t
        q = (u*u*T[0]+2*u*t*C[0]+t*t*E[0], u*u*T[1]+2*u*t*C[1]+t*t*E[1])
        dx, dy = 2*u*(C[0]-T[0])+2*t*(E[0]-C[0]), 2*u*(C[1]-T[1])+2*t*(E[1]-C[1])
        L = math.hypot(dx, dy)
        centre.append(q); normal.append((-dy/L, dx/L)); width.append(1.5+3.6*math.sin(math.pi*min(1, .2+t)))
    left = [(q[0]+n[0]*w, q[1]+n[1]*w) for q, n, w in zip(centre, normal, width)]
    right = [(q[0]-n[0]*w, q[1]-n[1]*w) for q, n, w in zip(centre, normal, width)]
    p.curve(left+right[::-1], True, 'white')
    for q, n, w in list(zip(centre, normal, width))[2:-1]:
        for k in (1, -1):
            p.path(f'M {q[0]+n[0]*k*w:.2f} {q[1]+n[1]*k*w:.2f} L {q[0]+n[0]*k*(w+3):.2f} {q[1]+n[1]*k*(w+3):.2f}', weight=1.05)


def foxtail(p, v):
    stems = [(44, 32, 32, -1), (50, 60, 20, 1), (56, 72, 42, 1)] if v == 0 else [(46, 34, 26, -1), (54, 66, 34, 1)]
    p.leaf(49, 108, -26, -22, 3.5); p.leaf(53, 106, 24, -26, 3.5)
    for bx, tx, ty, side in stems:
        p.path(f'M {bx} 112 C {bx} 70 {tx-side*10} {ty-18} {tx} {ty}')
        fuzzy_head(p, tx, ty, side)


def shamrock(p, v):
    if v == 0:
        p.path('M 50 113 C 55 96 44 78 50 58')
        for d in (-150, -90, -30):
            x, y = at(50, 58, 12, d); heart(p, x, y, 11, d+180)
        p.path('M 40 113 C 38 100 34 92 30 84')
        for d in (-150, -90, -30):
            x, y = at(30, 84, 8, d); heart(p, x, y, 7.5, d+180)
    else:
        p.path('M 52 113 C 60 98 44 82 50 58')
        for d in (-135, -45, 45, 135):
            x, y = at(50, 54, 12, d); heart(p, x, y, 11.5, d+180)
        p.dot(50, 54, 1.4)


# --------------------------------------------------------------------- flowers

def lavender(p, v):
    stems = [(36, 30, -1), (50, 16, 0), (64, 26, 1)] if v == 0 else [(32, 34, -1), (44, 20, -1), (56, 12, 1), (68, 28, 1)]
    for x, top, side in stems:
        p.path(f'M {50+side*2} 112 Q {x-side*3:.1f} {(top+112)/2+12:.1f} {x} {top+28}')
        for k in range(5):
            y = top+26-k*5.6; r = 2.7-k*.22
            oval(p, x-2.4, y, r, 3.6-k*.3, -28, weight=1.3)
            oval(p, x+2.4, y-1, r, 3.6-k*.3, 28, weight=1.3)
        p.dot(x, top-2, 1.3)
    p.leaf(50, 104, -22, -12, 3); p.leaf(51, 100, 22, -16, 3)


def trumpet(p, cx, cy, ax, ay, rx=17, tube=20, depth=7):
    L = math.hypot(ax, ay); ux, uy = ax/L, ay/L; nx, ny = -uy, ux
    tip = (cx+ux*tube, cy+uy*tube)
    for k in (1, -1):
        sx, sy = cx+nx*k*(rx-2), cy+ny*k*(rx-2)
        p.path(f'M {sx:.2f} {sy:.2f} Q {cx+ux*8+nx*k*3:.2f} {cy+uy*8+ny*k*3:.2f} {tip[0]+nx*k*1.5:.2f} {tip[1]+ny*k*1.5:.2f}')
    pts = [(cx+nx*rx*math.cos(t)+ux*depth*math.sin(t), cy+ny*rx*math.cos(t)+uy*depth*math.sin(t))
           for t in [TAU*i/18 for i in range(18)]]
    p.curve(pts, True, 'white')
    for i in range(5):
        t = TAU*i/5+.3
        p.path(f'M {cx:.2f} {cy:.2f} L {cx+nx*rx*.8*math.cos(t)+ux*depth*.8*math.sin(t):.2f} {cy+ny*rx*.8*math.cos(t)+uy*depth*.8*math.sin(t):.2f}', weight=1.1)
    p.dot(cx, cy, 1.2)


def morning_glory(p, v):
    if v == 0:
        p.path('M 48 113 C 30 96 66 84 50 68 C 40 58 52 54 50 50')
        heart(p, 30, 88, 11, 160); heart(p, 70, 78, 10, 20)
        trumpet(p, 60, 30, -.45, .89, 21, 22, 9)
    else:
        p.path('M 50 113 C 70 96 32 82 50 64 C 56 58 60 58 62 59 M 50 64 C 44 56 40 50 38 46')
        heart(p, 32, 94, 10, 160); heart(p, 72, 90, 10, 20)
        trumpet(p, 28, 30, .5, .87, 17, 19, 7.5)
        trumpet(p, 78, 50, -.87, .5, 16, 18, 7)


def floret(p, x, y, r=6.4):
    for k in range(4):
        a = 45+k*90; fx, fy = at(x, y, r*.52, a)
        oval(p, fx, fy, r*.5, r*.36, a, weight=1.35)
    p.dot(x, y, .9)


def hydrangea(p, v):
    if v == 0:
        p.path('M 50 113 L 50 62')
        p.leaf(49, 96, -30, -14, 10, True); p.leaf(51, 88, 30, -16, 10, True)
        for k in range(6):
            floret(p, *at(50, 40, 14, -90+k*60))
        floret(p, 50, 40)
    else:
        p.path('M 46 113 Q 44 82 38 64 M 48 104 Q 62 92 72 78')
        p.leaf(47, 98, -28, -10, 9, True)
        for k in range(6):
            floret(p, *at(38, 40, 13, -90+k*60), 6)
        floret(p, 38, 40, 6)
        for k in range(4):
            floret(p, *at(73, 70, 9, k*90), 5.4)


def lotus_leaf(p, cx, cy, rx=21, ry=8):
    p.path(f'M {cx} {cy+2} Q {cx-2} {(cy+113)/2:.1f} {cx+1} 113')
    pts = [(cx+rx*math.cos(t), cy+ry*math.sin(t)) for t in [TAU*i/20 for i in range(20)]]
    p.curve(pts, True, 'white')
    for d in (200, 250, 290, 340, 20):
        x, y = cx+math.cos(math.radians(d))*rx*.82, cy+math.sin(math.radians(d))*ry*.82
        p.path(f'M {cx} {cy} L {x:.2f} {y:.2f}', weight=1.1)


def lotus(p, v):
    if v == 0:
        lotus_leaf(p, 68, 82)
        p.path('M 40 49 Q 37 84 41 113')
        p.path('M 22 32 Q 28 44 38 49 L 43 49 Q 53 44 59 32 Z', 'white')
        oval(p, 40.5, 32, 18.5, 6.5)
        for x, y in [(31, 32), (38, 29), (46, 29), (50, 33), (41, 35), (35, 35), (43, 32)]:
            oval(p, x, y, 1.9, 1.3, weight=1.1)
    else:
        lotus_leaf(p, 30, 88, 20, 7.5)
        p.path('M 58 60 Q 62 88 60 113')
        for dx, dy, w in [(-20, -22, 8), (20, -24, 8), (-14, -30, 8), (13, -32, 8), (0, -40, 9)]:
            p.leaf(58, 60, dx, dy, w)
        p.path('M 58 60 L 58 34', weight=1.1)


# ------------------------------------------------------------ vegetables, fruit

def calyx(p, cx, cy, r=12, points=5):
    pts = []
    for i in range(points*2):
        a = math.radians(-90+180*i/points); rr = r if i % 2 == 0 else r*.32
        pts.append((cx+math.cos(a)*rr, cy+math.sin(a)*rr*.62))
    p.path(P(pts), 'white')


def tomato(p, v):
    if v == 0:
        pts = [(50+31*(1+.04*math.cos(5*t))*math.cos(t), 76+26*(1+.04*math.cos(5*t))*math.sin(t)) for t in [TAU*i/40 for i in range(40)]]
        p.curve(pts, True, 'white')
        calyx(p, 50, 52, 14)
        p.path('M 50 50 Q 50 40 56 36')
        p.path('M 30 66 Q 32 58 40 56', weight=1.4)
    else:
        p.path('M 12 20 Q 46 34 88 18')
        p.leaf(56, 26, 16, -14, 6, True)
        for cx, cy, r, sx in [(34, 70, 18, 32), (68, 82, 16, 64)]:
            p.path(f'M {sx} 27 Q {cx-3} {(cy-r+27)/2:.1f} {cx} {cy-r+2}')
            p.ellipse(cx, cy, r, r*.88)
            calyx(p, cx, cy-r*.82, 9)
            p.path(f'M {cx-r*.62:.2f} {cy-r*.2:.2f} Q {cx-r*.55:.2f} {cy-r*.55:.2f} {cx-r*.25:.2f} {cy-r*.62:.2f}', weight=1.3)


def peapod(p, v):
    if v == 0:
        p.path('M 18 86 C 30 104 74 90 84 54 C 70 68 34 80 18 86 Z', 'white')
        for x, y in [(31, 82), (44, 77), (57, 71), (69, 64)]:
            p.ellipse(x, y, 6.3)
        p.path('M 20 84 C 26 64 62 46 84 52')
        p.path('M 84 54 Q 92 46 86 36')
        p.spiral(83, 30, 6, 1.6)
        p.leaf(84, 54, -8, -12, 4)
    else:
        p.path('M 12 18 Q 50 8 90 22')
        p.leaf(74, 18, 12, -10, 6)
        p.spiral(28, 30, 7, 1.7)
        p.path('M 54 14 L 54 22')
        p.path('M 54 22 C 38 40 44 86 60 100 C 72 82 66 38 54 22 Z', 'white')
        p.path('M 54 30 Q 49 40 55 48 Q 49 58 56 66 Q 51 77 58 88', weight=1.4)
        p.leaf(54, 24, -10, 6, 4); p.leaf(54, 24, 10, 6, 4)


def persimmon_body(p, cx, cy, rx, ry, leaf=7):
    pts = [(cx+rx*(1+.06*math.cos(4*t))*math.cos(t), cy+ry*(1+.06*math.cos(4*t))*math.sin(t)) for t in [TAU*i/36 for i in range(36)]]
    p.curve(pts, True, 'white')
    top = cy-ry+3
    # Four broad sepals lie flat on the fruit: two to the sides, two in front.
    for dx, dy in [(-leaf*2.3, 2), (leaf*2.3, 1), (-leaf*1.1, leaf*.9), (leaf*1.2, leaf*.8)]:
        p.leaf(cx, top, dx, dy, leaf*.72)
    p.path(f'M {cx} {top} L {cx+1} {top-leaf}')
    p.path(f'M {cx-3} {top-leaf} L {cx+5} {top-leaf}', weight=1.6)


def persimmon(p, v):
    if v == 0:
        persimmon_body(p, 50, 82, 31, 24, 10)
        p.path('M 28 74 Q 30 66 37 64', weight=1.4)
    else:
        p.path('M 8 22 Q 40 16 60 26 L 92 18 M 60 26 L 68 10')
        p.leaf(40, 19, -4, -14, 6)
        p.path('M 34 22 L 34 46 M 72 23 L 72 58')
        persimmon_body(p, 34, 64, 19, 15, 5)
        persimmon_body(p, 72, 76, 17, 13, 5)


def gourd_shape(p, cx, top, s=1):
    rel = [(0, 0), (-11, 4), (-13, 16), (-7, 26), (-18, 36), (-22, 52), (-16, 70), (0, 76), (16, 70), (22, 52), (18, 36), (7, 26), (13, 16), (11, 4)]
    p.curve([(cx+x*s, top+y*s) for x, y in rel], True, 'white')
    p.path(f'M {cx-12*s:.2f} {top+46*s:.2f} Q {cx-14*s:.2f} {top+38*s:.2f} {cx-9*s:.2f} {top+33*s:.2f}', weight=1.3)


def gourd(p, v):
    if v == 0:
        p.path('M 50 32 Q 49 22 56 17')
        p.leaf(55, 18, 24, -4, 8, True)
        p.spiral(34, 18, 6, 1.6)
        gourd_shape(p, 50, 32)
        p.path('M 37 31 L 63 31', weight=1.6)
    else:
        p.path('M 8 16 Q 50 30 92 14')
        p.leaf(50, 23, -6, -14, 7, True)
        p.spiral(78, 28, 6, 1.6)
        p.path('M 30 21 L 31 30 M 66 22 L 65 44')
        gourd_shape(p, 31, 30, .78)
        gourd_shape(p, 65, 44, .7)


# ------------------------------------------------------------------- creatures

def dragonfly_body(p):
    for x, y, rx, ry, a in [(29, 27, 21, 5, 14), (71, 27, 21, 5, -14), (30, 41, 19, 5, -14), (70, 41, 19, 5, 14)]:
        oval(p, x, y, rx, ry, a)
    p.path('M 48 42 L 49 104 Q 50 111 52 104 L 53 42 Z', 'white')
    for y in range(52, 104, 9):
        p.path(f'M 48 {y} L 53 {y}', weight=1)
    oval(p, 50, 35, 5.5, 8)
    p.ellipse(50, 22, 6.5, 5.5)
    p.dot(46, 21, 1.6); p.dot(54, 21, 1.6)


def dragonfly(p, v):
    if v == 0:
        dragonfly_body(p)
    else:
        p.T = transform(.85, 35, 0, -2)
        dragonfly_body(p)
        p.T = None
        p.path('M 14 96 Q 22 90 30 94 M 8 82 Q 16 76 24 80', weight=1.3)


def rabbit(p, v):
    if v == 0:
        p.ellipse(18, 86, 6.5)
        oval(p, 60, 30, 4.8, 16, -18); oval(p, 70, 31, 4.8, 16, 6)
        p.curve([(20, 98), (22, 74), (40, 62), (60, 66), (66, 84), (64, 104), (40, 108)], True, 'white')
        p.ellipse(70, 56, 13.5, 12.5)
        p.path('M 69 23 L 70 40', weight=1.2)
        p.dot(74, 53, 1.5); p.dot(83, 58, 1.3)
        p.path('M 82 60 L 90 58 M 82 62 L 90 64', weight=1)
        p.path('M 58 104 Q 60 96 66 98')
    else:
        oval(p, 42, 26, 5, 16, -10); oval(p, 58, 26, 5, 16, 10)
        p.path('M 42 18 L 43 33 M 58 18 L 57 33', weight=1.2)
        p.curve([(50, 62), (30, 72), (28, 98), (40, 108), (60, 108), (72, 98), (70, 72)], True, 'white')
        p.ellipse(50, 52, 16, 14)
        p.dot(44, 50, 1.6); p.dot(56, 50, 1.6)
        p.path('M 48 56 L 50 58 L 52 56 M 50 58 L 50 61', weight=1.4)
        p.path('M 40 58 L 30 56 M 40 60 L 30 62 M 60 58 L 70 56 M 60 60 L 70 62', weight=1)
        oval(p, 40, 106, 7, 4); oval(p, 60, 106, 7, 4)


def squirrel(p, v):
    if v:
        p.T = transform(1, 0, 0, 0, mirror=True)
    p.curve([(56, 102), (74, 94), (86, 72), (88, 50), (82, 30), (70, 22), (58, 28), (64, 38), (72, 52), (70, 70), (60, 84), (48, 92)], True, 'white')
    for x, y in [(74, 40), (80, 56), (76, 74)]:
        p.path(f'M {x} {y} L {x-5} {y+3}', weight=1.2)
    oval(p, 44, 84, 15, 20, 10)
    p.path('M 36 47 L 39 35 L 45 46', 'white')
    p.ellipse(37, 57, 12, 11)
    p.dot(32, 55, 1.6); p.dot(26, 60, 1.3)
    if v == 0:
        p.ellipse(28, 76, 5, 5.5)
        p.path('M 22 73 Q 28 66 34 73 Z', 'white')
        p.path('M 34 74 Q 30 80 26 80 M 38 80 Q 34 84 30 82', weight=1.6)
    else:
        p.path('M 32 72 Q 26 78 30 84', weight=1.6)
        p.ellipse(18, 104, 5, 5.5); p.path('M 12 101 Q 18 94 24 101 Z', 'white')
    p.path('M 32 104 Q 42 108 54 104')
    p.T = None


def cat(p, v):
    if v == 0:
        p.path('M 38 34 L 37 16 L 48 28 Z', 'white'); p.path('M 52 28 L 63 16 L 62 34 Z', 'white')
        p.curve([(50, 48), (34, 58), (28, 82), (31, 102), (50, 108), (69, 102), (72, 82), (66, 58)], True, 'white')
        p.ellipse(50, 40, 15, 14)
        p.path('M 68 102 C 90 104 92 82 80 74 Q 76 72 78 66', weight=None)
    else:
        p.path('M 37 38 L 35 20 L 47 31 Z', 'white'); p.path('M 53 31 L 65 20 L 63 38 Z', 'white')
        p.path('M 66 102 C 88 100 88 114 60 112')
        p.curve([(50, 54), (34, 62), (29, 86), (33, 104), (50, 109), (67, 104), (71, 86), (66, 62)], True, 'white')
        p.ellipse(50, 44, 16, 14)
        p.path('M 41 43 Q 44 46 47 43 M 53 43 Q 56 46 59 43', weight=1.4)
        p.path('M 48 49 L 50 51 L 52 49', weight=1.4)
        p.path('M 38 48 L 27 46 M 38 51 L 27 53 M 62 48 L 73 46 M 62 51 L 73 53', weight=1)
        p.path('M 43 109 L 43 98 M 57 109 L 57 98', weight=1.4)


def ant_body(p, antennae=True):
    oval(p, 27, 80, 13, 10, -10)
    p.ellipse(52, 74, 9, 6)
    p.path('M 39 78 L 44 76', weight=2.4)
    p.ellipse(69, 66, 7.5)
    p.dot(72, 64, 1.4)
    if antennae:
        p.path('M 72 60 Q 78 46 87 48 M 68 59 Q 70 46 78 41', weight=1.5)
    p.path('M 48 78 L 40 90 L 33 100 M 52 79 L 52 92 L 47 102 M 56 78 L 64 90 L 71 100', weight=1.8)


def ant(p, v):
    if v == 0:
        ant_body(p)
    else:
        p.leaf(72, 60, -36, -40, 13, True)
        ant_body(p, False)
        p.path('M 74 62 Q 80 52 86 54', weight=1.5)


def mole(p, v):
    if v == 0:
        p.ellipse(50, 70, 14, 13)
        p.path('M 43 66 Q 45 68 47 66 M 53 66 Q 55 68 57 66', weight=1.4)
        oval(p, 50, 75, 4, 3)
        p.path('M 8 112 C 14 80 86 80 92 112 Z', 'white')
        for x in (38, 62):
            oval(p, x, 87, 6, 3.6)
            p.path(f'M {x-4} 89 L {x-5} 92 M {x} 90 L {x} 93 M {x+4} 89 L {x+5} 92', weight=1)
        for x, y in [(24, 102), (70, 98), (52, 104), (80, 106)]:
            p.dot(x, y, 1.4)
    else:
        p.ellipse(40, 72, 13, 12)
        p.dot(36, 69, 1.4); p.dot(45, 69, 1.4)
        p.path('M 37 76 Q 40 79 44 76', weight=1.2)
        oval(p, 40, 74, 3, 2.2)
        p.path('M 6 112 C 12 84 70 82 76 112 Z', 'white')
        oval(p, 28, 88, 5.5, 3.4); oval(p, 52, 88, 5.5, 3.4)
        p.path('M 64 112 C 70 98 92 96 96 112 Z', 'white')
        p.path('M 80 98 Q 80 88 76 84', weight=1.6); p.leaf(80, 90, -9, -8, 3.5); p.leaf(80, 92, 8, -8, 3.5)
        for x, y in [(62, 66), (70, 72), (56, 60)]:
            oval(p, x, y, 2.4, 1.8)


# ----------------------------------------------------------- garden objects

def scarecrow(p, v):
    p.path('M 50 113 L 50 80')
    p.path('M 36 54 L 16 54 L 16 63 L 36 65 Z', 'white'); p.path('M 64 54 L 84 54 L 84 63 L 64 65 Z', 'white')
    for x, k in ((16, -1), (84, 1)):
        p.path(f'M {x} 56 L {x+k*7} 52 M {x} 59 L {x+k*8} 60 M {x} 62 L {x+k*6} 67', weight=1.3)
    p.path('M 36 50 L 64 50 L 68 86 L 32 86 Z', 'white')
    p.path('M 53 64 L 61 64 L 61 72 L 53 72 Z', weight=1.3)
    p.path('M 36 86 L 34 93 M 44 86 L 44 94 M 56 86 L 57 94 M 64 86 L 67 92', weight=1.3)
    p.ellipse(50, 39, 11, 11)
    if v == 0:
        p.path('M 44 36 L 47 39 M 47 36 L 44 39 M 53 36 L 56 39 M 56 36 L 53 39', weight=1.3)
    else:
        p.dot(45, 37, 1.4); p.dot(55, 37, 1.4)
    p.path('M 44 44 Q 50 47 56 44', weight=1.3)
    p.path('M 41 29 L 43 16 L 57 16 L 59 29 Z', 'white')
    oval(p, 50, 29.5, 19, 3.6)
    if v:
        oval(p, 80, 47, 6, 4.5, -8); p.ellipse(86, 42, 3.4)
        p.path('M 89 42 L 93 43 L 89 44 M 74 48 L 69 50 L 73 51', weight=1.4)
        p.dot(87, 41, .8)


def birdhouse(p, v):
    p.path('M 47 113 L 47 70 M 55 113 L 55 70')
    p.path('M 31 42 L 71 42 L 71 72 L 31 72 Z', 'white')
    p.path('M 23 46 L 51 19 L 79 46 Z', 'white')
    p.path('M 27 44 L 51 23 L 75 44', weight=1.3)
    p.ellipse(51, 54, 6)
    p.dot(51, 66, 2)
    p.path('M 40 82 L 47 78 M 55 78 L 62 82', weight=1.6)
    if v:
        oval(p, 70, 25, 6, 4.5, -25); p.ellipse(75, 18, 3.4)
        p.path('M 78 17 L 82 18 L 78 19 M 64 29 L 59 33 L 64 32', weight=1.4)
        p.dot(76, 17, .8)
        p.path('M 40 113 L 38 102 M 44 113 L 46 104 M 60 113 L 63 103', weight=1.5)


def flowerpot(p, v):
    if v == 0:
        p.path('M 44 70 Q 42 56 38 48'); p.leaf(38, 48, -14, -6, 6); p.leaf(38, 49, 9, -12, 6)
        p.path('M 56 70 Q 58 60 62 54'); p.leaf(62, 54, 12, -7, 5); p.leaf(62, 55, -5, -12, 5)
    else:
        p.stem(x=50, top=32, bottom=70, bend=4, leaves=2)
        p.flower(50, 30, 13, 7)
    p.path('M 30 78 L 70 78 L 64 112 L 36 112 Z', 'white')
    p.path('M 26 69 L 74 69 L 74 80 L 26 80 Z', 'white')
    if v:
        p.path('M 56 88 L 52 96 L 57 102', weight=1.3)


def wheelbarrow(p, v):
    if v == 0:
        p.path('M 18 58 C 28 40 62 38 74 58 Z', 'white')
        p.path('M 46 46 Q 46 36 42 30'); p.leaf(42, 31, -10, -5, 4.5); p.leaf(43, 31, 5, -10, 4.5)
    else:
        for x, y, r in [(32, 50, 10), (54, 46, 12), (70, 52, 8)]:
            p.ellipse(x, y, r, r*.85)
            p.path(f'M {x} {y-r*.85+1:.2f} Q {x-1} {y-r:.2f} {x+3} {y-r-5:.2f}')
            p.path(f'M {x-r*.4:.2f} {y-r*.6:.2f} Q {x-r*.55:.2f} {y:.2f} {x-r*.35:.2f} {y+r*.6:.2f}', weight=1.2)
    p.path('M 14 56 L 80 56 L 68 82 L 26 84 Z', 'white')
    p.path('M 18 62 L 4 72 M 28 84 L 24 104 M 19 104 L 30 104 M 60 82 L 76 94')
    p.ellipse(77, 95, 13)
    p.dot(77, 95, 2)


def skep_x(y):
    return 31*((y-22)/82)**.5


def beehive(p, v):
    if v == 0:
        p.path('M 12 104 L 88 104 L 88 110 L 12 110 Z', 'white')
        pts = [(50-skep_x(y), y) for y in range(104, 22, -6)]+[(50, 22)]+[(50+skep_x(y), y) for y in range(28, 105, 6)]
        p.curve(pts, True, 'white')
        for y in (38, 52, 66, 80, 94):
            w = skep_x(y)-1.5
            p.path(f'M {50-w:.2f} {y} Q 50 {y+4} {50+w:.2f} {y}', weight=1.4)
        p.path('M 42 104 Q 50 91 58 104 Z', 'white')
        bee_x, bee_y = 82, 26
    else:
        p.path('M 26 104 L 24 112 M 74 104 L 76 112')
        p.path('M 24 62 L 76 62 L 76 104 L 24 104 Z', 'white')
        p.path('M 24 76 L 76 76 M 24 90 L 76 90', weight=1.5)
        p.path('M 18 62 L 50 44 L 82 62 Z', 'white')
        p.path('M 40 100 L 60 100', weight=2.2)
        bee_x, bee_y = 80, 26
    oval(p, bee_x, bee_y, 6.5, 4.6, 10)
    p.path(f'M {bee_x-2} {bee_y-4} L {bee_x-3} {bee_y+4} M {bee_x+2} {bee_y-4} L {bee_x+1} {bee_y+4}', weight=1.2)
    oval(p, bee_x-2, bee_y-8, 3, 4.5, -20, weight=1.2); oval(p, bee_x+3, bee_y-8, 3, 4.5, 20, weight=1.2)
    p.path(f'M {bee_x-12} {bee_y+10} L {bee_x-16} {bee_y+13} M {bee_x-21} {bee_y+16} L {bee_x-25} {bee_y+19}', weight=1.3)


def pinwheel_head(p, cx, cy, R, rot=0):
    for k in range(4):
        a = rot+k*90
        p1 = at(cx, cy, R, a); ctrl = at(cx, cy, R*.95, a+55); p3 = at(cx, cy, R*.55, a+88)
        p.path(f'M {cx:.2f} {cy:.2f} L {p1[0]:.2f} {p1[1]:.2f} Q {ctrl[0]:.2f} {ctrl[1]:.2f} {p3[0]:.2f} {p3[1]:.2f} Z', 'white')
    p.ellipse(cx, cy, 2.6)


def pinwheel(p, v):
    if v == 0:
        p.path('M 50 113 L 52 50')
        pinwheel_head(p, 52, 40, 24, 15)
    else:
        p.path('M 36 113 L 34 56 M 64 113 L 68 76')
        pinwheel_head(p, 34, 46, 18, 30)
        pinwheel_head(p, 68, 68, 14, 0)


def boot(p, dx, dy):
    p.path(f'M {30+dx} {50+dy} L {52+dx} {50+dy} L {52+dx} {90+dy} L {74+dx} {93+dy} Q {84+dx} {96+dy} {82+dx} {108+dy} L {26+dx} {108+dy} Q {24+dx} {92+dy} {30+dx} {88+dy} Z', 'white')
    p.path(f'M {28+dx} {48+dy} L {54+dx} {48+dy} L {54+dx} {56+dy} L {28+dx} {56+dy} Z', 'white')
    p.path(f'M {27+dx} {103+dy} L {82+dx} {103+dy}', weight=1.3)


def boots(p, v):
    if v == 0:
        boot(p, 12, -4)
        boot(p, -8, 2)
        p.path('M 6 114 Q 30 110 52 114 Q 74 118 94 113', weight=1.4)
    else:
        p.stem(x=40, top=24, bottom=52, bend=-3, leaves=1)
        p.flower(40, 24, 12, 6)
        boot(p, -2, 0)


# ---------------------------------------------------------------- seasonal

def snowflake(p, v):
    cx, cy, R = 50, 62, 36
    for k in range(6):
        a = -90+k*60
        x, y = at(cx, cy, R, a)
        p.path(f'M {cx} {cy} L {x:.2f} {y:.2f}', weight=1.8)
        marks = (14, 25) if v == 0 else (20,)
        for d in marks:
            bx, by = at(cx, cy, d, a); size = 9 if d < 20 else 7
            for s in (-1, 1):
                ex, ey = at(bx, by, size, a+s*45)
                p.path(f'M {bx:.2f} {by:.2f} L {ex:.2f} {ey:.2f}', weight=1.6)
        if v:
            tx, ty = at(cx, cy, R-4, a)
            p.path(P([at(tx, ty, 4, a), at(tx, ty, 3, a+90), at(tx, ty, 4, a+180), at(tx, ty, 3, a-90)]), weight=1.3)
    if v:
        p.path(P([at(cx, cy, 9, -90+k*60) for k in range(6)]), 'white', weight=1.6)


def maple_leaf(p, cx, cy, R):
    lobes = [(160, .55), (-145, .85), (-90, 1.0), (-35, .85), (20, .55)]
    pts = [at(cx, cy, R*.16, 105)]
    for i, (a, L) in enumerate(lobes):
        a = a-360 if a > 90 else a
        for da, rr in [(-22, .62), (-12, .56), (0, 1.0), (12, .56), (22, .62)]:
            pts.append(at(cx, cy, R*L*rr, a+da))
        if i < len(lobes)-1:
            nxt = lobes[i+1][0]
            pts.append(at(cx, cy, R*.36, (a+nxt)/2))
    pts.append(at(cx, cy, R*.16, 75))
    p.path(P(pts), 'white')
    for a, L in lobes:
        x, y = at(cx, cy, R*L*.78, a)
        p.path(f'M {cx} {cy} L {x:.2f} {y:.2f}', weight=1.2)
    p.path(f'M {cx} {cy} Q {cx+2} {cy+R*.5:.2f} {cx-1} {cy+R*.85:.2f}')


def maple(p, v):
    if v == 0:
        maple_leaf(p, 50, 64, 40)
    else:
        p.T = transform(.72, -26, -12, -18); maple_leaf(p, 50, 64, 40)
        p.T = transform(.6, 34, 14, 24); maple_leaf(p, 50, 64, 40)
        p.T = None


def blossom_branch(p, v):
    if v == 0:
        p.path('M 14 113 L 30 84 L 26 60 M 30 84 L 52 66 L 74 56 L 88 36 M 52 66 L 58 42')
        for x, y in [(26, 52), (58, 34), (76, 50), (86, 30)]:
            p.flower(x, y, 7.5, 5)
        for x, y in [(42, 72), (68, 62)]:
            oval(p, x, y, 2.6, 3.6)
    else:
        p.path('M 86 113 L 70 88 L 74 64 M 70 88 L 46 72 L 28 62 L 16 40 M 46 72 L 40 48')
        for x, y in [(74, 56), (40, 40), (24, 56), (16, 32)]:
            p.flower(x, y, 7.5, 5)
        oval(p, 56, 78, 2.6, 3.6)
        for x, y, a in [(64, 30, 30), (82, 40, -20)]:
            oval(p, x, y, 3.4, 2.4, a, weight=1.3)


ADDITIONS = [
 ('dandelion',dandelion,0),('dandelion',dandelion,1),('foxtail',foxtail,0),('foxtail',foxtail,1),
 ('shamrock',shamrock,0),('luckyclover',shamrock,1),('lavender',lavender,0),('lavender',lavender,1),
 ('morningglory',morning_glory,0),('morningglory',morning_glory,1),('hydrangea',hydrangea,0),('hydrangea',hydrangea,1),
 ('lotuspod',lotus,0),('lotus',lotus,1),('blossom',blossom_branch,0),('blossom',blossom_branch,1),
 ('tomato',tomato,0),('tomato',tomato,1),('peapod',peapod,0),('peapod',peapod,1),
 ('persimmon',persimmon,0),('persimmon',persimmon,1),('gourd',gourd,0),('gourd',gourd,1),
 ('dragonfly',dragonfly,0),('dragonfly',dragonfly,1),('rabbit',rabbit,0),('rabbit',rabbit,1),
 ('squirrel',squirrel,0),('squirrel',squirrel,1),('cat',cat,0),('cat',cat,1),('ant',ant,0),('ant',ant,1),
 ('mole',mole,0),('mole',mole,1),('scarecrow',scarecrow,0),('scarecrow',scarecrow,1),
 ('birdhouse',birdhouse,0),('birdhouse',birdhouse,1),('flowerpot',flowerpot,0),('flowerpot',flowerpot,1),
 ('wheelbarrow',wheelbarrow,0),('wheelbarrow',wheelbarrow,1),('beehive',beehive,0),('beehive',beehive,1),
 ('pinwheel',pinwheel,0),('pinwheel',pinwheel,1),('boots',boots,0),('boots',boots,1),
 ('snowflake',snowflake,0),('snowflake',snowflake,1),('maple',maple,0),('maple',maple,1),
]
# Numbers 1-365 are the reference slots and 366 the leap day.
FIRST_ADDITION = 367


def draw_subject(pen:Pen,kind:str,v:int):
    if not (foliage(pen,kind,v) or fruit(pen,kind,v) or animal(pen,kind,v)
            or objects(pen,kind,v) or special(pen,kind,v)):
        if kind=='mushroom':mushroom(pen,v)
        else:raise ValueError(f'Unimplemented subject {kind}')


def draw_asset(kind:str,number:int):
    pen=Pen(number)
    draw_subject(pen,kind,number)
    return pen




# ---------------------------------------------------------------- new hands
# A "hand" is a fresh drawing of a known subject. The numbered library above
# stays frozen; a hand reuses the same drawer with its own structure seed, pen
# wobble and a gentle whole-drawing bend, so each one is recognisably the same
# kind of plant or object and still differs when looked at closely.

ADDITION_HANDS: dict[str, list] = {}
for _kind, _drawer, _variant in ADDITIONS:
    ADDITION_HANDS.setdefault(_kind, []).append((_drawer, _variant))


def hand_frame(rng: random.Random, tilt: float):
    """Mirror, tilt, squash and softly bend a whole drawing around its centre.
    Returns the map and its overall scale."""
    mirror = rng.random() < .5
    angle = math.radians(rng.uniform(-tilt, tilt))
    size = rng.uniform(.93, 1.0)
    sx, sy = size*rng.uniform(.96, 1.04), size*rng.uniform(.96, 1.04)
    # Long, shallow waves: lines bend a little, nothing kinks or crosses.
    ax, ay = rng.uniform(.6, 2.2), rng.uniform(.6, 2.2)
    kx, ky = TAU/rng.uniform(70, 140), TAU/rng.uniform(70, 140)
    px, py = rng.uniform(0, TAU), rng.uniform(0, TAU)
    c, s = math.cos(angle), math.sin(angle)

    def frame(x, y):
        x, y = x+ax*math.sin(ky*y+px), y+ay*math.sin(kx*x+py)
        x, y = (x-50)*sx, (y-60)*sy
        if mirror:
            x = -x
        return 50+x*c-y*s, 60+x*s+y*c
    return frame, math.sqrt(sx*sy)


def berries_hand(p: Pen, rng: random.Random):
    """Three or four berries on their own branches; the library's bush is fixed.
    One berry always reaches to each side so the bush keeps its breadth."""
    left = rng.sample([(21, 53), (30, 27), (34, 70)], rng.randint(1, 2))
    right = [rng.choice([(76, 39), (70, 62)])]
    chosen = [(49, 38)]+left+right
    base = 50+rng.uniform(-4, 4)
    p.path(f'M {base:.1f} 111 Q {base+rng.uniform(-3, 6):.1f} 70 {47+rng.uniform(-3, 3):.1f} 46')
    for x, y in chosen:
        x, y, r = x+rng.uniform(-3, 3), y+rng.uniform(-3, 3), rng.uniform(9.5, 11.5)
        fork = rng.uniform(62, 92)
        p.path(f'M {base+(111-fork)*.03:.1f} {fork:.1f} Q {(base+x)/2+rng.uniform(-6, 6):.1f} {(fork+y)/2:.1f} {x:.1f} {y+r*.8:.1f}')
        p.ellipse(x, y, r)
        dots = rng.randint(4, 6)
        turn = rng.uniform(0, TAU)
        for i in range(dots):
            a = turn+TAU*i/dots
            p.dot(x+math.cos(a)*r*.45, y+math.sin(a)*r*.45, .8)
    side = rng.choice((-1, 1))
    p.leaf(base+side, rng.uniform(80, 98), side*rng.uniform(18, 26), -rng.uniform(6, 14), rng.uniform(6, 8))


def succulent_hand(p: Pen, rng: random.Random):
    """A rosette of six to eight veined leaves; the library's rosette is fixed."""
    count = rng.randint(6, 8)
    for i in range(count):
        t = i/(count-1)
        a = math.radians(-156+132*t+rng.uniform(-5, 5))
        length = (38+32*math.sin(math.pi*t))*rng.uniform(.93, 1.06)
        p.leaf(50, 104, math.cos(a)*length, math.sin(a)*length, rng.uniform(8, 9.5), True)
    p.path(f'M {22+rng.uniform(-3, 3):.1f} 112 Q 50 {119+rng.uniform(-2, 2):.1f} {82+rng.uniform(-3, 3):.1f} 112')


def apple_hand(p: Pen, rng: random.Random):
    """Plumper or taller, a little lopsided; stem, leaves and face vary."""
    sx, sy = rng.uniform(.9, 1.1), rng.uniform(.92, 1.06)
    lean = rng.uniform(-3, 3)
    dip = rng.uniform(-3, 4)

    def q(x, y):
        return f'{50+(x-50)*sx+lean*(76-y)/40:.1f} {76+(y-76)*sy:.1f}'
    p.path(f'M {q(50, 43+dip)} C {q(23, 29)} {q(10, 54)} {q(19, 78)} C {q(25, 107)} {q(39, 115)} {q(52, 107)} '
           f'C {q(70, 119)} {q(91, 87)} {q(83, 59)} C {q(79, 37)} {q(60, 37)} {q(50, 43+dip)} Z', 'white')
    top = 76+(41+dip-76)*sy
    bend = rng.uniform(-1, 1)
    p.path(f'M 51 {top:.1f} Q {49+bend*4:.1f} {top-14:.1f} {54+bend*8:.1f} {top-19:.1f}')
    for _ in range(rng.choice((1, 1, 2))):
        side = rng.choice((-1, 1))
        p.leaf(52, top-4, side*rng.uniform(13, 20), -rng.uniform(10, 17), rng.uniform(5, 7))
    if rng.random() < .35:
        p.face(49+lean, 74, rng.uniform(8, 10))
    elif rng.random() < .5:
        x = 50-26*sx
        p.path(f'M {x+4:.1f} 72 Q {x+5:.1f} 63 {x+11:.1f} 59', weight=1.4)


def snail_hand(p: Pen, rng: random.Random):
    """Shell size and coil, body length and feelers all vary."""
    tail = rng.uniform(10, 20)
    neck = rng.uniform(-3, 3)
    p.path(f'M {tail:.1f} 103 Q 26 96 48 99 L {77+neck:.1f} 96 C {75+neck:.1f} 79 {86+neck:.1f} 77 {86+neck:.1f} 96 '
           f'L 88 106 Q 48 117 {tail:.1f} 111 Z', 'white')
    r = rng.uniform(20, 25)
    cx = rng.uniform(41, 48)
    cy = 108-r
    p.ellipse(cx, cy, r, r*rng.uniform(.92, 1.04))
    p.spiral(cx, cy, r*rng.uniform(.66, .76), rng.uniform(1.8, 2.4))
    for side, base in ((-1, 78+neck), (1, 85+neck)):
        length = rng.uniform(9, 13)
        a = math.radians(-90+side*rng.uniform(10, 32))
        tip = (base+math.cos(a)*length, 86+math.sin(a)*length)
        p.path(f'M {base:.1f} 86 L {tip[0]:.1f} {tip[1]:.1f}')
        p.dot(*tip, 1.6)
    p.dot(84+neck, 98, .9)
    if rng.random() < .3:
        for i in range(3):
            p.dot(tail-4-i*4, 110+rng.uniform(-1, 1), .7)


def house_hand(p: Pen, rng: random.Random):
    """Roof pitch, door, window, chimney and grass vary; walls stay square."""
    apex = rng.uniform(13, 21)
    eave = rng.uniform(52, 58)
    left, right = rng.uniform(22, 26), rng.uniform(77, 81)
    p.path(f'M {left-3:.1f} {eave:.1f} L 50 {apex+5:.1f} L {right+4:.1f} {eave:.1f} L {right:.1f} 109 L {left:.1f} 109 Z', 'white')
    p.path(f'M {left-6:.1f} {eave:.1f} L 50 {apex:.1f} L {right+8:.1f} {eave:.1f}')
    door = rng.uniform(36, 58)
    width = rng.uniform(18, 23)
    if rng.random() < .65:
        p.path(f'M {door:.1f} 109 L {door:.1f} 82 Q {door+width/2:.1f} 70 {door+width:.1f} 82 L {door+width:.1f} 109')
    else:
        p.path(f'M {door:.1f} 109 L {door:.1f} 78 L {door+width:.1f} 78 L {door+width:.1f} 109')
        p.dot(door+width-4, 95, 1)
    if rng.random() < .6:
        p.path(f'M {left+5:.1f} {eave+7:.1f} L {right-5:.1f} {eave+7:.1f}')
    else:
        x = left+7 if door > 47 else right-17
        p.path(f'M {x:.1f} {eave+11:.1f} L {x+10:.1f} {eave+11:.1f} L {x+10:.1f} {eave+20:.1f} L {x:.1f} {eave+20:.1f} Z')
    if rng.random() < .25:
        # A chimney stands on the slope away from the apex.
        x = rng.choice((30, 63))
        rise = (eave-apex)/27

        def roof(at):
            return apex+rise*abs(at-50)
        p.path(f'M {x:.1f} {roof(x)-1:.1f} L {x:.1f} {roof(x)-10:.1f} L {x+6:.1f} {roof(x)-10:.1f} L {x+6:.1f} {roof(x+6)-1:.1f}')
    if rng.random() < .35:
        for x, y in [(15, 114), (84, 112)]:
            p.path(f'M {x} {y} L {x-4} {y-8} M {x} {y} L {x+5} {y-7}', weight=2)


def _f(point):
    return f'{point[0]:.1f} {point[1]:.1f}'


def fish_hand(p: Pen, rng: random.Random):
    """Body depth, tail, fins, scales and eye vary; sometimes a few bubbles."""
    depth, length = rng.uniform(.9, 1.05), rng.uniform(.93, 1.03)

    def q(x, y):
        return 50+(x-55)*length, 70+(y-70)*depth
    tail = rng.choice(('fork', 'round', 'fan'))
    body = f'M {_f(q(21, 70))} C {_f(q(39, 34))} {_f(q(68, 37))} {_f(q(78, 65))} '
    if tail == 'fork':
        body += f'L {_f(q(94, 52))} L {_f(q(87, 70))} L {_f(q(93, 85))} L {_f(q(78, 74))} '
    elif tail == 'round':
        body += f'Q {_f(q(98, 57))} {_f(q(95, 70))} Q {_f(q(98, 83))} {_f(q(78, 74))} '
    else:
        body += f'L {_f(q(95, 51))} L {_f(q(92, 82))} L {_f(q(78, 74))} '
    body += f'C {_f(q(64, 105))} {_f(q(34, 103))} {_f(q(21, 70))} Z'
    p.path(body, 'white')
    gill = rng.uniform(38, 46)
    p.path(f'M {_f(q(gill, 47))} Q {_f(q(gill+12, 71))} {_f(q(gill+3, 93))}')
    if rng.random() < .8:
        p.path(f'M {_f(q(40, 45))} L {_f(q(49+rng.uniform(-4, 4), 30))} L {_f(q(66, 41))}')
    if rng.random() < .6:
        p.path(f'M {_f(q(51, 96))} L {_f(q(59, 107))} L {_f(q(72, 88))}')
    p.dot(*q(31, 66), rng.uniform(1.3, 1.7))
    if rng.random() < .25:
        p.path(f'M {_f(q(24, 76))} Q {_f(q(28, 79))} {_f(q(32, 76))}', weight=1.5)
    for _ in range(rng.randint(2, 3)):
        x, y = q(rng.uniform(52, 70), rng.uniform(58, 84))
        p.path(f'M {x-3:.1f} {y-2:.1f} Q {x:.1f} {y+4:.1f} {x+3:.1f} {y-2:.1f}', weight=1.6)
    if rng.random() < .25:
        for i in range(2):
            p.ellipse(16+i*3, 50-i*9, 2.2-i*.4)


def fig_hand(p: Pen, rng: random.Random):
    """Plumper or slimmer, leaning, with its own seeds and sometimes a leaf."""
    sx, sy, lean = rng.uniform(.92, 1.06), rng.uniform(.95, 1.05), rng.uniform(-4, 4)

    def q(x, y):
        return 50+(x-50)*sx+lean*(80-y)/50, 72+(y-72)*sy
    p.path(f'M {_f(q(52, 31))} C {_f(q(26, 38))} {_f(q(12, 69))} {_f(q(22, 90))} C {_f(q(35, 117))} {_f(q(60, 112))} '
           f'{_f(q(74, 92))} C {_f(q(92, 59))} {_f(q(74, 32))} {_f(q(52, 31))} Z', 'white')
    top = q(52, 31)
    if rng.random() < .6:
        p.path(f'M {_f(top)} L {top[0]+rng.uniform(-2, 3):.1f} {top[1]-rng.uniform(4, 7):.1f}')
    if rng.random() < .75:
        p.path(f'M {_f(q(52, 37))} Q {_f(q(40+rng.uniform(-4, 4), 68))} {_f(q(56, 106))}')
    seeds = []
    while len(seeds) < rng.randint(4, 6):
        x, y = rng.uniform(32, 70), rng.uniform(50, 95)
        if all(math.hypot(x-a, y-b) > 11 for a, b in seeds):
            seeds.append((x, y))
    for x, y in seeds:
        p.dot(*q(x, y), 1)
    if rng.random() < .25:
        side = rng.choice((-1, 1))
        p.leaf(top[0], top[1]-2, side*rng.uniform(13, 18), -rng.uniform(5, 10), 5)


def cluster_hand(p: Pen, rng: random.Random, kind: str):
    """Grapes hang as a tapering bunch; raspberries are a rounder knot of beads."""
    r = rng.uniform(6.3, 7.0)
    if kind == 'grapes':
        sizes = list(range(rng.choice((4, 5)), 0, -1))
    else:
        sizes = rng.choice(([4, 5, 4, 3, 1], [3, 4, 5, 4, 2], [4, 5, 4, 2], [3, 4, 4, 3, 1]))
    top, dy = 36+rng.uniform(-2, 3), r*1.95
    skip = rng.randrange(1, sum(sizes)) if rng.random() < .25 else -1
    index = 0
    for row, count in enumerate(sizes):
        for j in range(count):
            if index != skip:
                p.ellipse(50+(j-(count-1)/2)*r*1.72+rng.uniform(-.8, .8), top+row*dy+rng.uniform(-.8, .8), r)
            index += 1
    bend = rng.choice((-1, 1))
    p.path(f'M 50 {top-r+1:.1f} Q {50-bend*7:.1f} {top-15:.1f} {50+bend*rng.uniform(5, 9):.1f} {top-20:.1f}')
    p.leaf(50, top-r-6, bend*rng.uniform(16, 22), -rng.uniform(4, 9), 7)
    if kind == 'grapes' and rng.random() < .35:
        p.spiral(50-bend*13, top-14, 5, 1.6)


def pine_hand(p: Pen, rng: random.Random):
    """Three or four tiers of different widths and notches on a short trunk."""
    tiers = rng.choice((3, 4, 4))
    apex, base = rng.uniform(11, 18), rng.uniform(88, 93)
    edges = [apex+(base-apex)*(k+1)/tiers for k in range(tiers)]
    widths = [(13+24*(k+1)/tiers)*rng.uniform(.9, 1.06) for k in range(tiers)]
    left, right = [], []
    for k, (y, w) in enumerate(zip(edges, widths)):
        left.append((51-w, y))
        right.append((51+w*rng.uniform(.95, 1.05), y+rng.uniform(-1.5, 1.5)))
        if k < tiers-1:
            notch = rng.uniform(.5, .66)
            left.append((51-w*notch, y-rng.uniform(1, 3)))
            right.append((51+w*notch, y-rng.uniform(1, 3)))
    outline = f'M 51 {apex:.1f} '+' '.join(f'L {_f(pt)}' for pt in left)
    outline += f' Q 50 {base+rng.uniform(12, 18):.1f} {_f(right[-1])} '+' '.join(f'L {_f(pt)}' for pt in reversed(right[:-1]))+' Z'
    p.path(f'M 51 113 L 51 {base:.1f}')
    p.path(outline, 'white')
    p.path(f'M 51 {apex+16:.1f} L 51 {base+3:.1f}', weight=2)
    for k in rng.sample(range(tiers), min(tiers, rng.randint(2, 3))):
        side = rng.choice((-1, 1))
        y = edges[k]-3
        p.path(f'M 51 {y:.1f} L {51+side*widths[k]*.62:.1f} {y-9:.1f}', weight=2)


def cactus_hand(p: Pen, rng: random.Random):
    """Arms at different heights and lengths, with spines and sometimes a bloom."""
    cx, half, top = rng.uniform(49, 54), rng.uniform(7.5, 9.5), rng.uniform(19, 28)
    arms = rng.choice(('both',)*4+('left', 'right'))
    reach = 6 if arms != 'both' else 0
    path = f'M {cx-half:.1f} 114 '
    if arms in ('both', 'left'):
        y, x, up = rng.uniform(66, 80), rng.uniform(18, 25)-reach, rng.uniform(14, 24)
        path += f'L {cx-half:.1f} {y:.1f} Q {x:.1f} {y+2:.1f} {x:.1f} {y-9:.1f} L {x:.1f} {y-up:.1f} Q {x+5:.1f} {y-up-8:.1f} {x+10:.1f} {y-up:.1f} L {x+10:.1f} {y-11:.1f} L {cx-half:.1f} {y-11:.1f} '
    path += f'L {cx-half:.1f} {top+8:.1f} Q {cx:.1f} {top-9:.1f} {cx+half:.1f} {top+8:.1f} '
    if arms in ('both', 'right'):
        y, x, up = rng.uniform(70, 86), rng.uniform(77, 84)+reach, rng.uniform(14, 24)
        path += f'L {cx+half:.1f} {y-11:.1f} L {x-10:.1f} {y-11:.1f} L {x-10:.1f} {y-up:.1f} Q {x-5:.1f} {y-up-8:.1f} {x:.1f} {y-up:.1f} L {x:.1f} {y-9:.1f} Q {x:.1f} {y+2:.1f} {cx+half:.1f} {y:.1f} '
    path += f'L {cx+half:.1f} 114'
    p.path(path, 'white')
    for _ in range(rng.randint(5, 8)):
        x, y = cx+rng.uniform(-half+3, half-3), rng.uniform(top+10, 104)
        if rng.random() < .5:
            p.path(f'M {x:.1f} {y:.1f} L {x+1:.1f} {y+7:.1f}', weight=1.7)
        else:
            p.path(f'M {x-4:.1f} {y:.1f} L {x+4:.1f} {y:.1f}')
    if rng.random() < .2:
        for a in (-60, -90, -120):
            p.leaf(cx, top-1, math.cos(math.radians(a))*7, math.sin(math.radians(a))*7, 2.6)


def bird_hand(p: Pen, rng: random.Random, heron: bool = False):
    """Head, beak, tail, wing and stance vary; a heron keeps its long legs."""
    hx, hy, hr = 43+rng.uniform(-2, 2), 35+rng.uniform(-3, 2), rng.uniform(10, 11.5)
    tail = (rng.uniform(74, 82), rng.uniform(63, 72))
    p.path(f'M 44 {hy+7:.1f} C 30 44 19 65 21 75 C 33 98 70 96 {_f(tail)} L 48 67 Q 54 57 50 {hy+12:.1f} Z', 'white')
    p.ellipse(hx, hy, hr, hr)
    length, tilt = rng.uniform(13, 20)*(1.25 if heron else 1), math.radians(rng.uniform(-8, 14))
    tip = (hx-hr-length*math.cos(tilt), hy+3+length*math.sin(tilt))
    if rng.random() < .15:
        p.path(f'M {hx-hr+1:.1f} {hy:.1f} L {_f(tip)} M {hx-hr+1:.1f} {hy+5:.1f} L {tip[0]+3:.1f} {tip[1]+5:.1f}')
    else:
        p.path(f'M {hx-hr+1:.1f} {hy:.1f} L {_f(tip)} L {hx-hr+1:.1f} {hy+5:.1f}')
    p.dot(hx-1, hy-3, rng.uniform(1, 1.3))
    if rng.random() < .15:
        p.path(f'M {hx:.1f} {hy-hr:.1f} L {hx+2:.1f} {hy-hr-6:.1f}', weight=1.8)
    wing = rng.uniform(-6, 6)
    p.path(f'M 50 {72+wing/3:.1f} Q {30+wing:.1f} {80+wing/2:.1f} {30+wing/2:.1f} {62+wing/2:.1f}')
    if heron:
        p.path(f'M {_f(tail)} Q {tail[0]-1:.1f} 43 64 49 L 54 65')
        legs = 'M 43 91 L 33 99 L 43 107' if rng.random() < .5 else 'M 43 91 L 42 112 L 34 114'
        p.path(f'{legs} M 55 89 L 57 112 L 65 113')
    elif rng.random() < .25:
        p.path('M 49 90 L 49 108 L 41 110 M 49 108 L 57 110')
    else:
        spread = rng.uniform(-3, 4)
        p.path(f'M 43 91 L {43-spread:.1f} 109 L {33-spread:.1f} 111 M 55 89 L {56+spread:.1f} 109 L {64+spread:.1f} 110')


def worm_hand(p: Pen, rng: random.Random):
    """The library's caterpillar with its own count, wave, feet and feelers."""
    count = rng.choice((4, 5, 5, 6))
    step = 56/(count-1)
    amp, phase, k = rng.uniform(4, 7), rng.uniform(0, TAU), rng.uniform(1.1, 1.6)
    rx = min(10, step*.78)
    for i in range(count):
        p.ellipse(22+i*step, 74+math.sin(i*k+phase)*amp, rx, rng.uniform(12, 13.5))
    hx, hy = 80, 69+rng.uniform(-2, 2)
    p.ellipse(hx, hy, 12, 14)
    p.face(hx, hy-2, 6, rng.random() < .85)
    for i in range(count):
        x = 20+i*step
        if rng.random() < .85:
            p.path(f'M {x:.1f} 87 L {x-2+rng.uniform(-1, 1):.1f} 98')
    spread = rng.uniform(-3, 3)
    p.path(f'M {hx-2:.1f} {hy-13:.1f} L {hx-7-spread:.1f} {hy-25:.1f} M {hx+4:.1f} {hy-13:.1f} L {hx+9+spread:.1f} {hy-24:.1f}')


def stump_hand(p: Pen, rng: random.Random):
    """Width, roots, rings and bark vary; a sprout may grow from the cut."""
    half, top = rng.uniform(25, 30), rng.uniform(46, 52)
    l, r = 50-half, 50+half
    base = f'M {l:.1f} {top+11:.1f} L {l+9:.1f} {top:.1f} L {r-9:.1f} {top:.1f} L {r:.1f} {top+10:.1f} L {r-3:.1f} 99 '
    base += f'L {r+rng.uniform(6, 11):.1f} 110 L {r-rng.uniform(16, 22):.1f} 111 '
    if rng.random() < .5:
        base += f'L 50 {rng.uniform(100, 104):.1f} L {50-rng.uniform(4, 10):.1f} 112 '
    base += f'L {l-rng.uniform(6, 11):.1f} 110 L {l+2:.1f} 99 Z'
    p.path(base, 'white')
    p.path(f'M {l+3:.1f} {top+10:.1f} Q 50 {top-7:.1f} {r-4:.1f} {top+9:.1f} Q 57 {top+32:.1f} {l+3:.1f} {top+10:.1f} Z', 'white')
    if rng.random() < .35:
        w = rng.uniform(.4, .6)
        p.path(f'M {50-half*w:.1f} {top+11:.1f} Q 50 {top+5:.1f} {50+half*w:.1f} {top+10:.1f}', weight=1.5)
    for _ in range(rng.choice((2, 2, 3))):
        x = rng.uniform(l+7, r-7)
        p.path(f'M {x:.1f} {top+rng.uniform(27, 33):.1f} L {x+rng.uniform(-3, 3):.1f} {rng.uniform(90, 99):.1f}')
    if rng.random() < .3:
        x = rng.uniform(l+12, r-12)
        p.path(f'M {x:.1f} {top+6:.1f} Q {x+2:.1f} {top-4:.1f} {x:.1f} {top-10:.1f}')
        p.leaf(x, top-6, -8, -5, 3.6)
        p.leaf(x, top-9, 8, -5, 3.6)


def strawberry_hand(p: Pen, rng: random.Random):
    """Rounder or more pointed, with its own leafy cap and seeds."""
    sx, sy, tip = rng.uniform(.92, 1.05), rng.uniform(.93, 1.04), rng.uniform(-4, 4)

    def q(x, y):
        return 50+(x-50)*sx+tip*(y-42)/67, 42+(y-42)*sy
    p.path(f'M {_f(q(21, 42))} C {_f(q(12, 70))} {_f(q(37, 102))} {_f(q(50, 109))} C {_f(q(64, 105))} {_f(q(91, 70))} '
           f'{_f(q(80, 44))} Q {_f(q(50, 30))} {_f(q(21, 42))} Z', 'white')
    tips = rng.choice((3, 3, 4))
    crown, left, right = [], rng.uniform(25, 30), rng.uniform(70, 75)
    crown.append((left, rng.uniform(42, 46)))
    for i in range(tips):
        x = left+(right-left)*(i+.5)/tips
        crown.append((x+rng.uniform(-2, 2), rng.uniform(20, 27)))
        if i < tips-1:
            crown.append((left+(right-left)*(i+1)/tips, rng.uniform(32, 37)))
    crown += [(right, rng.uniform(41, 45)), (right-rng.uniform(9, 13), rng.uniform(46, 49)),
              (50+rng.uniform(-3, 3), rng.uniform(37, 40)), (left+rng.uniform(9, 13), rng.uniform(47, 50))]
    p.path(P(crown), 'white')
    seeds = []
    while len(seeds) < rng.randint(5, 7):
        x, y = rng.uniform(31, 69), rng.uniform(56, 95)
        if all(math.hypot(x-a, y-b) > 10 for a, b in seeds) and abs(x-50) < 22-(y-56)*.35:
            seeds.append((x, y))
    for x, y in seeds:
        x, y = q(x, y)
        p.path(f'M {x:.1f} {y:.1f} L {x+1:.1f} {y+3:.1f}', weight=2)


def star_hand(p: Pen, rng: random.Random):
    """Six to eight points, fat or thin, with spokes, a face or sparkles."""
    points, outer = rng.choice((6, 7, 8, 8)), rng.uniform(41, 46)
    inner = outer*rng.uniform(.44, .54)
    turn = rng.uniform(0, TAU/points)
    shape = []
    for i in range(points*2):
        a = turn+TAU*i/(points*2)-math.pi/2
        radius = outer*rng.uniform(.95, 1.03) if i % 2 == 0 else inner
        shape.append((50+math.cos(a)*radius, 62+math.sin(a)*radius))
    p.path(P(shape), 'white')
    if rng.random() < .2:
        p.face(50, 62, 9)
    else:
        step = 2 if rng.random() < .55 else 4
        reach = rng.uniform(.65, .85)
        for i in range(0, points*2, step):
            p.path(f'M 50 62 L {50+(shape[i][0]-50)*reach:.1f} {62+(shape[i][1]-62)*reach:.1f}')
    if rng.random() < .25:
        for x, y in rng.sample([(12, 20), (88, 22), (14, 104), (88, 104)], 2):
            p.path(f'M {x-4} {y} L {x+4} {y} M {x} {y-4} L {x} {y+4}', weight=1.6)


def spade_hand(p: Pen, rng: random.Random):
    """Grip, shaft and blade shape vary; sometimes clods of soil."""
    blade_top = rng.uniform(84, 92)
    grip = rng.choice(('d', 'd', 't', 'ring'))
    if grip == 'd':
        p.path('M 37 15 L 64 15 L 62 36 Q 52 48 39 36 Z', 'white')
        neck = 42
    elif grip == 't':
        p.path('M 34 18 L 67 18 L 67 27 L 34 27 Z', 'white')
        neck = 27
    else:
        p.ellipse(51, 24, 10, 9)
        neck = 33
    p.path(f'M 47.5 {blade_top+1:.1f} L 48 {neck} L 55 {neck} L 55.5 {blade_top+1:.1f}')
    w = rng.uniform(17, 21)
    blade = rng.choice(('point', 'square', 'round'))
    if blade == 'point':
        p.path(f'M {51-w:.1f} {blade_top:.1f} L {51+w:.1f} {blade_top:.1f} L {53+w:.1f} 108 L 51 117 L {49-w:.1f} 108 Z', 'white')
    elif blade == 'square':
        p.path(f'M {51-w:.1f} {blade_top:.1f} L {51+w:.1f} {blade_top:.1f} L {52+w:.1f} 114 L {50-w:.1f} 114 Z', 'white')
    else:
        p.path(f'M {51-w:.1f} {blade_top:.1f} L {51+w:.1f} {blade_top:.1f} L {52+w:.1f} 104 Q 51 122 {50-w:.1f} 104 Z', 'white')
    if rng.random() < .3:
        p.path(f'M 51 {blade_top+4:.1f} L 51 {blade_top+14:.1f}', weight=1.6)


def pumpkin_hand(p: Pen, rng: random.Random):
    """Squatter or rounder, with its own ribs, stalk, leaf and curl."""
    sx, sy = rng.uniform(.9, 1.02), rng.uniform(.93, 1.04)

    def q(x, y):
        return 50+(x-50)*sx, 76+(y-76)*sy
    p.path(f'M {_f(q(50, 43))} C {_f(q(23, 29))} {_f(q(10, 54))} {_f(q(19, 78))} C {_f(q(25, 107))} {_f(q(39, 115))} '
           f'{_f(q(52, 107))} C {_f(q(70, 119))} {_f(q(91, 87))} {_f(q(83, 59))} C {_f(q(79, 37))} {_f(q(60, 37))} {_f(q(50, 43))} Z', 'white')
    ribs = rng.choice((3, 3, 4))
    for i in range(ribs):
        x = 50+(i-(ribs-1)/2)*rng.uniform(12, 15)
        bow = (x-50)*rng.uniform(.5, .8)
        p.path(f'M {_f(q(x-bow*.2, 46))} C {_f(q(x+bow, 66))} {_f(q(x+bow, 92))} {_f(q(x, 107))}')
    top = q(50, 43)
    lean = rng.uniform(-6, 8)
    p.path(f'M {top[0]:.1f} {top[1]:.1f} Q {top[0]-2+lean*.3:.1f} {top[1]-9:.1f} {top[0]+4+lean*.5:.1f} {top[1]-14:.1f}')
    side = rng.choice((-1, 1))
    p.leaf(top[0]+side*2, top[1]-4, side*rng.uniform(15, 20), -rng.uniform(6, 12), 5.5)
    if rng.random() < .35:
        p.spiral(top[0]-side*12, top[1]-10, 5, 1.6)


def log_hand(p: Pen, rng: random.Random):
    """The library's split log, recut: its block, end grain and bark lines vary."""
    def j(v, k=3):
        return v+rng.uniform(-k, k)
    near, far = (j(16), j(53)), (j(68), j(45))
    corner, foot = (j(86), j(56)), (j(85), j(102))
    low, back = (j(34), j(113, 2)), (j(16), j(100))
    p.path(f'M {_f(near)} L {_f(far)} L {_f(corner)} L {_f(foot)} L {_f(low)} L {_f(back)} Z', 'white')
    face = j(35, 2)
    p.path(f'M {near[0]+1:.1f} {near[1]:.1f} Q {face+4:.1f} {near[1]-6:.1f} {face:.1f} {j(74):.1f} L {face:.1f} {low[1]-1:.1f}')
    lines = rng.sample([(41, 69, 76, 63), (44, 84, 72, 81), (45, 103, 77, 96), (48, 76, 80, 71), (46, 94, 74, 89)], rng.randint(2, 3))
    for x1, y1, x2, y2 in lines:
        p.path(f'M {j(x1):.1f} {j(y1, 2):.1f} L {j(x2):.1f} {j(y2, 2):.1f}')
    if rng.random() < .6:
        p.path(f'M {j(25, 2):.1f} {j(67):.1f} L {j(25, 2):.1f} {j(97):.1f}')
    extra = rng.random()
    if extra < .3:
        oval(p, j(60, 6), j(74, 2), 3.6, 2.4)
    elif extra < .55:
        x = j(56, 6)
        p.path(f'M {x:.1f} {far[1]+2:.1f} Q {x+3:.1f} {far[1]-7:.1f} {x+8:.1f} {far[1]-12:.1f}')
        p.leaf(x+6, far[1]-9, 10, -4, 4)


def hedgehog_hand(p: Pen, rng: random.Random):
    """The library's hedgehog with its own quills, snout and stride."""
    back = [(10, 84), (15, 67), (10, 63), (21, 59), (18, 48), (32, 50), (32, 40), (45, 46), (52, 36),
            (59, 44), (70, 41), (73, 55), (84, 62), (79, 73)]
    points = []
    for i, (x, y) in enumerate(back):
        # Quill tips (odd points) grow or shrink; the body line just wobbles.
        if i % 2 == 0 and 0 < i < len(back)-1:
            cx, cy = 50, 80
            grow = rng.uniform(.9, 1.1)
            x, y = cx+(x-cx)*grow, cy+(y-cy)*grow
        points.append((x+rng.uniform(-1.5, 1.5), y+rng.uniform(-1.5, 1.5)))
    nose = (rng.uniform(90, 94), rng.uniform(83, 87))
    points += [nose, (nose[0]-5, 95), (11, 97)]
    p.curve(points, True, 'white')
    p.dot(nose[0]-12, nose[1]-1, 1.6)
    marks = rng.sample([(25, 70), (37, 58), (50, 68), (65, 58), (51, 87), (30, 84), (60, 78)], rng.randint(4, 5))
    for x, y in marks:
        p.path(f'M {x} {y} L {x+4} {y+6}', weight=2)
    stride = rng.uniform(-3, 3)
    p.path(f'M {18+stride:.1f} 99 L {17+stride:.1f} 110 M {70-stride:.1f} 97 L {73-stride:.1f} 109')


def camp_hand(p: Pen, rng: random.Random):
    """A tent of its own pitch and door; poles, pegs or a flag vary."""
    ax, ay = rng.uniform(43, 49), rng.uniform(39, 44)
    l, r = rng.uniform(15, 21), rng.uniform(73, 79)
    p.path(f'M {l:.1f} 100 L {ax:.1f} {ay:.1f} L {r:.1f} 99 Z', 'white')
    if rng.random() < .7:
        side = rng.uniform(90, 96)
        p.path(f'M {ax+1:.1f} {ay+2:.1f} L {side-10:.1f} {ay+20:.1f} L {side:.1f} 100 L {r:.1f} 99')
    if rng.random() < .65:
        p.path(f'M {ax-9:.1f} 100 L {ax+1:.1f} {ay+20:.1f} L {ax+16:.1f} 100')
    else:
        p.path(f'M {ax+1:.1f} {ay+22:.1f} L {ax+1:.1f} 100')
    if rng.random() < .75:
        p.path(f'M {ax:.1f} {ay+1:.1f} L {ax-6:.1f} {ay-11:.1f} M {ax+1:.1f} {ay+1:.1f} L {ax+7:.1f} {ay-11:.1f}')
    elif rng.random() < .5:
        p.path(f'M {ax:.1f} {ay:.1f} L {ax:.1f} {ay-13:.1f} L {ax+9:.1f} {ay-10:.1f} L {ax:.1f} {ay-7:.1f}')
    p.path(f'M {l-3:.1f} 103 L {l-8:.1f} 111 M {r+5:.1f} 103 L {r+12:.1f} 112')


def butterfly_hand(p: Pen, rng: random.Random):
    """Wing size and cut, wing marks and feelers vary; it stays symmetric."""
    up, low = rng.uniform(.9, 1.05), rng.uniform(.88, 1.06)
    split = rng.random() < .5
    # A single-piece wing carries the library's vein; split wings take spots.
    pattern = rng.choice(('dots', 'rings')) if split else rng.choice(('lines', 'lines', 'dots', 'rings'))
    for side in (-1, 1):
        def q(x, y):
            return 50+side*x, y
        if split:
            # Hind wing first so the forewing overlaps it cleanly.
            p.path(f'M {_f(q(3, 63))} C {_f(q(27*low, 64))} {_f(q(32*low, 88))} {_f(q(17*low, 92))} Q {_f(q(6, 92))} {_f(q(4, 72))}', 'white')
            p.path(f'M {_f(q(3, 55))} C {_f(q(12*up, 26))} {_f(q(42*up, 22))} {_f(q(38*up, 54))} Q {_f(q(22, 59))} {_f(q(3, 59))}', 'white')
        else:
            p.path(f'M {_f(q(2, 53))} C {_f(q(14*up, 27))} {_f(q(44*up, 24))} {_f(q(36*up, 62))} C {_f(q(34*low, 79))} {_f(q(20*low, 91))} {_f(q(5, 87))}', 'white')
        if pattern == 'lines':
            p.path(f'M {_f(q(4, 64))} Q {_f(q(20*up, 41))} {_f(q(26*up, 47))} Q {_f(q(30*up, 68))} {_f(q(8, 81))}')
        elif pattern == 'dots':
            for x, y in [(22*up, 42), (15*low, 77)]:
                p.dot(*q(x, y), 2.2)
        else:
            p.ellipse(*q(22*up, 44), 5)
        a = math.radians(-118 if side < 0 else -62)+math.radians(rng.uniform(-8, 8))
        tip = (50+side*2+math.cos(a)*18, 49+math.sin(a)*18)
        p.path(f'M {50+side*2:.1f} 49 L {_f(tip)}')
        if rng.random() < .5:
            p.dot(*tip, 1.5)
    p.path('M 47 49 Q 51 44 56 49 L 55 97 Q 50 112 47 98 Z', 'white')


SUBJECT_HANDS = {
    'berries': berries_hand, 'succulent': succulent_hand, 'apple': apple_hand, 'snail': snail_hand,
    'house': house_hand, 'fish': fish_hand, 'fig': fig_hand, 'pine': pine_hand, 'cactus': cactus_hand,
    'bird': bird_hand, 'worm': worm_hand, 'stump': stump_hand, 'strawberry': strawberry_hand,
    'star': star_hand, 'spade': spade_hand, 'pumpkin': pumpkin_hand, 'log': log_hand,
    'hedgehog': hedgehog_hand, 'camp': camp_hand, 'butterfly': butterfly_hand,
    'grapes': lambda p, rng: cluster_hand(p, rng, 'grapes'),
    'raspberry': lambda p, rng: cluster_hand(p, rng, 'raspberry'),
    'heron': lambda p, rng: bird_hand(p, rng, heron=True),
}


def draw_hand(subject: str, rng: random.Random, tilt: float = 6, variant: int | None = None) -> Pen:
    """Draw a new hand of a subject from one random stream. For the original
    additions, variant keeps the A or B design of the drawing it stands in for."""
    number = rng.randrange(1_000_000, 2**31)
    pen = Pen(number, fast=True)
    pen.frame, pen.stroke_scale = hand_frame(rng, tilt)
    if subject in SUBJECT_HANDS:
        SUBJECT_HANDS[subject](pen, rng)
    elif subject in ADDITION_HANDS:
        options = [o for o in ADDITION_HANDS[subject] if variant is None or o[1] == variant] or ADDITION_HANDS[subject]
        drawer, design = rng.choice(options)
        drawer(pen, design)
    else:
        draw_subject(pen, subject, number)
    return pen
