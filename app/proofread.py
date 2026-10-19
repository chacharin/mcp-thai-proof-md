"""Thai spelling correction of Markdown text with an OpenAI-compatible LLM.

Context given to the model for every chunk (read-only, never returned):
  - the document title and the heading path of the section the chunk is in
  - CONTEXT_LINES lines before and after the chunk
Chunks follow the document: a new chunk starts at every heading and when CHUNK_CHARS is
reached; table rows and list items are never split across lines.

Safety (a corrected line that breaks a rule keeps its original text):
  - numbers, codes matching PROTECTED_REGEX (default [S1]-style citations), URLs, standalone
    English words, table pipes, Markdown line prefix (#, -, 1.) and ** count must be identical
  - the line must stay similar to the original (difflib ratio >= MIN_SIMILARITY)
  - if the model returns a different number of lines, the chunk is split in half and retried
Fenced code blocks and lines without Thai are never sent.
"""
from __future__ import annotations

import concurrent.futures as cf
import difflib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import Settings

THAI = re.compile(r"[฀-๿]")
_MARK = "ัิ-ฺ็"
_TONE = "่-์"
SUSPECT = [
    re.compile(rf"([{_MARK}{_TONE}])\1"),                                               # doubled mark
    re.compile(rf"[{_TONE}][{_MARK}]"),                                                 # tone before vowel
    re.compile(rf"(^|[^ก-ฮะ-ฺ็-๎])[{_MARK}{_TONE}]"),     # mark with no consonant
    re.compile(r"[ก-๎][A-Za-z]{2,}|[A-Za-z]{2,}[ัิ-ฺ็-๎]"),  # English inside Thai
    re.compile("�"),
    re.compile("[぀-ヿ㐀-䶿一-鿿가-힯]+"),                # Chinese/Japanese/Korean
    re.compile("(?<=[ก-๎]) (?=[ัิ-ฺ็-๎])"),        # space before a vowel/tone mark
]
HEADING = re.compile(r"^\s*(#{1,6})\s+(.*)$")


def suspect_count(text: str) -> int:
    return sum(len(p.findall(text)) for p in SUSPECT)


# ------------------------------------------------------------------ line rules
_NUM = re.compile(r"\d+(?:[.,:/]\d+)*")
_URL = re.compile(r"https?://\S+")
_ENG = re.compile(r"(?<![A-Za-z฀-๿])[A-Za-z][A-Za-z'\-]*(?![A-Za-z฀-๿])")
_PREFIX = re.compile(r"^(\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s?)?)")


def invariants(line: str, protected: re.Pattern | None = None) -> tuple:
    codes = sorted(protected.findall(line)) if protected else []
    return (sorted(_NUM.findall(line)), codes, sorted(_URL.findall(line)),
            sorted(_ENG.findall(line)), line.count("|"), _PREFIX.match(line).group(1).strip(), line.count("**"))


def judge(old: str, new: str, min_sim: float, protected: re.Pattern | None = None) -> tuple[bool, str]:
    if new == old:
        return True, "same"
    if old.strip() and not new.strip():
        return False, "LLM ลบข้อความในบรรทัดนี้ออก"
    if invariants(old, protected) != invariants(new, protected):
        return False, "ตัวเลข รหัส URL คำภาษาอังกฤษ หรือรูปแบบ Markdown เปลี่ยนไปจากต้นฉบับ"
    if difflib.SequenceMatcher(None, old, new).ratio() < min_sim:
        return False, "ข้อความเปลี่ยนไปจากต้นฉบับมากเกินไป"
    return True, "fixed"


# ------------------------------------------------------------------ chunking with context
@dataclass
class Chunk:
    idx: list[int]
    headings: list[str]


def make_chunks(lines: list[str], max_chars: int) -> tuple[str, list[Chunk]]:
    title = ""
    path: list[str] = []
    out: list[Chunk] = []
    cur: list[int] = []
    size = 0
    fenced = False

    def flush() -> None:
        nonlocal cur, size
        if cur:
            out.append(Chunk(cur, list(path)))
        cur, size = [], 0

    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            if not title and level == 1:
                title = m.group(2).strip()
            path = path[: level - 1] + [m.group(2).strip()]
        if not THAI.search(line):
            continue
        if cur and size + len(line) > max_chars:
            flush()
        cur.append(i)
        size += len(line) + 1
    flush()
    return title, out


def build_prompt(lines: list[str], ch: Chunk, title: str, ctx: int) -> str:
    first, last = ch.idx[0], ch.idx[-1]
    before = [ln for ln in lines[max(0, first - ctx):first] if ln.strip()]
    after = [ln for ln in lines[last + 1:last + 1 + ctx] if ln.strip()]
    parts = ["[บริบท — ใช้ประกอบการเดาคำเท่านั้น ห้ามแก้และห้ามคืน]"]
    if title:
        parts.append(f"ชื่อเอกสาร: {title}")
    if ch.headings:
        parts.append("หัวข้อ: " + " > ".join(ch.headings))
    if before:
        parts += ["บรรทัดก่อนหน้า:", *before]
    if after:
        parts += ["บรรทัดถัดไป:", *after]
    parts += ["", f"[ข้อความที่ต้องตรวจ — คืนเฉพาะส่วนนี้ {len(ch.idx)} บรรทัด]", "<<<",
              *[lines[i] for i in ch.idx], ">>>"]
    return "\n".join(parts)


THINK = re.compile(r"<think>.*?</think>", re.S)


def clean_output(s: str) -> list[str]:
    # reasoning models served by Ollama/vLLM may put their thinking inside <think>…</think>
    s = THINK.sub("", s)
    if "</think>" in s:
        s = s.split("</think>", 1)[1]
    s = s.strip("\n")
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    out = s.strip("\n").split("\n")
    if out and out[0].strip() == "<<<":
        out = out[1:]
    if out and out[-1].strip() == ">>>":
        out = out[:-1]
    return out


# ------------------------------------------------------------------ model
class LLM:
    def __init__(self, s: Settings):
        self.s = s

    def complete(self, user: str) -> str:
        body = json.dumps({"model": self.s.llm_model, "temperature": self.s.llm_temperature,
                           "max_tokens": self.s.llm_max_tokens,
                           **self.s.llm_extra_params,   # provider options from LLM_EXTRA_PARAMS
                           "messages": [{"role": "system", "content": self.s.system_prompt},
                                        {"role": "user", "content": user}]}).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "mcp-thai-proofread/0.2",
                   **self.s.extra_headers}
        if self.s.llm_api_key:
            headers["Authorization"] = f"Bearer {self.s.llm_api_key}"
        req = urllib.request.Request(f"{self.s.llm_base_url}/chat/completions", data=body, headers=headers)
        last = ""
        for attempt in range(self.s.llm_retries):
            try:
                with urllib.request.urlopen(req, timeout=self.s.llm_timeout) as r:
                    d = json.loads(r.read().decode("utf-8"))
                return d["choices"][0]["message"].get("content") or ""
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code in (401, 403):
                    # 401 = bad key; 403 can also be a spent budget or blocked model - show the provider's reason
                    try:
                        detail = e.read().decode("utf-8", "replace").strip()[:200]
                    except Exception:
                        detail = ""
                    last += (" - check LLM_API_KEY in .env (wrong, expired or still the example value)"
                             if e.code == 401 else " - the provider refused the request")
                    if detail:
                        last += f": {detail}"
                if e.code not in (408, 409, 429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as e:
                last = type(e).__name__
            time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"model call failed: {last}")


# ------------------------------------------------------------------ main
def proofread_lines(lines: list[str], s: Settings) -> dict:
    """Returns new lines + changes/rejected/errors. Does not touch any file."""
    llm = LLM(s)
    title, chunks = make_chunks(lines, s.chunk_chars)
    new = list(lines)
    changes, rejected, errors = [], [], []

    def run(ch: Chunk, depth: int = 0) -> list[tuple[int, str]] | None:
        out = clean_output(llm.complete(build_prompt(lines, ch, title, s.context_lines)))
        if len(out) == len(ch.idx):
            return list(zip(ch.idx, out))
        if len(ch.idx) == 1 or depth >= 4:
            errors.append(f"บรรทัด {ch.idx[0] + 1}-{ch.idx[-1] + 1}: LLM ส่งกลับมา {len(out)} บรรทัด แต่ต้องการ {len(ch.idx)} บรรทัด จึงคงข้อความเดิมไว้")
            return None
        mid = len(ch.idx) // 2
        a = run(Chunk(ch.idx[:mid], ch.headings), depth + 1) or []
        b = run(Chunk(ch.idx[mid:], ch.headings), depth + 1) or []
        return a + b

    def work(ch: Chunk):
        try:
            return run(ch)
        except RuntimeError as e:
            errors.append(f"บรรทัด {ch.idx[0] + 1}-{ch.idx[-1] + 1}: {e}")
            return None

    with cf.ThreadPoolExecutor(max_workers=s.workers) as ex:
        for pairs in ex.map(work, chunks):
            for i, cand in pairs or []:
                old = lines[i]
                cand = cand.rstrip() + old[len(old.rstrip()):]
                ok, why = judge(old, cand, s.min_similarity, s.protected_regex)
                if ok and cand != old:
                    new[i] = cand
                    changes.append({"line": i + 1, "before": old, "after": cand})
                elif not ok:
                    rejected.append({"line": i + 1, "reason": why, "before": old, "suggested": cand})
    changes.sort(key=lambda c: c["line"])
    rejected.sort(key=lambda c: c["line"])
    return {"lines": new, "chunks": len(chunks), "changes": changes, "rejected": rejected, "errors": errors}
