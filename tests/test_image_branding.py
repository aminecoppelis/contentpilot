from io import BytesIO

from PIL import Image

from app.services.image_result import apply_brand_badge, calculate_macaron_position, parse_boolean


def test_apply_brand_badge_adds_visible_pixels_bottom_right():
    source = Image.new("RGB", (1000, 800), "white")
    raw = BytesIO()
    source.save(raw, format="PNG")

    branded, suffix, mime = apply_brand_badge(raw.getvalue(), ".png")

    result = Image.open(BytesIO(branded)).convert("RGB")
    assert result.size == (1000, 800)
    assert suffix == ".png"
    assert mime == "image/png"
    # Le centre reste intact, la zone réservée au macaron est modifiée.
    assert result.getpixel((500, 400)) == (255, 255, 255)
    assert result.getpixel((885, 685)) != (255, 255, 255)


def test_apply_brand_badge_preserves_jpeg_output_contract():
    source = Image.new("RGB", (640, 640), (20, 40, 60))
    raw = BytesIO()
    source.save(raw, format="JPEG")

    branded, suffix, mime = apply_brand_badge(raw.getvalue(), ".jpg")

    assert Image.open(BytesIO(branded)).format == "JPEG"
    assert suffix == ".jpg"
    assert mime == "image/jpeg"


def test_parse_boolean_handles_json_and_form_values():
    assert parse_boolean(True) is True
    assert parse_boolean("true") is True
    assert parse_boolean("false") is False
    assert parse_boolean("0") is False
    assert parse_boolean(None, default=True) is True


def test_calculate_macaron_position_supports_all_positions():
    expected = {
        "top-left": (10, 10),
        "top-right": (790, 10),
        "bottom-left": (10, 690),
        "bottom-right": (790, 690),
        "center": (400, 350),
    }
    for position, coordinates in expected.items():
        assert calculate_macaron_position(1000, 800, 200, 100, position, .0125) == coordinates
