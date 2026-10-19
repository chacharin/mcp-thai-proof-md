"""The guard rails: which corrections from the model are accepted or rejected."""
import re

from app.config import DEFAULT_PROTECTED_REGEX
from app.proofread import judge, suspect_count

P = re.compile(DEFAULT_PROTECTED_REGEX)


def test_real_spelling_fix_is_accepted():
    ok, why = judge("รายงานวิเคราะหปจจัยขบเคลอน", "รายงานวิเคราะห์ปัจจัยขับเคลื่อน", 0.5, P)
    assert ok and why == "fixed"


def test_unchanged_line_is_same():
    assert judge("ข้อความเดิม", "ข้อความเดิม", 0.5, P) == (True, "same")


def test_deleting_a_line_is_rejected():
    ok, why = judge("มีข้อความ", "   ", 0.5, P)
    assert not ok and why == "บรรทัดถูกลบ"


def test_number_change_is_rejected():
    assert not judge("งบประมาณ 120 ล้านบาท", "งบประมาณ 210 ล้านบาท", 0.5, P)[0]


def test_protected_code_change_is_rejected():
    assert not judge("ตามรายงาน [S2] ระบุว่า", "ตามรายงาน [S3] ระบุว่า", 0.5, P)[0]


def test_url_and_english_word_changes_are_rejected():
    assert not judge("ดู https://a.example/x ด้วย", "ดู https://b.example/x ด้วย", 0.5, P)[0]
    assert not judge("ใช้ Gemma ตรวจ", "ใช้ Llama ตรวจ", 0.5, P)[0]


def test_markdown_structure_change_is_rejected():
    assert not judge("| ชื่อ | ค่า |", "| ชื่อ ค่า |", 0.5, P)[0]          # table pipes
    assert not judge("- รายการแรก", "รายการแรก", 0.5, P)[0]             # list prefix
    assert not judge("**สำคัญ** มาก", "สำคัญ มาก", 0.5, P)[0]           # bold markers


def test_rewriting_too_much_is_rejected():
    ok, why = judge("ฝนตกหนักทางภาคใต้", "ภาคเหนือมีอากาศหนาวเย็นตลอดสัปดาห์", 0.5, P)
    assert not ok and why == "เปลี่ยนมากเกินไป"


def test_custom_protected_regex():
    # a Thai code with no digits or English: only PROTECTED_REGEX can catch the change
    old, new = "ชั้นความลับ ลับ-กข ห้ามแก้", "ชั้นความลับ ลับ-กค ห้ามแก้"
    assert judge(old, new, 0.5, None)[0]                                  # without the rule: accepted
    assert not judge(old, new, 0.5, re.compile(r"ลับ-[ก-ฮ]+"))[0]          # with the rule: rejected


def test_no_protected_regex_still_guards_numbers():
    assert not judge("ข้อ [S1] ที่ 5", "ข้อ [S1] ที่ 6", 0.5, None)[0]


def test_suspect_count_finds_typical_damage():
    assert suspect_count("ที่่") >= 1                # the same tone mark twice
    assert suspect_count("วันantry") >= 1           # English stuck inside Thai
    assert suspect_count("ข้อความปกติที่ถูกต้อง") == 0
