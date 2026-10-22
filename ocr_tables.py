"""Read a ruled header/value table without merging wrapped column headings."""
from collections import Counter
from PIL import Image, ImageOps


def _runs(items, gap=1):
    groups = []
    for value in items:
        if not groups or value - groups[-1][-1] > gap:
            groups.append([value])
        else:
            groups[-1].append(value)
    return groups


def detect_header_grid(image):
    """Return the top grid's measured rules, never fixed screen coordinates."""
    width, height = image.size
    pixels = image.load()
    bands = []
    colors = {}
    for y in range(min(height // 3, 350)):
        color, count = Counter(pixels[x, y] for x in range(width)).most_common(1)[0]
        if count > width * .75 and 140 <= min(color) and max(color) < 245:
            colors[y] = color
            bands.append(y)
    for band in _runs(bands):
        split = band[0]
        if split < 8:
            continue
        color = colors[split]
        following = [y for y in bands if y > band[-1] + 5 and colors[y] == color]
        if not following:
            continue
        bottom = following[0]
        if bottom < split + 10:
            continue
        vertical = [x for x in range(width) if sum(pixels[x, y] == color for y in range(bottom)) >= bottom * .65]
        columns = _runs(vertical)
        if len(columns) < 6:
            continue
        extent = [x for x in range(width) if pixels[x, split] == color]
        left, right = min(extent), max(extent) + 1
        rules = [round(sum(group)/len(group)) for group in columns]
        if rules[0] - left > 3:
            rules.insert(0, left)
        if right - rules[-1] > 3:
            rules.append(right)
        if min(b-a for a,b in zip(rules,rules[1:])) < 5:
            continue
        return tuple(rules), split, band[-1] + 1, bottom
    return None


def read_header_grid(image, grid, engine, language, scale, support_words):
    import pyocr.builders
    from ocr_core import OCRTable, OCRTableCell, OCRWord

    rules, header_bottom, value_top, bottom = grid

    def read(box, header=False):
        left, top, right, end = box
        crop = image.crop(box).convert('L')
        # Grid rules are pale; dark text survives without coloring artifacts.
        binary = crop.point(lambda pixel: 0 if pixel < 170 else 255)
        data = binary.load()
        rows = []
        spans = {}
        for y in range(binary.height):
            ink = [x for x in range(binary.width) if data[x,y] == 0]
            if ink:
                rows.append(y)
                spans[y] = (min(ink), max(ink)+1)
        if not rows:
            return ()
        bands = _runs(rows, gap=2)
        line_boxes = [(min(spans[y][0] for y in band), band[0], max(spans[y][1] for y in band), band[-1]+1) for band in bands]
        if header:
            line_boxes = [(0, 0, binary.width, binary.height)]
        else:
            widest = max(x2-x1 for x1,y1,x2,y2 in line_boxes)
            # Exclude tiny link/decorative marks above a full-width data line.
            line_boxes = [b for b in line_boxes if b[2]-b[0] >= widest * .25]
        words = []
        for x1,y1,x2,y2 in line_boxes:
            # Keep antialiased glyph edges and breathing room for tiny characters.
            x1, y1 = max(0, x1-2), max(0, y1-2)
            x2, y2 = min(crop.width, x2+2), min(crop.height, y2+2)
            area = crop.crop((x1,y1,x2,y2))
            factor = max(scale, 4)
            area = area.resize((area.width*factor, area.height*factor), Image.Resampling.LANCZOS)
            border = 24
            area = ImageOps.expand(area, border=border, fill='white')
            boxes = engine.image_to_string(area, lang=language, builder=pyocr.builders.WordBoxBuilder(tesseract_layout=6 if header else 7))
            line_words = []
            for word in boxes:
                (wx1,wy1),(wx2,wy2) = word.position
                bbox = (round((left+x1+(wx1-border)/factor)*scale), round((top+y1+(wy1-border)/factor)*scale),
                        round((left+x1+(wx2-border)/factor)*scale), round((top+y1+(wy2-border)/factor)*scale))
                confidence = max(0., min(100., float(word.confidence)))
                for support in support_words:
                    cx, cy = (support.bbox[0]+support.bbox[2])/2, (support.bbox[1]+support.bbox[3])/2
                    if support.content == word.content and bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]:
                        confidence = max(confidence, support.confidence)
                if word.content.strip():
                    line_words.append(OCRWord(word.content, bbox, confidence))
            if not header and line_words:
                # A full-page read can recognize a tiny glyph better than an
                # isolated cell. Reconcile only evidence from the same ink line.
                support = tuple(w for w in support_words
                                if (left+x1)*scale <= (w.bbox[0]+w.bbox[2])/2 <= (left+x2)*scale
                                and (top+y1)*scale <= (w.bbox[1]+w.bbox[3])/2 <= (top+y2)*scale)
                if support and min(w.confidence for w in support) >= 80 and min(w.confidence for w in support) > min(w.confidence for w in line_words):
                    line_words = list(support)
            words.extend(line_words)
            area.close()
        crop.close()
        binary.close()
        return tuple(words)

    cells = tuple(OCRTableCell(read((a+1,0,b-1,header_bottom), header=True),
                               read((a+1,value_top,b-1,bottom)))
                  for a,b in zip(rules,rules[1:]))
    return OCRTable(cells, (rules[0]*scale,0,rules[-1]*scale,bottom*scale))
