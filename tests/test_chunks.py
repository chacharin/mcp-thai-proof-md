"""How a document is cut into chunks, the prompt built for each, and how model output is cleaned."""
from app.proofread import build_prompt, clean_output, make_chunks

DOC = """# รายงานสถานการณ์
บทนำภาษาไทย
## ส่วนที่ 1
เนื้อหาส่วนแรก
English only line
```
โค้ดภาษาไทยในบล็อก
```
## ส่วนที่ 2
เนื้อหาส่วนที่สอง""".split("\n")


def test_title_and_heading_path():
    title, chunks = make_chunks(DOC, 3500)
    assert title == "รายงานสถานการณ์"
    assert [c.headings for c in chunks] == [["รายงานสถานการณ์"], ["รายงานสถานการณ์", "ส่วนที่ 1"],
                                            ["รายงานสถานการณ์", "ส่วนที่ 2"]]


def test_code_blocks_and_lines_without_thai_are_never_sent():
    _, chunks = make_chunks(DOC, 3500)
    sent = [DOC[i] for c in chunks for i in c.idx]
    assert "English only line" not in sent
    assert "โค้ดภาษาไทยในบล็อก" not in sent


def test_long_section_is_split_by_chunk_chars():
    lines = ["# หัวข้อ"] + ["ประโยคภาษาไทยยาวพอสมควร"] * 10
    _, chunks = make_chunks(lines, 60)
    assert len(chunks) > 2
    assert all(sum(len(lines[i]) for i in c.idx) <= 60 or len(c.idx) == 1 for c in chunks)


def test_prompt_contains_context_and_exact_lines():
    title, chunks = make_chunks(DOC, 3500)
    p = build_prompt(DOC, chunks[1], title, 3)
    assert "ชื่อเอกสาร: รายงานสถานการณ์" in p
    assert "หัวข้อ: รายงานสถานการณ์ > ส่วนที่ 1" in p
    assert f"คืนเฉพาะส่วนนี้ {len(chunks[1].idx)} บรรทัด" in p
    assert p.rstrip().endswith(">>>")


def test_clean_output_strips_reasoning_fences_and_markers():
    raw = "<think>คิดก่อน</think>\n```\n<<<\nบรรทัดหนึ่ง\nบรรทัดสอง\n>>>\n```"
    assert clean_output(raw) == ["บรรทัดหนึ่ง", "บรรทัดสอง"]
