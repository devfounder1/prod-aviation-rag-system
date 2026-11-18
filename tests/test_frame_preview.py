from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject,NameObject

from frame_preview import observe_frames,frame_warnings


def pdf_frame(width: float=185,stamp: float=40,duplicate: bool=False) -> bytes:
    pt=72/25.4;writer=PdfWriter();page=writer.add_blank_page(210*pt,297*pt)
    # Frame 20/5 mm from left/top with 287 mm height; 40 mm stamp below.
    data=f'0.5 w 0 G {20*pt} {5*pt} {width*pt} {287*pt} re S\n'
    data+=f'{20*pt} {5*pt} {width*pt} {stamp*pt} re S\n'
    if duplicate:data+=f'{21*pt} {5*pt} {width*pt} {287*pt} re S\n'
    stream=DecodedStreamObject();stream.set_data(data.encode());page[NameObject('/Contents')]=writer._add_object(stream)
    out=BytesIO();writer.write(out);return out.getvalue()


def test_actual_pdf_outline_measurements_include_stamp_without_modification() -> None:
    raw=pdf_frame(183.4);before=bytes(raw);row=observe_frames(raw)[0]
    assert row.width_mm==pytest.approx(183.4,abs=.001)
    assert row.stamp_height_mm==pytest.approx(40,abs=.001)
    assert raw==before and 'не заключение' in frame_warnings(raw)[0]


def test_ambiguous_frames_are_not_selected_by_first_match() -> None:
    assert observe_frames(pdf_frame(duplicate=True))==()


def test_full_page_form_is_not_classified_as_main_stamp() -> None:
    assert observe_frames(pdf_frame(stamp=54))[0].stamp_height_mm is None


def test_invalid_pdf_is_not_treated_as_an_unmeasured_valid_preview() -> None:
    with pytest.raises(ValueError):observe_frames(b'not pdf')
