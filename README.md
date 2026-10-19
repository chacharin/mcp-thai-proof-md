# mcp-thai-proofread

MCP server สำหรับ**ตรวจและแก้คำสะกดภาษาไทย**ในไฟล์ Markdown หรือข้อความทั่วไป โดยใช้ LLM ผ่าน endpoint แบบ OpenAI-compatible เช่น OpenRouter, vLLM และ Ollama
ระบบแก้ไขเฉพาะการสะกดคำโดยไม่เรียบเรียงเนื้อหาใหม่ และมีกฎตรวจสอบคำตอบของ LLM อีกชั้นหนึ่ง เพื่อป้องกันไม่ให้ตัวเลข รหัส URL หรือโครงสร้างของเอกสารเปลี่ยนไป

AI agent ที่รองรับ MCP เช่น Hermes เรียกใช้งานได้ผ่าน **streamable HTTP** ที่ `http://<host>:8800/mcp`

ผู้พัฒนา: **Chacharin Lertyosbordin**

## เครื่องมือที่มีให้

| เครื่องมือ | พารามิเตอร์ | ผลลัพธ์ |
|---|---|---|
| `proofread_thai` | `path` ตำแหน่งไฟล์เทียบกับ workspace เช่น `report.md` หรือ `project-a/chapter1.md`<br>`dry_run` (ไม่บังคับ) หากเป็น `true` จะตรวจอย่างเดียวโดยไม่แก้ไฟล์ | แก้ไขไฟล์จริง สำรองไฟล์ต้นฉบับไว้ที่ `<โฟลเดอร์>/backups/` และบันทึกรายการที่แก้ไขไว้ที่ `<โฟลเดอร์>/notes/proofread-<ชื่อไฟล์>.md` |
| `proofread_text` | `text` ข้อความที่ต้องการตรวจ (ใช้ Markdown ได้)<br>`title` (ไม่บังคับ) ชื่อเรื่องที่ใช้เป็นบริบท | ส่งข้อความที่แก้ไขแล้วกลับมา โดยไม่อ่านหรือเขียนไฟล์ใด ๆ |

`<โฟลเดอร์>` กำหนดได้ด้วย `OUTPUT_PLACEMENT` ได้แก่ `file` (ค่าเริ่มต้น) คือโฟลเดอร์เดียวกับไฟล์ที่แก้ไข และ `top` คือโฟลเดอร์ชั้นแรกใต้ workspace ซึ่งเหมาะกับการรวมไฟล์สำรองของโปรเจกต์ไว้ในที่เดียว
เปลี่ยนชื่อโฟลเดอร์ย่อยได้ด้วย `BACKUP_SUBDIR` และ `NOTES_SUBDIR` หากกำหนด `NOTES_SUBDIR` เป็นค่าว่าง ระบบจะไม่เขียนบันทึก ส่วนการสำรองไฟล์ไม่สามารถปิดได้

## หลักการทำงาน

1. **ตรวจสอบตำแหน่งไฟล์** — ตัดคำนำหน้า path ที่ agent อาจส่งมา (`PATH_PREFIXES`) ตรวจว่าไฟล์อยู่ภายใน workspace และรับเฉพาะนามสกุลที่อนุญาต (`FILE_EXTENSIONS`)
2. **แบ่งเอกสารเป็นช่วง** — เริ่มช่วงใหม่ทุกครั้งที่พบหัวข้อ หรือเมื่อความยาวเกิน `CHUNK_CHARS` ตัวอักษร โดยข้ามบล็อกโค้ดและบรรทัดที่ไม่มีภาษาไทย ซึ่งจะไม่ถูกส่งไปยัง LLM
3. **แนบบริบท** — ส่งชื่อเอกสาร ลำดับหัวข้อ และบรรทัดก่อนหลังจำนวน `CONTEXT_LINES` บรรทัดไปด้วย เพื่อให้ LLM ใช้ประกอบการพิจารณาเท่านั้น
4. **ส่งให้ LLM ตรวจ** — ส่งพร้อมกันครั้งละ `WORKERS` ช่วง และลองใหม่เมื่อได้รับ HTTP 429 หรือ 5xx หาก LLM ส่งจำนวนบรรทัดกลับมาไม่ครบ ระบบจะแบ่งช่วงนั้นครึ่งหนึ่งแล้วส่งใหม่
5. **ตรวจสอบผลทีละบรรทัด** — ระบบจะปฏิเสธการแก้ไขและคงข้อความเดิมไว้พร้อมบันทึกเหตุผล หาก
   - ตัวเลข URL คำภาษาอังกฤษ รหัสที่ตรงกับ `PROTECTED_REGEX` จำนวนเครื่องหมาย `|` หรือ `**` หรือเครื่องหมายหัวข้อและรายการเปลี่ยนไป
   - หรือบรรทัดนั้นเปลี่ยนไปจากต้นฉบับมากกว่าเกณฑ์ `MIN_SIMILARITY`
6. **บันทึกผล** — สำรองไฟล์ต้นฉบับก่อนเขียนทับ แล้วบันทึกว่าแก้ไขบรรทัดใด และปฏิเสธการแก้ไขบรรทัดใดด้วยเหตุผลอะไร

## เริ่มต้นใช้งาน

### สิ่งที่ต้องเตรียม

- **Docker ที่เปิดใช้ BuildKit** ซึ่ง Docker Desktop และ Docker Engine ตั้งแต่เวอร์ชัน 23.0 เปิดไว้เป็นค่าเริ่มต้นแล้ว
  หากพบข้อความ `the --mount option requires BuildKit` ระหว่าง build ให้อัปเดต Docker หรือสั่ง build ด้วย `DOCKER_BUILDKIT=1 docker compose build`
- **การเชื่อมต่ออินเทอร์เน็ตระหว่าง build ครั้งแรก** เพื่อดาวน์โหลด `python:3.12-slim` image ของ uv และไลบรารีจาก PyPI (หากองค์กรไม่อนุญาตให้เชื่อมต่ออินเทอร์เน็ต ต้องใช้ mirror ภายใน)
- **LLM endpoint แบบ OpenAI-compatible** พร้อม API key (หาก endpoint นั้นกำหนดให้ใช้)

**ไม่จำเป็นต้องติดตั้ง Python หรือ uv บนเครื่อง** เพราะ Dockerfile จะใช้ uv เวอร์ชันที่ระบุไว้ติดตั้งไลบรารีตาม `uv.lock` เฉพาะระหว่าง build และไม่เก็บ uv ไว้ใน image ทุกเครื่องจึงได้ไลบรารีเวอร์ชันเดียวกัน

### ขั้นตอนการติดตั้ง

```bash
git clone https://github.com/chacharin/mcp-thai-proof-md.git
cd mcp-thai-proof-md
cp .env.example .env          # จากนั้นแก้ LLM_BASE_URL, LLM_API_KEY และ LLM_MODEL ในไฟล์ .env
mkdir -p workspace            # วางไฟล์ที่ต้องการตรวจไว้ในโฟลเดอร์นี้ หรือกำหนดโฟลเดอร์อื่นใน WORKSPACE_HOST_DIR
docker network create agent_network   # สร้างครั้งแรกครั้งเดียว หากต้องการใช้ชื่ออื่นให้กำหนดใน DOCKER_NETWORK
docker compose up -d --build
curl http://127.0.0.1:8805/health
```

หาก `/health` ตอบกลับ `"ok": false` ให้ดูรายการ `problems` ในคำตอบ เช่น ยังไม่ได้เปลี่ยน `LLM_API_KEY` จากค่าตัวอย่าง หรือยังไม่ได้ mount workspace

ทดสอบการทำงานด้วยการเรียก LLM จริงหนึ่งครั้ง:

```bash
docker exec mcp-thai-proofread /app/.venv/bin/python -m app.selftest
docker exec mcp-thai-proofread /app/.venv/bin/python -m app.selftest --file report.md   # ตรวจไฟล์จริงโดยไม่แก้ไขไฟล์
```

คำอธิบายการตั้งค่าทั้งหมดอยู่ในไฟล์ [`.env.example`](.env.example) โดยในไฟล์ `.env` ให้กำหนดเฉพาะค่าที่จำเป็นและค่าที่ต้องการเปลี่ยนจากค่าเริ่มต้น ค่าเริ่มต้นในโค้ดไม่ผูกกับ agent หรือองค์กรใด
เมื่อแก้ไข `.env` แล้ว ให้สั่ง `docker compose up -d` อีกครั้ง โดยไม่ต้อง build ใหม่

## การเชื่อมต่อกับ MCP client

ตัวอย่างการตั้งค่าใน Hermes (`config.yaml`):

```yaml
mcp_servers:
  thai_proofread:
    url: http://mcp-thai-proofread:8800/mcp
    timeout: 900          # ไฟล์ยาวอาจใช้เวลาหลายนาที ควรตั้งให้นานกว่า LLM_TIMEOUT_SECONDS
    connect_timeout: 60
```

หาก timeout ของ client สั้นกว่าเวลาที่ใช้ตรวจจริง client จะแจ้งว่าการเรียกล้มเหลว ทั้งที่ server ยังแก้ไขไฟล์ต่อไปอยู่

หาก agent อ้างถึงไฟล์ด้วย path ภายในเครื่องของตัวเอง เช่น Hermes ส่ง `/opt/data/workspace/report.md` ให้กำหนด `PATH_PREFIXES=/opt/data/workspace/` เพื่อให้ระบบตัดคำนำหน้านั้นออก และควรกำหนด `RUN_UID` และ `RUN_GID` ให้ตรงกับเจ้าของ workspace ของ agent

หากต้องการส่งตัวเลือกเฉพาะของผู้ให้บริการ LLM เช่น `top_p` หรือการเลือก provider ของ OpenRouter ให้กำหนดเป็น JSON ใน `LLM_EXTRA_PARAMS` โดยไม่ต้องแก้ไขโค้ด

## การปรับ prompt ให้เหมาะกับงาน

prompt ที่มากับระบบเป็นแบบทั่วไป มีเนื้อหาเดียวกับไฟล์ [`prompts/system_prompt.example.md`](prompts/system_prompt.example.md) หากต้องการปรับให้เหมาะกับงาน:

```bash
cp prompts/system_prompt.example.md prompts/system_prompt.md   # จากนั้นแก้ไขไฟล์นี้
echo "SYSTEM_PROMPT_FILE=/app/prompts/system_prompt.md" >> .env
docker compose up -d
```

prompt ที่แก้ไขแล้วยังต้องสั่งให้ LLM **ส่งกลับเฉพาะบรรทัดที่ต้องตรวจ ในจำนวนและลำดับเดิม โดยไม่มีคำอธิบายเพิ่มเติม** มิฉะนั้นระบบจะปฏิเสธการแก้ไขของช่วงนั้นทั้งหมด
ไฟล์ในโฟลเดอร์ `prompts/` ที่ไม่ใช่ `*.example.md` จะไม่ถูก commit เนื่องจากอาจมีชื่อองค์กรอยู่

## ความปลอดภัย

- workspace ถูก mount **แบบเขียนได้** เพราะเครื่องมือต้องแก้ไขไฟล์ และทุกการแก้ไขจะมีไฟล์สำรองเสมอ
- ค่าเริ่มต้นเปิดพอร์ต 8805 ให้เครื่องอื่นในเครือข่ายเข้าถึงได้ (`PUBLISH_ADDR=0.0.0.0`) **หากไม่ได้กำหนด `MCP_AUTH_TOKEN` ทุกคนในเครือข่ายจะสั่งแก้ไขไฟล์ได้** จึงควรกำหนด token หรือเปลี่ยนเป็น `PUBLISH_ADDR=127.0.0.1`
- API key ของ LLM ถูกเก็บไว้ในไฟล์ `.env` เท่านั้น และไม่ถูกส่งกลับไปยัง client

## การพัฒนาต่อ

ชุดทดสอบใช้ LLM จำลองแทนการเรียก LLM จริง จึงไม่มีค่าใช้จ่าย และรันได้ 2 วิธี

หากติดตั้ง [uv](https://docs.astral.sh/uv/) ไว้บนเครื่อง:

```bash
uv run pytest
```

หากไม่ได้ติดตั้ง uv ให้รันผ่าน Docker ซึ่งจะไม่สร้างไฟล์ใด ๆ ในโฟลเดอร์โปรเจกต์:

```bash
docker run --rm -v "$PWD:/w" -w /w -e UV_PROJECT_ENVIRONMENT=/tmp/venv python:3.12-slim \
  sh -c "pip install -q uv==0.13.1 && uv run --frozen pytest -q -p no:cacheprovider"
```

หากใช้ PowerShell ให้เปลี่ยน `$PWD` เป็น `${PWD}` และใช้ `` ` `` แทน `\` สำหรับขึ้นบรรทัดใหม่

การเพิ่มหรืออัปเดตไลบรารี: แก้ไข `pyproject.toml` แล้วสั่ง `uv lock` จากนั้น commit ไฟล์ `uv.lock` ที่เปลี่ยนไปด้วย

| ไฟล์ | หน้าที่ |
|---|---|
| `app/server.py` | MCP endpoint, `/health`, การตรวจ token และการจัดการไฟล์ (ตรวจตำแหน่งไฟล์ สำรองไฟล์ เขียนบันทึก) |
| `app/proofread.py` | แบ่งเอกสารเป็นช่วง สร้าง prompt เรียก LLM และตรวจสอบคำตอบ |
| `app/prompt.py` | system prompt ที่มากับระบบ |
| `app/config.py` | อ่านค่าการตั้งค่าจาก `.env` |
| `app/selftest.py` | ทดสอบหลังติดตั้ง (เรียก LLM จริง) |
| `tests/` | ชุดทดสอบ (ไม่เรียก LLM จริง) |

## สัญญาอนุญาต

[MIT](LICENSE) © 2026 Chacharin Lertyosbordin
