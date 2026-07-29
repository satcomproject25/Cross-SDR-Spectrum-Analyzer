from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "tmp" / "pdfs"
pages = sorted(SOURCE_DIR.glob("algorithms-final-page-*.png"))
if not pages:
    raise SystemExit("No rendered PDF pages found")

thumb_width = 420
margin = 18
label_height = 24
columns = 2
rows_per_sheet = 2
pages_per_sheet = columns * rows_per_sheet

for sheet_index in range(0, len(pages), pages_per_sheet):
    group = pages[sheet_index : sheet_index + pages_per_sheet]
    thumbs = []
    for page_number, page_path in enumerate(group, start=sheet_index + 1):
        image = Image.open(page_path).convert("RGB")
        thumb_height = round(image.height * thumb_width / image.width)
        image = image.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        thumbs.append((page_number, image))

    cell_height = max(image.height for _, image in thumbs) + label_height
    sheet = Image.new(
        "RGB",
        (
            columns * thumb_width + (columns + 1) * margin,
            rows_per_sheet * cell_height + (rows_per_sheet + 1) * margin,
        ),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for position, (page_number, image) in enumerate(thumbs):
        row, column = divmod(position, columns)
        x = margin + column * (thumb_width + margin)
        y = margin + row * (cell_height + margin)
        draw.text((x, y), f"Page {page_number}", fill="#1D2733")
        sheet.paste(image, (x, y + label_height))
        draw.rectangle(
            (
                x,
                y + label_height,
                x + image.width - 1,
                y + label_height + image.height - 1,
            ),
            outline="#AAB5BC",
            width=1,
        )

    output = SOURCE_DIR / f"contact-sheet-{sheet_index // pages_per_sheet + 1}.png"
    sheet.save(output, quality=92)
    print(output)
