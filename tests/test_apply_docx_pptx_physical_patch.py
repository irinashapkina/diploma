from __future__ import annotations

from pathlib import Path
import zipfile

from app.services.review_pdf_apply_service import _replace_text_in_xml_bytes, _rewrite_zip_xml_text, _rewrite_zip_xml_text_any


def test_replace_text_in_docx_xml_bytes() -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Java (актуальная версия 21)</w:t></w:r></w:p></w:body></w:document>"
    ).encode("utf-8")
    updated, replaced = _replace_text_in_xml_bytes(xml, targets=["Java (актуальная версия 21)"], replacement="Java (актуальная версия 26)")
    assert replaced is True
    assert "26" in updated.decode("utf-8")


def test_rewrite_zip_docx_entry(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "updated.docx"
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Java (актуальная версия 21)</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr("word/document.xml", xml)
    replaced = _rewrite_zip_xml_text(
        source_zip=source,
        output_zip=output,
        entry_name="word/document.xml",
        targets=["Java (актуальная версия 21)"],
        replacement="Java (актуальная версия 26)",
    )
    assert replaced is True
    assert output.exists()
    with zipfile.ZipFile(output, "r") as zf:
        payload = zf.read("word/document.xml").decode("utf-8")
    assert "26" in payload


def test_rewrite_zip_pptx_any_slide(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    output = tmp_path / "updated.pptx"
    slide = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Java (актуальная версия 21)</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>"
        "</p:sld>"
    )
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", slide)
    replaced = _rewrite_zip_xml_text_any(
        source_zip=source,
        output_zip=output,
        entry_pattern=r"^ppt/slides/slide\d+\.xml$",
        targets=["Java (актуальная версия 21)"],
        replacement="Java (актуальная версия 26)",
    )
    assert replaced is True
    assert output.exists()
    with zipfile.ZipFile(output, "r") as zf:
        payload = zf.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "26" in payload
