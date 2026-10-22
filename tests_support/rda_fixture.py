"""Hand-positioned RDA screen fixture; never imported by application code."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SUMMARY = [
    ("lob", "LOB", 65), ("co", "CO", 45), ("transaction_type", "Trans Type", 80),
    ("ship_date", "Ship Dt", 120), ("tendered_date", "Tendered Dt", 120),
    ("revenue_date", "Revenue Dt", 120), ("customs_entry_date", "Customs Entry Dt", 125),
    ("origin_station", "Origin Station", 100), ("destination_station", "Dest Station", 100),
    ("payor_code", "Payor", 65), ("summary_invoice_number", "Invoice #", 105),
    ("summary_invoice_date", "Invoice Dt", 120), ("summary_bill_to_account_number", "Bill To Acct #", 140),
    ("bill_to_customer_name", "Bill To Cust Name", 200), ("revenue_item_id", "Rev Item Id", 250),
    ("cdo_required_date", "CDO Req Dt", 120), ("device_flag", "Device", 90),
    ("ors_flag", "ORS Flag", 70), ("stage", "Stage", 120),
]
SECTIONS = [
    ("Transaction Information", 0, 150, [
        ("net_amount", "Net Amt:", 15, 55), ("balance_due", "Balance Due:", 485, 55),
        ("transaction_ship_date", "Ship Date:", 950, 55), ("transaction_tendered_date", "Tendered Date:", 1400, 55),
        ("transaction_revenue_date", "Revenue Date:", 15, 105), ("transaction_cdo_required_date", "CDO Req Date:", 485, 105),
        ("meter_number", "Meter Number:", 950, 105), ("billing_cycle", "Billing Cycle:", 1400, 105),
        ("form_id", "Form ID:", 15, 155), ("group_id", "Group ID:", 485, 155),
        ("pickup_type", "Pickup Type:", 950, 155), ("master_tracking_number", "Master Trkng #:", 1400, 155),
    ]),
    ("Invoice Information", 0, 360, [
        ("invoice_number", "Invoice #:", 15, 55), ("invoice_date", "Invoice Date:", 485, 55),
        ("invoice_age", "Invoice Age:", 950, 55), ("invoice_amount", "Invoice Amount:", 1400, 55),
        ("invoice_balance", "Invoice Balance:", 15, 105),
    ]),
    ("Shipper Information", 0, 520, []), ("Recipient Information", 680, 520, []),
    ("Bill To Information", 0, 910, []),
    ("Payment", 680, 910, [
        ("payment_payor", "Payor:", 15, 55), ("payment_method", "Method:", 15, 100),
        ("payment_source", "Payment Source:", 15, 145), ("ground_sort_key", "Grnd Sort Key:", 15, 190),
        ("bill_characteristics", "Bill Characteristics:", 15, 235),
        ("bill_to_legal_entity", "Bill To Legal Entity:", 15, 280), ("bill_to_station", "Bill To Station:", 15, 325),
    ]),
]
PARTY = [("name", "Name:"), ("account_number", "Acct #:"), ("company", "Company:"),
         ("address_line_1", "Address:"), ("address_line_2", "Address 2:"), ("city", "City:"),
         ("state", "State:"), ("zip_code", "Zip:"), ("country", "Cntry/Terr:"), ("phone_number", "Phone #:")]


def layout(values):
    """Yield literal text placements independent of the production mapper."""
    x = 10
    for key, label, width in SUMMARY:
        # The real grid wraps cells. Keep this single-line fixture free of overlaps.
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 18)
        label_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 18)
        width = max(width, round(label_font.getlength(label)) + 22,
                    round(font.getlength(str(values.get(key, "")))) + 22)
        yield label, x + 5, 12, True
        if str(values.get(key, "")):
            yield str(values[key]), x + 5, 85, False
        x += width
    for title, sx, sy, cells in SECTIONS:
        yield title, sx + 10, sy, True
        if title.endswith("Information") and title.split()[0] in ("Shipper", "Recipient", "Bill"):
            prefix = {"Shipper Information": "shipper", "Recipient Information": "recipient", "Bill To Information": "bill_to"}[title]
            cells = [(prefix + "_" + suffix, label,
                      255 if suffix == 'zip_code' else 420 if suffix == 'country' else 15,
                      240 if suffix in ('state', 'zip_code', 'country') else 272 if suffix == 'phone_number' else 48 + index * 32)
                     for index, (suffix, label) in enumerate(PARTY)]
        for key, label, dx, dy in cells:
            yield label, sx + dx, sy + dy, True
            value = values.get(key, "")
            if key == "net_amount" and value != "":
                value = str(value) + " " + str(values.get("currency", ""))
            if value != "":
                offset = 210 if title in ("Transaction Information", "Invoice Information", "Payment") else 160
                if key.endswith('_state'):
                    offset = 100
                elif key.endswith('_zip_code'):
                    offset = 60
                elif key.endswith('_country'):
                    offset = 120
                yield str(value), sx + dx + offset, sy + dy, False


def render_rda_fixture(path: Path, values: dict[str, object], scale: int = 1) -> None:
    image = Image.new("RGB", (4000, 1310), "white")
    draw = ImageDraw.Draw(image)
    regular = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 18)
    bold = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 18)
    for text, x, y, is_label in layout(values):
        draw.text((x, y), text, font=bold if is_label else regular, fill="black")
    if scale != 1:
        image = image.resize((image.width * scale, image.height * scale))
    image.save(path)


def word_document(values, scale=1, shift=(0, 0)):
    from ocr_core import OCRDocument, OCRWord
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 18)
    words = []
    for text, x, y, _ in layout(values):
        offset = 0
        for token in text.split():
            width = round(font.getlength(token))
            words.append(OCRWord(token, ((x + offset + shift[0]) * scale, (y + shift[1]) * scale,
                                         (x + offset + width + shift[0]) * scale, (y + 22 + shift[1]) * scale), 98.0))
            offset += width + 6
    return OCRDocument("\n".join(t for t, *_ in layout(values)), tuple(words), (4000 + shift[0]) * scale, (1310 + shift[1]) * scale)
