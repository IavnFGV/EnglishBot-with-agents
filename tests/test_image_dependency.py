from io import BytesIO

from PIL import Image, __version__
import pytest


def test_pillow_uses_security_patched_major():
    assert int(__version__.split(".")[0]) >= 13


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "TIFF"])
def test_image_thumbnail_roundtrip(image_format):
    source = BytesIO()
    with Image.new("RGB", (1200, 1100), color=(40, 80, 120)) as image:
        image.save(source, format=image_format)
    source.seek(0)
    with Image.open(source) as image:
        image.thumbnail((256, 256))
        image.load()
        assert 0 < image.width <= 256
        assert 0 < image.height <= 256
        output = BytesIO()
        image.save(output, format="PNG")
        assert output.getvalue().startswith(b"\x89PNG\r\n\x1a\n")
