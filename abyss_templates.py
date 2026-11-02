"""Small local, position-constrained text/HUD templates, learned from actual MCP fixtures."""
from pathlib import Path
import json
from PIL import Image, ImageOps, ImageFilter, ImageChops, ImageStat
from abyss_core import Token


def glyph_mask(image):
    gray = ImageOps.autocontrast(image.convert('L').resize((112, 40), Image.Resampling.LANCZOS))
    return gray.point(lambda p: 255 if p >= 168 else 0)


def similarity(reference, candidate):
    r = sum(reference.histogram()[1:])
    c = sum(candidate.histogram()[1:])
    if not 45 < r < reference.width * reference.height * .80 or not 45 < c < candidate.width * candidate.height * .80:
        return 0.0
    rd, cd = reference.filter(ImageFilter.MaxFilter(3)), candidate.filter(ImageFilter.MaxFilter(3))
    a = sum(ImageChops.multiply(reference, cd).histogram()[1:]) / r
    b = sum(ImageChops.multiply(candidate, rd).histogram()[1:]) / c
    return (a+b)/2


class TemplateBank:
    def __init__(self, root):
        folder=Path(root)/'templates'
        self.entries=[]
        path=folder/'model.json'
        if not path.exists():
            return
        for data in json.loads(path.read_text(encoding='utf-8'))['entries']:
            data=dict(data)
            data['mask']=Image.open(folder/data['file']).convert('L')
            self.entries.append(data)

    def apply(self, image, observation):
        for entry in self.entries:
            a,b,c,d=entry['rect']
            box=(round(a*image.width),round(b*image.height),round(c*image.width),round(d*image.height))
            score=similarity(entry['mask'], glyph_mask(image.crop(box)))
            best_box=box
            threshold=entry.get('threshold',.92)
            if score < threshold:
                for dx in (-round(image.width*.010),-round(image.width*.005),0,round(image.width*.005),round(image.width*.010)):
                    for dy in (-round(image.height*.010),-round(image.height*.005),0,round(image.height*.005),round(image.height*.010)):
                        shifted=(box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy)
                        candidate=similarity(entry['mask'],glyph_mask(image.crop(shifted)))
                        if candidate>score:score,best_box=candidate,shifted
            box=best_box
            if score >= threshold:
                observation.tokens.append(Token(entry['text'],box[0],box[1],box[2]-box[0],box[3]-box[1],
                                                source='template:'+entry['name'],score=round(score,4)))
                observation.visuals.add(entry['name'])
        return observation
