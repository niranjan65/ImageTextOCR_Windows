from PIL import Image, ImageOps
import pyocr.builders
from ocr_core import get_ocr_engine

im = Image.open('.superpowers/sdd/automatic-rda-upload/reported_rda_capture.png').convert('RGB')
engine = get_ocr_engine()
cols = [3,37,60,95,158,221,285,337,382,425,457,498,538,601,658,763,793,831,858,908]
for index, (left, right) in enumerate(zip(cols, cols[1:])):
    cells = []
    for top, bottom in [(0,43), (45,90)]:
        crop = ImageOps.expand(im.crop((left+1,top,right-1,bottom)).resize(((right-left-2)*4,(bottom-top)*4)),border=20,fill='white')
        words = engine.image_to_string(crop,lang='eng',builder=pyocr.builders.WordBoxBuilder(tesseract_layout=6))
        cells.append([(w.content,round(w.confidence)) for w in words])
    print(index, cells, flush=True)
for factor in (3,4):
    body = im.crop((0,94,908,754)).resize((908*factor,660*factor))
    words = engine.image_to_string(body,lang='eng',builder=pyocr.builders.WordBoxBuilder(tesseract_layout=11))
    print('BODY',factor,[(w.content,round(w.confidence)) for w in words if w.position[0][1]<115*factor],flush=True)
