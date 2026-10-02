"""HEIC photos are converted to JPEG on import, keeping their GPS tags and standing upright."""

import json

import pytest

pytest.importorskip("pillow_heif")

import pillow_heif  # noqa: E402
from PIL import Image  # noqa: E402

from services.cli.image_commands import run_image_action  # noqa: E402
from services.imageconvert import HeifUnavailable, convert_images, convert_to_jpeg, is_heif  # noqa: E402

pillow_heif.register_heif_opener()

GPS_IFD = 0x8825


def _dms(value):
    degrees = int(value)
    minutes = int((value - degrees) * 60)
    seconds = round(((value - degrees) * 60 - minutes) * 60, 2)
    return (float(degrees), float(minutes), seconds)


def _exif(lat=33.6679, lng=135.3436, orientation=1):
    exif = Image.Exif()
    exif[0x0112] = orientation
    gps = exif.get_ifd(GPS_IFD)
    gps[1], gps[2] = "N", _dms(lat)
    gps[3], gps[4] = "E", _dms(lng)
    return exif


def _heic(path, size=(40, 30), orientation=1, with_gps=True):
    image = Image.new("RGB", size, (200, 80, 40))
    image.save(path, format="HEIF", exif=(_exif(orientation=orientation) if with_gps else Image.Exif()).tobytes())
    return path


def _degrees(dms):
    d, m, sec = (float(x) for x in dms)
    return d + m / 60 + sec / 3600


def test_is_heif_matches_both_extensions_in_any_case():
    assert is_heif("a.HEIC") and is_heif("b.heif") and not is_heif("c.jpg") and not is_heif("d.png")


def test_a_heic_photo_becomes_a_jpeg_with_its_gps(tmp_path):
    src = _heic(tmp_path / "IMG_0001.HEIC")
    out = convert_to_jpeg(src, tmp_path / "out")
    assert out.name == "IMG_0001.jpg"
    with Image.open(out) as jpeg:
        assert jpeg.format == "JPEG" and jpeg.size == (40, 30)
        gps = jpeg.getexif().get_ifd(GPS_IFD)
    assert gps[1] == "N" and gps[3] == "E"
    assert _degrees(gps[2]) == pytest.approx(33.6679, abs=0.01)
    assert _degrees(gps[4]) == pytest.approx(135.3436, abs=0.01)


def test_a_photo_taken_sideways_is_turned_upright_once(tmp_path):
    src = _heic(tmp_path / "side.heic", size=(40, 30), orientation=6)
    with Image.open(convert_to_jpeg(src, tmp_path / "out")) as jpeg:
        assert jpeg.size == (30, 40)
        assert jpeg.getexif().get(0x0112, 1) == 1


def test_a_name_already_taken_is_not_overwritten(tmp_path):
    src = _heic(tmp_path / "same.heic")
    first = convert_to_jpeg(src, tmp_path / "out")
    second = convert_to_jpeg(src, tmp_path / "out")
    assert first != second and first.exists() and second.exists()


def test_only_heic_files_are_converted_and_a_bad_one_does_not_stop_the_rest(tmp_path):
    good = _heic(tmp_path / "good.heic")
    bad = tmp_path / "broken.heic"
    bad.write_bytes(b"not a photo")
    jpg = tmp_path / "plain.jpg"
    Image.new("RGB", (4, 4)).save(jpg)
    result = convert_images([str(good), str(bad), str(jpg)], tmp_path / "out")
    assert list(result["images"]) == [str(good)]
    assert list(result["failed"]) == [str(bad)]


def test_the_sidecar_action_returns_one_json_reply(tmp_path):
    src = _heic(tmp_path / "a.heic")
    reply = run_image_action("convert_images", {"paths": [str(src)], "out_dir": str(tmp_path / "out")})
    assert reply["success"] is True
    assert json.loads(json.dumps(reply))["images"][str(src)].endswith("a.jpg")


def test_missing_fields_are_reported(tmp_path):
    assert run_image_action("convert_images", {"paths": []}) == {"success": False, "error": "Missing field: out_dir"}


def test_a_missing_pillow_heif_says_how_to_install_it(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "pillow_heif":
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(HeifUnavailable, match="pip install pillow-heif"):
        convert_to_jpeg(tmp_path / "x.heic", tmp_path / "out")
    reply = run_image_action("convert_images", {"paths": [str(tmp_path / "x.heic")], "out_dir": str(tmp_path / "out")})
    assert reply["success"] is False and reply["missing_package"] == "pillow-heif"
