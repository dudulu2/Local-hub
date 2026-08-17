from pathlib import Path
from PIL import Image, ImageDraw

out = Path("build_assets/localhub.ico")
out.parent.mkdir(parents=True, exist_ok=True)

image = Image.new("RGBA", (256, 256), (12, 12, 13, 255))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((10, 10, 246, 246), radius=54, fill=(255, 151, 0, 255))
draw.rounded_rectangle((38, 38, 218, 218), radius=40, fill=(18, 18, 20, 255))
draw.polygon(((104, 77), (104, 179), (183, 128)), fill=(255, 151, 0, 255))

image.save(
    out,
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print(out)
