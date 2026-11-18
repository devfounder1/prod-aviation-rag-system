from io import BytesIO
from xml.etree import ElementTree as E
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document

from stamp_review import measure_header,review_stamps,A,WP,WPG,WPS,EMU


def header(scale: float=1,rotation: bool=False) -> E.Element:
    # A known synthetic group: 185 x 287 mm frame, 40 mm main block.
    def rect(x: int,y: int,w: int,h: int,text: str='',geom: str='rect') -> str:
        return f'<wps:wsp><wps:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="{geom}"/><a:ln w="18000"/></wps:spPr><wps:txbx><w:txbxContent><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:txbxContent></wps:txbx></wps:wsp>'
    content=rect(0,0,6660000,10332000)+rect(0,8892000,6660000,0,geom='line')+rect(3000000,9500000,500000,200000,'SYNTHETIC ТУ')
    rot=' rot="5400000"' if rotation else ''
    return E.fromstring(f'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:wp="{WP[1:-1]}" xmlns:a="{A[1:-1]}" xmlns:wps="{WPS[1:-1]}" xmlns:wpg="{WPG[1:-1]}"><wp:anchor><wp:extent cx="{round(6660000*scale)}" cy="{round(10332000*scale)}"/><a:graphic><a:graphicData><wpg:wgp><wpg:grpSpPr><a:xfrm{rot}><a:off x="0" y="0"/><a:ext cx="6660000" cy="10332000"/><a:chOff x="0" y="0"/><a:chExt cx="6660000" cy="10332000"/></a:xfrm></wpg:grpSpPr>{content}</wpg:wgp></a:graphicData></a:graphic></wp:anchor></w:hdr>')


def test_group_scale_is_measured_without_modifying_artwork() -> None:
    root=header(1.01);before=E.tostring(root);rows=measure_header(root)
    assert len(rows)==1 and rows[0].width_mm==pytest.approx(186.85,abs=.001)
    assert rows[0].stamp_height_mm==pytest.approx(40.4,abs=.001)
    assert rows[0].candidate_form=='похожа на 2'
    assert rows[0].unmeasured_groups==0
    assert E.tostring(root)==before


def test_rotated_unknown_geometry_is_not_guessed() -> None:
    assert measure_header(header(rotation=True))==()


def test_ambiguous_frame_is_not_selected_by_first_match() -> None:
    root=header();group=root.find('.//'+WPG+'wgp');shape=group.find(WPS+'wsp')
    group.append(E.fromstring(E.tostring(shape)))
    assert measure_header(root)==()


def test_incomplete_child_group_is_disclosed_as_partial_measurement() -> None:
    root=header();group=root.find('.//'+WPG+'wgp')
    group.append(E.fromstring(f'<wpg:grpSp xmlns:wpg="{WPG[1:-1]}" xmlns:a="{A[1:-1]}"><wpg:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1" cy="1"/></a:xfrm></wpg:grpSpPr><a:ln w="18000"/></wpg:grpSp>'))
    row=measure_header(root)[0]
    assert row.width_mm==185 and row.unmeasured_groups==1


def test_review_does_not_create_missing_stamps_or_requisites() -> None:
    doc=Document();doc.add_heading('Requirements',1);out=BytesIO();doc.save(out)
    raw=out.getvalue();rows=review_stamps(raw,'print_framed')
    assert rows[0].check_id=='stamp-no-supported-headers'
    assert all(c.status!='выполнено' for c in rows)
    assert raw==out.getvalue()
