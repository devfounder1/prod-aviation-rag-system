"""Read-only inventory before a layout-preserving DOCX transformation.

This module does not format documents, execute embedded objects, resolve external
relationships, or certify GOST compliance. Reports contain hashes and structure,
not document prose. Binary .doc import is deliberately a separate setup step.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_PARTS = 4096


@dataclass(frozen=True)
class PartEvidence:
    name: str
    size: int
    sha256: str
    text_sha256: str | None


@dataclass(frozen=True)
class SectionEvidence:
    width_mm: float | None
    height_mm: float | None
    left_mm: float | None
    right_mm: float | None
    top_mm: float | None
    bottom_mm: float | None
    different_first_page: bool
    has_page_borders: bool


@dataclass(frozen=True)
class DocumentEvidence:
    schema_version: int
    source_name: str
    source_sha256: str
    sections: tuple[SectionEvidence, ...]
    body_paragraphs: int
    tables: int
    textboxes: int
    native_equations: int
    image_parts: int
    embedded_objects: int
    fonts: tuple[str, ...]
    field_kinds: tuple[str, ...]
    external_relationships: int
    has_macros: bool
    parts: tuple[PartEvidence, ...]
    review_required: tuple[str, ...]
    conformance_assessed: bool = False


def _parse(data: bytes) -> ET.Element:
    # DOCX parts do not require a DTD; reject it rather than expand entities.
    # UTF-16/32 must not bypass the byte-level DTD check. This initial reader
    # deliberately accepts only XML without NUL bytes instead of transcoding it.
    if b"\x00" in data:
        raise ValueError("UTF-16/32 XML parts are not supported by this inventory")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("DTD/entity declarations are not supported in DOCX parts")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("Invalid XML in DOCX package") from exc


def _active(root: ET.Element) -> ET.Element:
    """Count one representation, preserving both representations in part hashes."""
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag == MC + "AlternateContent":
                choice = child.find(MC + "Choice")
                if choice is None:
                    choice = child.find(MC + "Fallback")
                position = list(parent).index(child)
                parent.remove(child)
                if choice is not None:
                    for item in reversed(list(choice)):
                        parent.insert(position, item)
    return root


def _mm(element: ET.Element | None, attr: str) -> float | None:
    value = element.get(W + attr) if element is not None else None
    if value is None:
        return None
    try:
        return round(int(value) * 25.4 / 1440, 3)
    except ValueError as exc:
        raise ValueError("Non-numeric section dimension") from exc


def inspect_docx(path: Path) -> DocumentEvidence:
    """Inventory OOXML without extracting files or changing the source."""
    if path.suffix.lower() != ".docx":
        raise ValueError("Expected DOCX. Binary DOC needs a separately prepared converter.")
    with path.open("rb") as stream:
        payload = stream.read(MAX_INPUT_BYTES + 1)
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("Document exceeds the inspection size limit")
    parts: list[PartEvidence] = []
    sections: list[SectionEvidence] = []
    fonts: set[str] = set()
    fields: set[str] = set()
    tables = textboxes = equations = paragraphs = external = images = objects = 0
    macros = False
    try:
        with ZipFile(BytesIO(payload)) as package:
            entries = package.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > MAX_PARTS or sum(e.file_size for e in entries) > MAX_EXPANDED_BYTES:
                raise ValueError("DOCX package exceeds the inspection limits")
            if len(names) != len(set(names)):
                raise ValueError("Duplicate package parts are ambiguous")
            if any(name.startswith('/') or '\\' in name or
                   any(part in {'', '.', '..'} for part in name.rstrip('/').split('/')) for name in names):
                raise ValueError("Non-canonical package part paths are ambiguous")
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise ValueError("Not a Word OOXML package")
            xml_total = 0
            for entry in entries:
                if entry.filename.endswith(('.xml', '.rels')):
                    xml_total += entry.file_size
                    if entry.file_size > 8 * 1024 * 1024 or xml_total > 24 * 1024 * 1024:
                        raise ValueError("XML parts exceed the inspection limits")
                data = package.read(entry)
                name = entry.filename
                text_hash: str | None = None
                if name.startswith("word/media/"):
                    images += 1
                if name.startswith("word/embeddings/"):
                    objects += 1
                if name.lower().endswith("vbaproject.bin"):
                    macros = True
                if name.endswith(".xml") or name.endswith(".rels"):
                    root = _parse(data)
                    # Cover body, tables, headers, footers, fields and textboxes.
                    # Hash each text node with its tag; do not publish its text.
                    nodes = [(node.tag, node.text or "") for node in root.iter()
                             if node.tag in {W + "t", W + "instrText", W + "delText"}]
                    text_hash = hashlib.sha256(json.dumps(nodes, ensure_ascii=False).encode()).hexdigest()
                    if name.endswith(".rels"):
                        external += sum(r.get("TargetMode") == "External"
                                        for r in root.findall(REL + "Relationship"))
                    root = _active(root)
                    if name.startswith("word/"):
                        tables += sum(1 for _ in root.iter(W + "tbl"))
                        textboxes += sum(1 for _ in root.iter(W + "txbxContent"))
                        equations += sum(1 for _ in root.iter(
                            "{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath"))
                        for font in root.iter(W + "rFonts"):
                            fonts.update(v for k, v in font.attrib.items()
                                         if k in {W + "ascii", W + "hAnsi", W + "eastAsia", W + "cs"})
                        instructions = [n.text or "" for n in root.iter(W + "instrText")]
                        instructions += [n.get(W + "instr", "") for n in root.iter(W + "fldSimple")]
                        fields.update(v.strip().split()[0].upper() for v in instructions if v.strip())
                    if name == "word/document.xml":
                        body = root.find(W + "body")
                        if body is None:
                            raise ValueError("Word document body is missing")
                        paragraphs = len(body.findall(W + "p"))
                        for section in body.iter(W + "sectPr"):
                            size, margin = section.find(W + "pgSz"), section.find(W + "pgMar")
                            sections.append(SectionEvidence(
                                _mm(size, "w"), _mm(size, "h"), _mm(margin, "left"),
                                _mm(margin, "right"), _mm(margin, "top"), _mm(margin, "bottom"),
                                section.find(W + "titlePg") is not None,
                                section.find(W + "pgBorders") is not None))
                parts.append(PartEvidence(name, len(data), hashlib.sha256(data).hexdigest(), text_hash))
    except BadZipFile as exc:
        raise ValueError("Not a valid DOCX ZIP package") from exc
    review = ["Rendered pages and normative applicability have not been checked by this inventory."]
    if textboxes:
        review.append("Textboxes may contain title blocks, frames or labels; preserve their layout and text.")
    if objects:
        review.append("Embedded objects need visual/manual review; do not execute or silently flatten them.")
    if fields:
        review.append("Field caches and page references need verification after any layout change.")
    if external:
        review.append("External relationships exist; they were not fetched or refreshed.")
    if macros:
        review.append("Macro content exists; it was not executed.")
    if any(not s.has_page_borders for s in sections):
        review.append("No page-border element does not prove a frame is absent; it can be a drawing/image.")
    return DocumentEvidence(1, path.name, hashlib.sha256(payload).hexdigest(), tuple(sections),
                            paragraphs, tables, textboxes, equations, images, objects,
                            tuple(sorted(fonts)), tuple(sorted(fields)), external, macros,
                            tuple(parts), tuple(review))


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only DOCX structural inventory; not a GOST certificate")
    parser.add_argument("document", type=Path)
    parser.add_argument("--output", type=Path, help="New JSON report; existing files are never overwritten")
    args = parser.parse_args()
    try:
        report = json.dumps(asdict(inspect_docx(args.document)), ensure_ascii=False, indent=2) + "\n"
        if args.output is not None:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(report)
            print(f"Inventory saved: {args.output}")
        else:
            print(report, end="")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Inspection failed: {exc}\n")


if __name__ == "__main__":
    main()
