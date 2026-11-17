from pathlib import Path
from zipfile import ZipFile

import pytest

from document_inspection import inspect_docx


def package(path: Path, body: str, extras: dict[str, bytes] | None = None) -> None:
    with ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
            f"<w:body>{body}</w:body></w:document>"))
        for name, data in (extras or {}).items():
            z.writestr(name, data)


def test_inventory_preserves_original_and_covers_opaque_parts(tmp_path: Path) -> None:
    path = tmp_path / "sample.docx"
    package(path, '<w:p><w:r><w:t>PRIVATE_SENTINEL</w:t></w:r></w:p>'
            '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:left="1134"/><w:titlePg/></w:sectPr>', {
                "word/header1.xml": b'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:txbxContent><w:p><w:r><w:t>Stamp</w:t></w:r></w:p></w:txbxContent></w:hdr>',
                "word/embeddings/formula.bin": b"opaque object",
                "word/media/diagram.emf": b"opaque image",
                "word/_rels/document.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship TargetMode="External" Target="https://invalid.example"/></Relationships>'})
    original = path.read_bytes()
    result = inspect_docx(path)
    assert path.read_bytes() == original
    assert result.body_paragraphs == result.textboxes == result.embedded_objects == result.image_parts == 1
    assert result.external_relationships == 1
    assert result.sections[0].left_mm == 20.002
    assert result.sections[0].right_mm is None
    assert result.sections[0].different_first_page
    assert not result.conformance_assessed
    assert "PRIVATE_SENTINEL" not in repr(result)


def test_alternate_content_counted_once_but_both_branches_hashed(tmp_path: Path) -> None:
    a, b = tmp_path / "a.docx", tmp_path / "b.docx"
    body = '<mc:AlternateContent><mc:Choice><w:tbl/></mc:Choice>'
    package(a, body + '<mc:Fallback><w:tbl/><w:p><w:r><w:t>A</w:t></w:r></w:p></mc:Fallback></mc:AlternateContent>')
    package(b, body + '<mc:Fallback><w:tbl/><w:p><w:r><w:t>B</w:t></w:r></w:p></mc:Fallback></mc:AlternateContent>')
    ra, rb = inspect_docx(a), inspect_docx(b)
    assert ra.tables == rb.tables == 1
    assert ra.parts[1].text_sha256 != rb.parts[1].text_sha256


def test_legacy_doc_is_not_misread_as_docx(tmp_path: Path) -> None:
    path = tmp_path / "legacy.doc"
    path.write_bytes(b"legacy")
    with pytest.raises(ValueError, match="separately prepared converter"):
        inspect_docx(path)
    assert path.read_bytes() == b"legacy"


def test_duplicate_parts_and_entity_xml_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.docx"
    package(path, "")
    with pytest.warns(UserWarning), ZipFile(path, "a") as z:
        z.writestr("word/document.xml", "<different/>")
    with pytest.raises(ValueError, match="Duplicate"):
        inspect_docx(path)
    package(path, "", {"word/custom.xml": b'<!DOCTYPE x [<!ENTITY y "x">]><x>&y;</x>'})
    with pytest.raises(ValueError, match="DTD/entity"):
        inspect_docx(path)
    package(path, "", {"word/custom.xml": '<!DOCTYPE x [<!ENTITY y "x">]><x>&y;</x>'.encode("utf-16")})
    with pytest.raises(ValueError, match="UTF-16/32"):
        inspect_docx(path)
