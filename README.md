# mcp-thai-proofread

MCP server สำหรับ**ตรวจและแก้คำสะกดภาษาไทย**ในไฟล์ Markdown หรือข้อความ ด้วย LLM ที่เรียกผ่าน endpoint แบบ OpenAI-compatible (OpenRouter, vLLM, Ollama ฯลฯ)
แก้เฉพาะการสะกด ไม่เรียบเรียงใหม่ และมีกฎตรวจคำตอบของ LLM อีกชั้น เพื่อกันไม่ให้ตัวเลข รหัส URL หรือโครงสร้างเอกสารเปลี่ยน

ให้ AI agent ที่รองรับ MCP (เช่น Hermes) เรียกใช้ผ่าน **streamable HTTP** ที่ `http://<host>:8800/mcp`

ผู้พัฒนา: **Chacharin Lertyosbordin**

## เครื่องมือ

| เครื่องมือ | อาร์กิวเมนต์ | ผล |
|---|---|---|
| `proofread_thai` | `path` path สัมพัทธ์จาก workspace เช่น `report.md` หรือ `project-a/chapter1.md`<br>`dry_run` (ไม่บังคับ) `true` = ตรวจอย่างเดียว | แก้ไฟล์จริง สำรองไฟล์เดิมไว้ที่ `<โฟลเดอร์>/backups/` และบันทึกรายการแก้ไว้ที่ `<โฟลเดอร์>/notes/proofread-<ชื่อ>.md` |
| `proofread_text` | `text` ข้อความ (Markdown ได้)<br>`title` (ไม่บังคับ) ใช้เป็นบริบท | คืนข้อความที่แก้แล้ว ไม่อ่านหรือเขียนไฟล์ |

`<โฟลเดอร์>` ตั้งด้วย `OUTPUT_PLACEMENT`: `file` (ค่าเริ่มต้น) = โฟลเดอร์เดียวกับไฟล์ที่แก้ · `top` = โฟลเดอร์ชั้นแรกใต้ workspace (รวมไว้ที่เดียวต่อหนึ่งโปรเจกต์) ชื่อโฟลเดอร์ย่อยเปลี่ยนได้ด้วย `BACKUP_SUBDIR` และ `NOTES_SUBDIR` (ตั้ง `NOTES_SUBDIR` ว่าง = ไม่เขียนบันทึก ส่วนไฟล์สำรองปิดไม่ได้)

## หลักการทำงาน

1. **หา path อย่างปลอดภัย** — ตัด prefix ที่ agent อาจใส่มา (`PATH_PREFIXES`) บังคับให้ไฟล์อยู่ใน workspace และรับเฉพาะนามสกุลที่อนุญาต (`FILE_EXTENSIONS`)
2. **หั่นเอกสาร** — ขึ้นช่วงใหม่ทุกหัวข้อ หรือเมื่อเกิน `CHUNK_CHARS` ตัวอักษร ข้ามบล็อกโค้ดและบรรทัดที่ไม่มีภาษาไทย (ไม่ส่งไป LLM)
3. **แนบบริบท** — ชื่อเอกสาร ลำดับหัวข้อ และ `CONTEXT_LINES` บรรทัดก่อนและหลัง (LLM อ่านได้แต่ไม่แก้)
4. **เรียก LLM** — ส่งพร้อมกัน `WORKERS` ช่วง ลองใหม่เมื่อเจอ 429 หรือ 5xx ถ้า LLM คืนจำนวนบรรทัดไม่ตรง จะหั่นช่วงครึ่งแล้วส่งใหม่
5. **ตรวจทีละบรรทัด** — ไม่รับการแก้ (คงข้อความเดิมและบันทึกเหตุผล) ถ้า
   - ตัวเลข, URL, คำภาษาอังกฤษ, รหัสที่ตรงกับ `PROTECTED_REGEX`, จำนวน `|` หรือ `**` หรือเครื่องหมายหัวข้อและรายการ เปลี่ยนไป
   - หรือบรรทัดเปลี่ยนไปมากกว่าเกณฑ์ `MIN_SIMILARITY`
6. **เขียนผล** — สำรองไฟล์เดิมก่อนเขียนทับ แล้วบันทึกว่าแก้บรรทัดไหน และไม่รับการแก้บรรทัดไหน เพราะอะไร

## เริ่มใช้งาน

### สิ่งที่ต้องมี

- **Docker ที่เปิด BuildKit** — Docker Desktop และ Docker Engine 23.0 ขึ้นไปเปิดเป็นค่าเริ่มต้นแล้ว
  ถ้า build แล้วเจอ `the --mount option requires BuildKit` ให้อัปเดต Docker หรือสั่ง build ด้วย `DOCKER_BUILDKIT=1 docker compose build`
- **อินเทอร์เน็ตตอน build ครั้งแรก** — ดึง `python:3.12-slim`, image ของ uv และไลบรารีจาก PyPI (ถ้าองค์กรปิดอินเทอร์เน็ต ต้องใช้ mirror ภายใน)
- **LLM endpoint แบบ OpenAI-compatible** พร้อม API key (ถ้า endpoint ต้องใช้)

**ไม่ต้องติดตั้ง Python หรือ uv บนเครื่อง** — Dockerfile ยืม uv รุ่นที่ระบุไว้มาติดตั้งไลบรารีตาม `uv.lock` ระหว่าง build แล้วไม่เก็บไว้ใน image ทุกคนจึงได้ไลบรารีเวอร์ชันเดียวกัน

### ติดตั้ง

```bash
cp .env.example .env          # แล้วแก้ LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
mkdir -p workspace            # วางไฟล์ที่ต้องการตรวจไว้ที่นี่ (หรือชี้ไปที่อื่นด้วย WORKSPACE_HOST_DIR)
docker network create agent_network   # ครั้งแรกครั้งเดียว — ชื่ออื่นตั้งได้ด้วย DOCKER_NETWORK
docker compose up -d --build
curl http://127.0.0.1:8805/health
```

ถ้า `/health` ตอบ `"ok": false` ให้ดูรายการ `problems` ในคำตอบ เช่น ยังไม่ได้เปลี่ยน `LLM_API_KEY` จากค่าตัวอย่าง หรือ workspace ยังไม่ถูก mount

`.env` ใส่เฉพาะค่าในหมวด "ต้องตั้ง" และค่าที่ต้องการให้ต่างจากค่าเริ่มต้น ส่วน `.env.example` เป็นคู่มือของทุกค่า ค่าเริ่มต้นในโค้ดเป็นกลาง ไม่ผูกกับ agent หรือองค์กรใด

ทดสอบด้วยการเรียก LLM จริงหนึ่งครั้ง:

```bash
docker exec mcp-thai-proofread /app/.venv/bin/python -m app.selftest
docker exec mcp-thai-proofread /app/.venv/bin/python -m app.selftest --file report.md   # ตรวจไฟล์จริงแบบไม่เขียน
```

ค่าตั้งทั้งหมดและคำอธิบายอยู่ใน [`.env.example`](.env.example) แก้ `.env` แล้วสั่ง `docker compose up -d` (ไม่ต้อง build ใหม่)

## เชื่อมกับ MCP client

ตัวอย่างสำหรับ Hermes (`config.yaml`):

```yaml
mcp_servers:
  thai_proofread:
    url: http://mcp-thai-proofread:8800/mcp
    timeout: 900          # ไฟล์ยาวใช้เวลาหลายนาที อย่าตั้งต่ำกว่า LLM_TIMEOUT_SECONDS
    connect_timeout: 60
```

ถ้า timeout ของ client สั้นกว่าเวลาที่ใช้ตรวจจริง client จะรายงานว่าล้มเหลว ทั้งที่ server ยังแก้ไฟล์ต่ออยู่เบื้องหลัง

ถ้า agent อ้างถึงไฟล์ด้วย path ของเครื่องตัวเอง (เช่น Hermes ส่ง `/opt/data/workspace/report.md`) ให้ตั้ง `PATH_PREFIXES=/opt/data/workspace/` เพื่อให้ระบบตัด prefix นั้นออก ส่วน uid/gid (`RUN_UID`, `RUN_GID`) ควรตรงกับเจ้าของ workspace ของ agent

ตัวเลือกเฉพาะของผู้ให้บริการ LLM (เช่น `top_p` หรือการเลือก provider ของ OpenRouter) ส่งผ่าน `LLM_EXTRA_PARAMS` เป็น JSON ได้โดยไม่ต้องแก้โค้ด

## ปรับ prompt ให้เข้ากับงาน

prompt ในตัวเป็นแบบทั่วไป (เนื้อหาเดียวกับ [`prompts/system_prompt.example.md`](prompts/system_prompt.example.md)) ถ้าต้องการปรับ:

```bash
cp prompts/system_prompt.example.md prompts/system_prompt.md   # แล้วแก้ไฟล์นี้
echo "SYSTEM_PROMPT_FILE=/app/prompts/system_prompt.md" >> .env
docker compose up -d
```

prompt ต้องยังสั่งให้ LLM **คืนเฉพาะบรรทัดที่ต้องตรวจ จำนวนเท่าเดิม เรียงตามเดิม และไม่มีคำอธิบาย** ไม่อย่างนั้นการแก้จะถูกปฏิเสธทั้งช่วง
ไฟล์ใน `prompts/` ที่ไม่ใช่ `*.example.md` จะไม่ถูก commit (อาจมีชื่อองค์กร)

## ความปลอดภัย

- workspace ถูก mount **แบบเขียนได้** เพราะเครื่องมือแก้ไฟล์ให้ ทุกการแก้มีไฟล์สำรองเสมอ
- ค่าเริ่มต้นเปิดพอร์ต 8805 ให้เครื่องอื่นในเครือข่ายเรียกได้ (`PUBLISH_ADDR=0.0.0.0`) **ถ้าไม่ได้ตั้ง `MCP_AUTH_TOKEN` ใครในเครือข่ายก็สั่งแก้ไฟล์ได้** ควรตั้ง token หรือเปลี่ยนเป็น `PUBLISH_ADDR=127.0.0.1`
- API key ของ LLM อยู่ใน `.env` เท่านั้น และไม่ถูกส่งกลับไปให้ client

## พัฒนาต่อ

ชุดทดสอบไม่เรียก LLM จริง (ใช้ LLM จำลอง) จึงไม่เสียค่า API รันได้ 2 วิธี

ถ้ามี [uv](https://docs.astral.sh/uv/) บนเครื่อง:

```bash
uv run pytest
```

ถ้าไม่มี uv ให้รันผ่าน Docker (ไม่สร้างไฟล์ใด ๆ ในโฟลเดอร์โปรเจกต์):

```bash
docker run --rm -v "$PWD:/w" -w /w -e UV_PROJECT_ENVIRONMENT=/tmp/venv python:3.12-slim \
  sh -c "pip install -q uv==0.13.1 && uv run --frozen pytest -q -p no:cacheprovider"
```

บน PowerShell ใช้ `${PWD}` แทน `$PWD` และขึ้นบรรทัดใหม่ด้วย `` ` `` แทน `\`

เพิ่มหรืออัปเดตไลบรารี: แก้ `pyproject.toml` แล้วสั่ง `uv lock` และ commit `uv.lock` ที่ได้ไปด้วย

| ไฟล์ | หน้าที่ |
|---|---|
| `app/server.py` | MCP endpoint, `/health`, ตรวจ token, จัดการไฟล์ (หา path, สำรอง, บันทึก) |
| `app/proofread.py` | หั่นเอกสาร, ประกอบ prompt, เรียก LLM, กฎตรวจคำตอบ |
| `app/prompt.py` | system prompt ในตัว |
| `app/config.py` | อ่านค่าจาก `.env` |
| `app/selftest.py` | ทดสอบหลังติดตั้ง (เรียก LLM จริง) |
| `tests/` | ชุดทดสอบ (ไม่เรียก LLM จริง) |

## สัญญาอนุญาต

[MIT](LICENSE) © 2026 Chacharin Lertyosbordin
