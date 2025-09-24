from io import BytesIO
from zipfile import ZipFile
from PIL import Image

def png_bytes(w=2, h=2):
    im = Image.new("RGB", (w, h), (123, 222, 111))
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()

def make_zip(path, name_bytes_map):
    """name_bytes_map: dict of {filename_in_zip: bytes}"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as zf:
        for name, data in name_bytes_map.items():
            zf.writestr(name, data)
    return path
