from PIL import Image, ImageOps
import pyocr.builders
from ocr_core import get_ocr_engine

im=Image.open('.superpowers/sdd/automatic-rda-upload/reported_rda_capture.png').convert('RGB')
engine=get_ocr_engine()
for name,box in [('type',(62,45,94,90)),('revenue',(660,66,762,82)),('pickup',(500,180,520,200))]:
    for scale in (3,4,5):
        crop=im.crop(box)
        crop=crop.resize((crop.width*scale,crop.height*scale),Image.Resampling.LANCZOS)
        # Purple and black characters become black; pale grid/background stays white.
        crop=crop.convert('L').point(lambda v: 0 if v<155 else 255)
        crop=ImageOps.expand(crop,border=24,fill='white')
        for psm in (6,7,10,13):
            words=engine.image_to_string(crop,lang='eng',builder=pyocr.builders.WordBoxBuilder(tesseract_layout=psm))
            print(name,scale,psm,[(w.content,round(w.confidence)) for w in words],flush=True)
