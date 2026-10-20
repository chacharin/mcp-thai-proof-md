# mcp-thai-proofread

MCP server ที่ช่วยให้ AI agent ที่รองรับ MCP เช่น Hermes ตรวจและแก้คำสะกดภาษาไทยในไฟล์ Markdown หรือในข้อความได้โดยตรง
ทำงานบน Docker ในโหมด **streamable HTTP** โดยใช้ LLM ผ่าน endpoint แบบ OpenAI-compatible เช่น OpenRouter, vLLM หรือ Ollama

ผู้พัฒนา: **Chacharin Lertyosbordin**

> ระบบแก้เฉพาะการสะกดคำ โดยไม่เรียบเรียงเนื้อหาใหม่ และตรวจคำตอบของ LLM อีกชั้นหนึ่ง
> เพื่อไม่ให้ตัวเลข รหัสอ้างอิง URL หรือโครงสร้างของเอกสารเปลี่ยนไป

## เครื่องมือที่มีให้

| เครื่องมือ | หน้าที่ | อ่านหรือเขียนไฟล์ |
|---|---|---|
| `proofread_thai` | ตรวจและแก้คำสะกดในไฟล์ (ค่าเริ่มต้นคือ `.md`) แล้วบันทึกทับไฟล์เดิม โดยสำรองไฟล์ต้นฉบับไว้ก่อนเสมอ และเขียนบันทึกว่าแก้บรรทัดใดบ้าง | อ่านและเขียนไฟล์ใน workspace |
| `proofread_text` | ตรวจและแก้คำสะกดในข้อความ แล้วส่งข้อความที่แก้แล้วกลับมา | ไม่แตะไฟล์ใด ๆ |

`proofread_thai` มีโหมด `dry_run` สำหรับดูรายการที่จะแก้ก่อนโดยยังไม่เปลี่ยนไฟล์

## หลักการทำงาน

```
agent ──POST /mcp──▶ mcp-thai-proofread (container)
                       ① ตรวจ token หากกำหนด MCP_AUTH_TOKEN ไว้
                       ② แบ่งเอกสารเป็นช่วง แล้วส่งให้ LLM ตรวจทีละช่วง
                       ③ ตรวจคำตอบของ LLM ทีละบรรทัด และปฏิเสธการแก้ไขที่เกินขอบเขต
                       ④ สำรองไฟล์ต้นฉบับ บันทึกไฟล์ที่แก้แล้ว และเขียนบันทึกการแก้ไข
                     ◀── ส่งสรุปผลกลับไปยัง agent
```

รายละเอียดของแต่ละขั้น:

1. **ตรวจตำแหน่งไฟล์** ตัดคำนำหน้า path ที่ agent อาจส่งมา (`PATH_PREFIXES`) ตรวจว่าไฟล์อยู่ภายใน workspace และรับเฉพาะนามสกุลที่อนุญาต (`FILE_EXTENSIONS`)
2. **แบ่งเอกสารเป็นช่วง** เริ่มช่วงใหม่ทุกครั้งที่พบหัวข้อ หรือเมื่อความยาวเกิน `CHUNK_CHARS` ตัวอักษร โดยข้ามบล็อกโค้ดและบรรทัดที่ไม่มีภาษาไทย ซึ่งจะไม่ถูกส่งไปยัง LLM
3. **แนบบริบท** ส่งชื่อเอกสาร ลำดับหัวข้อ และบรรทัดก่อนหลังจำนวน `CONTEXT_LINES` บรรทัดไปด้วย เพื่อให้ LLM ใช้ประกอบการพิจารณาเท่านั้น
4. **ส่งให้ LLM ตรวจ** ส่งพร้อมกันครั้งละ `WORKERS` ช่วง และลองใหม่เมื่อได้รับ HTTP 429 หรือ 5xx หาก LLM ส่งจำนวนบรรทัดกลับมาไม่ครบ ระบบจะแบ่งช่วงนั้นครึ่งหนึ่งแล้วส่งใหม่
5. **ตรวจผลทีละบรรทัด** ระบบจะปฏิเสธการแก้ไขและคงข้อความเดิมไว้ หาก
   - ตัวเลข URL คำภาษาอังกฤษ รหัสที่ตรงกับ `PROTECTED_REGEX` หรือรูปแบบ Markdown (ตาราง ตัวหนา หัวข้อ รายการ) เปลี่ยนไป
   - หรือบรรทัดนั้นเปลี่ยนไปจากต้นฉบับมากกว่าเกณฑ์ `MIN_SIMILARITY`
6. **บันทึกผล** สำรองไฟล์ต้นฉบับก่อนเขียนทับ แล้วบันทึกว่าแก้บรรทัดใด และปฏิเสธการแก้ไขบรรทัดใดด้วยเหตุผลอะไร

ค่าใช้จ่ายขึ้นอยู่กับ LLM ที่เลือกและความยาวของเอกสาร เพราะทุกช่วงของเอกสารต้องส่งให้ LLM ตรวจหนึ่งครั้ง

### สองวิธีในการเข้าถึง workspace

`proofread_thai` ต้องอ่านและเขียนไฟล์ชุดเดียวกับที่ agent ใช้งาน ระบบรองรับ 2 วิธี และเลือกให้เองตอนเริ่มทำงาน

| โหมด | เงื่อนไข | เหมาะกับ |
|---|---|---|
| `hermes` | ไม่มีโฟลเดอร์ workspace ใน container แต่กำหนดบัญชี dashboard ของ Hermes ไว้ (`HERMES_DASHBOARD_URL`, `HERMES_DASHBOARD_USER`, `HERMES_DASHBOARD_PASSWORD`) | server อยู่คนละเครื่องกับ Hermes ระบบอ่านและเขียนไฟล์ผ่าน API ไฟล์ของ dashboard ทาง HTTP เหมือน MCP ทั่วไป |
| `local` | mount โฟลเดอร์ workspace ไว้ที่ `WORKSPACE_DIR` (ค่าเริ่มต้น `/workspace`) | server อยู่เครื่องเดียวกับ agent หรือใช้งานกับ agent อื่นที่ไม่ใช่ Hermes |

```
โหมด hermes (คนละเครื่องได้)
agent ──POST /mcp──▶ mcp-thai-proofread ──HTTP──▶ Hermes dashboard ──▶ /opt/data/workspace
                                         GET  /api/files/read     (อ่านไฟล์)
                                         POST /api/files/upload   (สำรองไฟล์ บันทึกไฟล์ที่แก้ และบันทึกการแก้ไข)

โหมด local (เครื่องเดียวกัน)
agent ──POST /mcp──▶ mcp-thai-proofread ──▶ /workspace (โฟลเดอร์ที่ mount ไว้)
```

ทั้งสองโหมดให้ผลลัพธ์และสร้างไฟล์สำรองกับบันทึกการแก้ไขเหมือนกันทุกประการ ต่างกันเพียงช่องทางที่ใช้เข้าถึงไฟล์
หากมีทั้งโฟลเดอร์ที่ mount ไว้และบัญชี dashboard ระบบจะใช้โฟลเดอร์ก่อน

## เริ่มต้นใช้งาน

### สิ่งที่ต้องเตรียม

- **Docker ที่เปิดใช้ BuildKit** ซึ่ง Docker Desktop และ Docker Engine ตั้งแต่เวอร์ชัน 23.0 เปิดไว้เป็นค่าเริ่มต้นแล้ว
  หากพบข้อความ `the --mount option requires BuildKit` ระหว่าง build ให้อัปเดต Docker หรือสั่ง build ด้วย `DOCKER_BUILDKIT=1 docker compose build`
- **การเชื่อมต่ออินเทอร์เน็ตระหว่าง build ครั้งแรก** เพื่อดาวน์โหลด `python:3.12-slim` image ของ uv และไลบรารีจาก PyPI (หากองค์กรไม่อนุญาตให้เชื่อมต่ออินเทอร์เน็ต ต้องใช้ mirror ภายใน)
- **LLM endpoint แบบ OpenAI-compatible** พร้อม API key (หาก endpoint นั้นกำหนดให้ใช้) ควรเลือก model ที่รองรับภาษาไทยได้ดี เพราะคุณภาพการแก้ไขขึ้นอยู่กับ model โดยตรง

ไม่จำเป็นต้องติดตั้ง Python หรือ uv บนเครื่อง เพราะ Dockerfile จะใช้ uv เวอร์ชันที่ระบุไว้ติดตั้งไลบรารีตาม `uv.lock` เฉพาะระหว่าง build และไม่เก็บ uv ไว้ใน image ทุกเครื่องจึงได้ไลบรารีเวอร์ชันเดียวกัน

### ขั้นตอนการติดตั้ง

```bash
git clone https://github.com/chacharin/mcp-thai-proof-md.git
cd mcp-thai-proof-md
cp .env.example .env                  # จากนั้นแก้ LLM_BASE_URL, LLM_API_KEY และ LLM_MODEL ในไฟล์ .env
docker network create agent_network   # สร้างครั้งแรกครั้งเดียว หากต้องการใช้ชื่ออื่นให้กำหนดใน DOCKER_NETWORK
```

จากนั้นเลือกวิธีเข้าถึง workspace ในไฟล์ `.env` ตามแบบใดแบบหนึ่ง

**แบบที่ 1 ผ่าน dashboard ของ Hermes** (server อยู่คนละเครื่องกับ Hermes ได้) ให้กำหนดค่าในหมวด `--- workspace ---`

```bash
HERMES_DASHBOARD_URL=http://hermes-dashboard:9119   # หรือ https://<เครื่องของ Hermes> เมื่ออยู่คนละเครื่อง
HERMES_DASHBOARD_USER=<ชื่อผู้ใช้ dashboard>
HERMES_DASHBOARD_PASSWORD=<รหัสผ่าน dashboard>
PATH_PREFIXES=/opt/data/workspace/                  # Hermes อ้างถึงไฟล์ด้วย path นี้
```

**แบบที่ 2 mount โฟลเดอร์** (server อยู่เครื่องเดียวกับ agent) ให้เพิ่มไฟล์ `docker-compose.same-host.yml` เข้าไปในการสั่ง compose

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.same-host.yml   # บน Windows ใช้ ; คั่นแทน :
WORKSPACE_HOST_DIR=./workspace                                 # โฟลเดอร์บนเครื่องที่เก็บไฟล์ที่ต้องการตรวจ
```

เมื่อกำหนด `COMPOSE_FILE` ไว้ใน `.env` แล้ว คำสั่ง `docker compose` ทุกคำสั่งจะใช้ทั้งสองไฟล์เอง จึงไม่ต้องระบุ `-f` ทุกครั้ง

จากนั้นเริ่มระบบและตรวจสถานะ

```bash
docker compose up -d --build
curl http://127.0.0.1:8805/health
```

หาก `/health` ตอบ `"ok": true` และ `workspace.reachable` เป็น `true` แปลว่าการตั้งค่า LLM พร้อมใช้งานและเข้าถึง workspace ได้แล้ว
หากยังมีปัญหา ให้ดูรายการ `problems` ซึ่งจะบอกสาเหตุ เช่น ยังใช้ `LLM_API_KEY` ตัวอย่างจาก `.env.example` หรือ dashboard ปฏิเสธรหัสผ่าน

`/health` ไม่ได้เรียก LLM จริง หากต้องการทดสอบให้แน่ใจว่า LLM ตอบได้ ให้สั่ง (เรียก LLM จริงหนึ่งครั้ง):

```bash
docker exec mcp-thai-proofread /app/.venv/bin/python -m app.selftest
docker exec mcp-thai-proofread /app/.venv/bin/python -m app.selftest --file report.md   # ตรวจไฟล์จริงโดยไม่แก้ไขไฟล์
```

คำอธิบายการตั้งค่าทั้งหมดอยู่ในไฟล์ [`.env.example`](.env.example) โดยในไฟล์ `.env` ให้กำหนดเฉพาะค่าที่จำเป็น และค่าที่ต้องการเปลี่ยนจากค่าเริ่มต้น
เมื่อแก้ไข `.env` แล้ว ให้สั่ง `docker compose up -d` อีกครั้ง โดยไม่ต้อง build ใหม่

### การเชื่อมต่อกับ MCP client

ตัวอย่างการตั้งค่าใน Hermes (`config.yaml`):

```yaml
mcp_servers:
  thai_proofread:
    url: http://mcp-thai-proofread:8800/mcp
    timeout: 900          # ไฟล์ยาวอาจใช้เวลาหลายนาที ควรนานกว่า LLM_TIMEOUT_SECONDS
    connect_timeout: 60
```

หาก timeout ของ client สั้นกว่าเวลาที่ใช้ตรวจจริง client จะแจ้งว่าการเรียกล้มเหลว ทั้งที่ server ยังแก้ไขไฟล์ต่อไปอยู่

agent ต้องมองเห็นไฟล์ชุดเดียวกับ server
- หาก agent อ้างถึงไฟล์ด้วย path ภายในเครื่องของตัวเอง เช่น Hermes ส่ง `/opt/data/workspace/report.md` ให้กำหนด `PATH_PREFIXES=/opt/data/workspace/` เพื่อให้ระบบตัดคำนำหน้านั้นออก
- โหมด `hermes` ใช้ workspace ของ Hermes เสมอ (`HERMES_WORKSPACE` ค่าเริ่มต้น `/opt/data/workspace`) ไฟล์ที่แก้แล้วจึงเป็นไฟล์เดียวกับที่ agent เห็นทันที
- โหมด `local` ต้อง mount โฟลเดอร์เดียวกันให้ทั้งสองฝั่ง และกำหนด `RUN_UID` กับ `RUN_GID` ให้ตรงกับเจ้าของ workspace เพื่อให้ทั้ง agent และ server ยังเขียนไฟล์ที่แก้แล้วได้

หากกำหนด `MCP_AUTH_TOKEN` ไว้ ให้เพิ่ม header `Authorization: Bearer <token>` ในการตั้งค่าของ client ด้วย
สำหรับ client ที่อยู่นอก docker network ให้ใช้ `http://<IP ของเครื่อง>:8805/mcp`

## วิธีใช้งาน

เมื่อเชื่อมต่อแล้ว ผู้ใช้เพียงพิมพ์สั่ง agent ด้วยภาษาปกติ agent จะเลือกเครื่องมือและกรอกค่าให้เอง
หัวข้อนี้อธิบายว่าแต่ละงานควรสั่งอย่างไร และเครื่องมือรับค่าอะไรบ้าง

### 1. ตรวจและแก้ไฟล์

ตัวอย่างคำสั่ง:

> ตรวจคำสะกดภาษาไทยในไฟล์ report.md ให้หน่อย
> ตรวจภาษาไทยของ project-a/chapter1.md แต่ยังไม่ต้องแก้ไฟล์ ขอดูก่อนว่าจะแก้อะไรบ้าง

agent จะเรียก `proofread_thai`

| ค่า | จำเป็น | ความหมาย |
|---|---|---|
| `path` | ✓ | ตำแหน่งไฟล์เทียบกับราก workspace เช่น `report.md` หรือ `project-a/chapter1.md` |
| `dry_run` | | `true` = ตรวจอย่างเดียว แล้วส่งรายการที่จะแก้กลับมา โดยไม่เปลี่ยนไฟล์ (ค่าเริ่มต้น `false`) |

เมื่อแก้ไฟล์จริง ระบบจะสร้างไฟล์ 2 ไฟล์ใน `<โฟลเดอร์>`

| ไฟล์ | เนื้อหา |
|---|---|
| `backups/<ชื่อไฟล์>.bak-proof-<วันที่>-<เวลา>` | ไฟล์ต้นฉบับก่อนแก้ไข สร้างเฉพาะเมื่อมีการแก้ไข และปิดการสำรองไม่ได้ |
| `notes/proofread-<ชื่อไฟล์>.md` | บันทึกว่าแก้บรรทัดใดจากอะไรเป็นอะไร และปฏิเสธการแก้ไขบรรทัดใดด้วยเหตุผลอะไร ตรวจไฟล์เดิมซ้ำจะต่อท้ายบันทึกเดิม |

`<โฟลเดอร์>` กำหนดได้ด้วย `OUTPUT_PLACEMENT` ได้แก่ `file` (ค่าเริ่มต้น) คือโฟลเดอร์เดียวกับไฟล์ที่แก้ไข และ `top` คือโฟลเดอร์ชั้นแรกใต้ workspace ซึ่งเหมาะกับการรวมไฟล์สำรองของทั้งโปรเจกต์ไว้ในที่เดียว
เปลี่ยนชื่อโฟลเดอร์ย่อยได้ด้วย `BACKUP_SUBDIR` และ `NOTES_SUBDIR` หากกำหนด `NOTES_SUBDIR` เป็นค่าว่าง ระบบจะไม่เขียนบันทึก

ตัวอย่างบันทึกการแก้ไข:

```markdown
## ตรวจภาษาไทย 20261019-203654 · google/gemma-4-31b-it

- ไฟล์: `meeting.md` · ส่งตรวจ 1 ช่วง · แก้ 2 บรรทัด · ปฏิเสธการแก้ไข 0 บรรทัด
- จุดที่น่าสงสัย (ตรวจด้วยรูปแบบ) ก่อน/หลัง: 0 / 0

- บรรทัด 3
  - เดิม: ที่ประชุมอนุญาติให้ใช้งบประมาณ 2.5 ล้านบาท ตามข้อเสนอ [S1]
  - แก้: ที่ประชุมอนุญาตให้ใช้งบประมาณ 2.5 ล้านบาท ตามข้อเสนอ [S1]
```

หากต้องการย้อนกลับ ให้คัดลอกไฟล์จาก `backups/` กลับมาแทนไฟล์ที่แก้แล้ว
ไฟล์ขนาดไม่กี่ย่อหน้าใช้เวลาไม่กี่วินาที แต่เอกสารยาวอาจใช้เวลาหลายนาที

### 2. ตรวจข้อความที่ไม่ได้อยู่ในไฟล์

ตัวอย่างคำสั่ง:

> ช่วยตรวจคำสะกดของย่อหน้านี้ก่อนส่งอีเมล: …
> ร่างคำตอบเสร็จแล้ว ตรวจภาษาไทยให้ด้วยก่อนส่งให้ผม

agent จะเรียก `proofread_text`

| ค่า | จำเป็น | ความหมาย |
|---|---|---|
| `text` | ✓ | ข้อความที่ต้องการตรวจ (ใช้ Markdown ได้) |
| `title` | | ชื่อเรื่องของข้อความ ใช้เป็นบริบทให้ LLM เท่านั้น ไม่ถูกแก้ไขและไม่รวมอยู่ในผลลัพธ์ |

ผลลัพธ์คือข้อความทั้งหมดที่แก้แล้ว พร้อมรายการบรรทัดที่แก้และบรรทัดที่ปฏิเสธการแก้ไข โดยไม่มีการอ่านหรือเขียนไฟล์ใด ๆ

### 3. อ่านผลลัพธ์ให้ถูกต้อง

| ค่าในผลลัพธ์ | ความหมาย |
|---|---|
| `ok` | `true` = ตรวจครบทุกช่วงโดยไม่มีข้อผิดพลาด · `false` = มีข้อผิดพลาด ให้ดู `errors` หรือ `error` |
| `lines_changed` | จำนวนบรรทัดที่แก้ |
| `lines_rejected` | จำนวนบรรทัดที่ LLM เสนอให้แก้ แต่ระบบปฏิเสธและคงข้อความเดิมไว้ ดูเหตุผลได้ใน `rejected` หรือในบันทึกการแก้ไข |
| `suspect_before` / `suspect_after` | จำนวนจุดที่น่าจะสะกดผิด ซึ่งระบบนับด้วยรูปแบบที่กำหนดไว้ ก่อนและหลังแก้ ใช้ดูแนวโน้มคร่าว ๆ เท่านั้น |
| `errors` | ช่วงที่ตรวจไม่สำเร็จ เช่น เรียก LLM ไม่ได้ ช่วงนั้นจะคงข้อความเดิมไว้ทั้งหมด |

เหตุผลที่ระบบปฏิเสธการแก้ไขมี 3 แบบ

| เหตุผล | ความหมาย |
|---|---|
| `ตัวเลข รหัส URL คำภาษาอังกฤษ หรือรูปแบบ Markdown เปลี่ยนไปจากต้นฉบับ` | LLM แก้เกินกว่าคำสะกด เช่น เปลี่ยนตัวเลขหรือลบรหัสอ้างอิง |
| `ข้อความเปลี่ยนไปจากต้นฉบับมากเกินไป` | ความคล้ายกับต้นฉบับต่ำกว่า `MIN_SIMILARITY` ซึ่งมักเกิดจาก LLM เรียบเรียงประโยคใหม่ |
| `LLM ลบข้อความในบรรทัดนี้ออก` | LLM ส่งบรรทัดว่างกลับมาแทนบรรทัดที่มีข้อความ |

## รูปแบบ JSON ของคำขอและผลลัพธ์

mcp-thai-proofread มี 3 route

| Route | ใช้ทำอะไร |
|---|---|
| `POST /mcp` | เรียกเครื่องมือทั้งหมดตามมาตรฐาน MCP (JSON-RPC 2.0) agent ใช้ route นี้ |
| `GET /health` | ตรวจว่าการตั้งค่า LLM พร้อมใช้งานและเข้าถึง workspace ได้ ไม่ต้องใช้ token และไม่เรียก LLM จริง |
| `GET /usage` | ข้อมูลการใช้งาน: token เวลา และค่าใช้จ่ายของการเรียก LLM และการเรียกเครื่องมือทุกครั้ง (ใช้ token เดียวกับ `/mcp` หากกำหนด `MCP_AUTH_TOKEN`) |

### การส่งคำขอไปที่ `/mcp`

ทุกคำขอต้องมี header สองตัวนี้ (และ `Authorization: Bearer <token>` หากกำหนด `MCP_AUTH_TOKEN`)

```
Content-Type: application/json
Accept: application/json, text/event-stream
```

ผลลัพธ์จะส่งกลับในรูปแบบ Server-Sent Events คือมีบรรทัด `event: message` แล้วตามด้วย `data: <JSON>`
ตัวอย่างต่อไปนี้แสดงเฉพาะส่วน JSON และจัดบรรทัดใหม่ให้อ่านง่าย

ผลลัพธ์ของทุกเครื่องมืออยู่ใน `result.content[0].text` เป็นข้อความ JSON
ตัวอย่างด้านล่างจึงแสดงค่า `text` ในรูป JSON ที่แปลงกลับแล้ว เพื่อให้อ่านง่าย

### ดูรายการเครื่องมือ (`tools/list`)

คำขอ:

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

ผลลัพธ์ (ย่อ):

```json
{"jsonrpc": "2.0", "id": 1, "result": {"tools": [
  {
    "name": "proofread_thai",
    "description": "ตรวจและแก้คำสะกดภาษาไทยในไฟล์ใน workspace แล้วบันทึกทับไฟล์เดิม …",
    "inputSchema": {
      "type": "object",
      "properties": {
        "path":    {"type": "string", "description": "ตำแหน่งไฟล์เทียบกับราก workspace เช่น \"report.md\" … (รับเฉพาะไฟล์นามสกุล .md)"},
        "dry_run": {"type": "boolean", "default": false, "description": "true = ตรวจอย่างเดียว …"}
      },
      "required": ["path"]
    },
    "annotations": {"readOnlyHint": false, "destructiveHint": false, "openWorldHint": true}
  },
  {"name": "proofread_text", "…": "…"}
]}}
```

### ตรวจและแก้ไฟล์ (`proofread_thai`)

ไฟล์ `meeting.md` ที่ใช้ในตัวอย่าง:

```markdown
# รายงานการประชุม

ที่ประชุมอนุญาติให้ใช้งบประมาณ 2.5 ล้านบาท ตามข้อเสนอ [S1]
ผลลัพท์ของการทดลองแสดงว่ามีโอกาศสำเร็จสูง
```

คำขอ:

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
  "name": "proofread_thai",
  "arguments": {"path": "meeting.md"}
}}
```

ค่า `text` ในผลลัพธ์:

```json
{
  "ok": true,
  "file": "meeting.md",
  "model": "google/gemma-4-31b-it",
  "dry_run": false,
  "chunks": 1,
  "lines_changed": 2,
  "lines_rejected": 0,
  "suspect_before": 0,
  "suspect_after": 0,
  "errors": [],
  "seconds": 3.3,
  "backup": "backups/meeting.md.bak-proof-20261019-203654",
  "sample_changes": [
    {"before": "ที่ประชุมอนุญาติให้ใช้งบประมาณ 2.5 ล้านบาท ตามข้อเสนอ [S1]",
     "after":  "ที่ประชุมอนุญาตให้ใช้งบประมาณ 2.5 ล้านบาท ตามข้อเสนอ [S1]"},
    {"before": "ผลลัพท์ของการทดลองแสดงว่ามีโอกาศสำเร็จสูง",
     "after":  "ผลลัพธ์ของการทดลองแสดงว่ามีโอกาสสำเร็จสูง"}
  ],
  "log": "notes/proofread-meeting.md"
}
```

ตัวเลข `2.5` และรหัส `[S1]` ยังเหมือนเดิม `sample_changes` แสดงไม่เกิน 10 บรรทัดแรก ส่วนรายการทั้งหมดอยู่ในไฟล์ `log`
เมื่อส่ง `"dry_run": true` ผลลัพธ์จะไม่มี `backup` และ `log` แต่มี `changes` (พร้อมเลขบรรทัด) และ `rejected` แทน

### ตรวจข้อความ (`proofread_text`)

คำขอ:

```json
{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
  "name": "proofread_text",
  "arguments": {"text": "ผลลัพท์ของการทดลองแสดงว่ามีโอกาศสำเร็จสูง", "title": "รายงานการทดลอง"}
}}
```

ค่า `text` ในผลลัพธ์:

```json
{
  "ok": true,
  "model": "google/gemma-4-31b-it",
  "text": "ผลลัพธ์ของการทดลองแสดงว่ามีโอกาสสำเร็จสูง",
  "lines_changed": 1,
  "lines_rejected": 0,
  "changes": [
    {"line": 1, "before": "ผลลัพท์ของการทดลองแสดงว่ามีโอกาศสำเร็จสูง", "after": "ผลลัพธ์ของการทดลองแสดงว่ามีโอกาสสำเร็จสูง"}
  ],
  "rejected": [],
  "errors": []
}
```

รายการใน `rejected` มีรูปแบบ `{"line": 4, "reason": "<เหตุผล>", "before": "<ข้อความเดิม>", "suggested": "<ข้อความที่ LLM เสนอ>"}`

### ข้อผิดพลาด

| กรณี | ผลลัพธ์ |
|---|---|
| ไม่ส่ง token หรือ token ผิด (เมื่อกำหนด `MCP_AUTH_TOKEN`) | HTTP 401 `{"error": "unauthorized"}` |
| ไม่ส่งค่าที่จำเป็น | `"isError": true` และ `text` บอกชื่อค่าที่ขาด เช่น `path  Field required` |
| path อยู่นอก workspace | `{"ok": false, "error": "path must be inside the workspace"}` |
| นามสกุลไฟล์ไม่อยู่ใน `FILE_EXTENSIONS` | `{"ok": false, "error": "only .md files can be proofread"}` |
| ไม่พบไฟล์ | `{"ok": false, "error": "file not found: report.md"}` |
| ไม่มี workspace ทั้งสองแบบ | `{"ok": false, "error": "no workspace: mount WORKSPACE_DIR, or set the Hermes dashboard login …"}` |
| dashboard ปฏิเสธชื่อผู้ใช้หรือรหัสผ่าน | `{"ok": false, "error": "the Hermes dashboard refused HERMES_DASHBOARD_USER / HERMES_DASHBOARD_PASSWORD"}` |
| ติดต่อ dashboard ไม่ได้ | `{"ok": false, "error": "cannot reach the Hermes dashboard at http://… (URLError)"}` |
| API key ผิด | `"ok": false` และ `errors` มี `model call failed: HTTP 401 - check LLM_API_KEY in .env …` |
| ผู้ให้บริการ LLM ปฏิเสธ เช่น งบประมาณหมด | `"ok": false` และ `errors` มี `model call failed: HTTP 403 - the provider refused the request: <เหตุผลจากผู้ให้บริการ>` |
| LLM ส่งจำนวนบรรทัดกลับมาไม่ครบ | `errors` มี `บรรทัด 12-20: LLM ส่งกลับมา 7 บรรทัด แต่ต้องการ 9 บรรทัด จึงคงข้อความเดิมไว้` |

ทุกกรณีที่เรียก LLM ไม่สำเร็จ ช่วงนั้นจะคงข้อความเดิมไว้ ไฟล์จึงไม่เสียหาย

### ตรวจสถานะ (`GET /health`)

```json
{
  "ok": true,
  "model": "google/gemma-4-31b-it",
  "base_url": "https://openrouter.ai/api/v1",
  "key_configured": true,
  "workspace": {"mode": "hermes", "root": "/opt/data/workspace", "reachable": true},
  "usage_log": {"enabled": true, "dir": "/app/usage", "writable": true, "last_error": null},
  "auth": false,
  "problems": []
}
```

`workspace.mode` บอกโหมดที่ระบบเลือก (`hermes` หรือ `local` และเป็น `null` เมื่อไม่มี workspace) ส่วน `reachable` บอกว่าเข้าถึงได้จริงหรือไม่
ในโหมด `hermes` ค่านี้ได้จากการเข้าสู่ระบบ dashboard และเปิดโฟลเดอร์ workspace จริงหนึ่งครั้ง
หากไม่มี workspace เลย `proofread_text` ยังใช้งานได้ตามปกติ

เมื่อมีปัญหา `ok` จะเป็น `false` และ `problems` จะบอกสาเหตุพร้อมวิธีแก้ เช่น
`"LLM_API_KEY is still the example value from .env.example - put your real key in .env"`

### ข้อมูลการใช้งาน (`GET /usage`)

ระบบบันทึกการเรียก LLM ทุกครั้ง และสรุปของการเรียกเครื่องมือแต่ละครั้ง ลงไฟล์ `usage-<วันที่>.jsonl` ใน docker volume `usage`
เพื่อใช้วิจัยและปรับประสิทธิภาพ เช่น เทียบ model ผู้ให้บริการ หรือขนาดช่วงข้อความ (`CHUNK_CHARS`) ระเบียนมีเฉพาะจำนวน token ขนาด และเวลา ไม่มีข้อความที่ตรวจ

| ค่า | ความหมาย |
|---|---|
| `since`, `until` | ช่วงเวลา (epoch วินาที) หากไม่ระบุจะส่งทั้งหมด |
| `limit` | จำนวนระเบียนสูงสุด (ล่าสุด) ค่าเริ่มต้น 50000 |

ผลลัพธ์ของ `GET /usage?since=1792466000` (ย่อ):

```json
{
  "schema": "harness-usage/1",
  "environment": {"component": "mcp-thai-proofread", "version": "0.3.0", "host": "3f2a…", "cpu_count": 20, "mem_total_mb": 11816, "…": "…"},
  "records": [
    {"kind": "llm_call", "tool": "proofread_text", "request_id": "9c1e…", "model": "google/gemma-4-31b-it",
     "upstream_provider": "Google", "endpoint_host": "openrouter.ai", "duration_s": 2.015,
     "input_tokens": 480, "cache_read_tokens": 0, "output_tokens": 6, "reasoning_tokens": 0, "total_tokens": 486,
     "cost_usd": 5.004e-05, "output_tps": 2.98, "status": "ok", "detail": {"attempts": 1, "request_chars": 1342, "answer_chars": 17}},
    {"kind": "mcp_tool", "tool": "proofread_text", "request_id": "9c1e…", "duration_s": 2.019, "total_tokens": 486,
     "cost_usd": 5e-05, "status": "ok", "detail": {"llm_calls": 1, "llm_seconds": 2.015, "text_chars": 17, "chunks": 1, "lines_changed": 1}}
  ]
}
```

- `llm_call` หนึ่งระเบียนต่อการเรียก LLM หนึ่งครั้ง (หนึ่งช่วงข้อความ) ส่วน `mcp_tool` คือสรุปของการเรียกเครื่องมือหนึ่งครั้ง ทั้งสองใช้ `request_id` เดียวกัน
- ตัวเลข token และ `cost_usd` มาจากผู้ให้บริการ (OpenRouter รายงานค่าใช้จ่ายจริง) หากผู้ให้บริการไม่รายงาน ค่าจะเป็น `null`
- ชื่อช่องข้อมูลเป็นแบบเดียวกับ plugin `usage-telemetry` ของ [harness-server](https://github.com/chacharin/harness-server) และ MCP ตัวอื่นของชุดนี้ จึงรวมเป็นชุดข้อมูลเดียวกันได้

### ทดลองด้วย curl

```bash
curl http://127.0.0.1:8805/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"proofread_text","arguments":{"text":"มีโอกาศสำเร็จสูง"}}}'
```

บน Windows คำสั่ง curl อาจส่งภาษาไทยที่พิมพ์ในบรรทัดคำสั่งผิดเพี้ยนเป็น `?` ให้บันทึก JSON ของคำขอเป็นไฟล์ UTF-8 เช่น `request.json` แล้วส่งด้วย `-d @request.json` แทน

## การปรับให้เหมาะกับงานของคุณ

ค่าต่อไปนี้เป็นตัวแปรในไฟล์ `.env` ซึ่งไม่จำเป็นต้องกำหนด หากไม่กำหนด ระบบจะใช้ค่าเริ่มต้น
เมื่อต้องการปรับ ให้เพิ่มบรรทัด `ชื่อตัวแปร=ค่า` ลงในไฟล์ `.env` แล้วสั่ง `docker compose up -d` (คำอธิบายและค่าเริ่มต้นของทุกตัวแปรดูได้ใน [`.env.example`](.env.example))

- **`PROTECTED_REGEX`** regex ของรหัสที่ห้ามเปลี่ยน ค่าเริ่มต้นตรวจรหัสอ้างอิงรูปแบบ `[S1]` `[F12]` และรวมหลายรูปแบบได้ด้วย `|` เช่น `\[[A-Z]{1,3}\d+\]|มาตรา\s?\d+`
- **`MIN_SIMILARITY`** เกณฑ์ความคล้ายกับต้นฉบับ (0–1) ค่ายิ่งสูง ระบบยิ่งเข้มงวดกับการแก้ไขที่เปลี่ยนข้อความมาก
- **`CHUNK_CHARS`, `CONTEXT_LINES` และ `WORKERS`** ขนาดของแต่ละช่วงที่ส่งให้ LLM จำนวนบรรทัดบริบท และจำนวนช่วงที่ส่งพร้อมกัน หากพบ rate limit (HTTP 429) บ่อย ให้ลด `WORKERS`
- **`FILE_EXTENSIONS`, `OUTPUT_PLACEMENT`, `BACKUP_SUBDIR` และ `NOTES_SUBDIR`** นามสกุลไฟล์ที่แก้ได้ และตำแหน่งของไฟล์สำรองกับบันทึกการแก้ไข
- **`USAGE_LOG` และ `USAGE_DIR`** เปิด/ปิดการบันทึกข้อมูลการใช้งาน และโฟลเดอร์ที่เก็บ (ดู[ข้อมูลการใช้งาน](#ข้อมูลการใช้งาน-get-usage))
- **`LLM_EXTRA_PARAMS`** ค่าเพิ่มเติมที่ส่งไปกับทุกคำขอถึง LLM ในรูปแบบ JSON เช่น `{"top_p": 0.9}` หรือการเลือก provider ของ OpenRouter `{"provider": {"order": ["google-vertex"]}}`

### การปรับ prompt

prompt ที่มากับระบบเป็นแบบทั่วไป มีเนื้อหาเดียวกับไฟล์ [`prompts/system_prompt.example.md`](prompts/system_prompt.example.md) หากต้องการปรับให้เหมาะกับงาน เช่น เอกสารราชการ กฎหมาย หรือการแพทย์:

```bash
cp prompts/system_prompt.example.md prompts/system_prompt.md   # จากนั้นแก้ไขไฟล์นี้
echo "SYSTEM_PROMPT_FILE=/app/prompts/system_prompt.md" >> .env
docker compose up -d
```

prompt ที่แก้ไขแล้วยังต้องสั่งให้ LLM **ส่งกลับเฉพาะบรรทัดที่ต้องตรวจ ในจำนวนและลำดับเดิม โดยไม่มีคำอธิบายเพิ่มเติม** มิฉะนั้นระบบจะปฏิเสธการแก้ไขของช่วงนั้นทั้งหมด
ไฟล์ในโฟลเดอร์ `prompts/` ที่ไม่ใช่ `*.example.md` จะไม่ถูก commit เนื่องจากอาจมีชื่อองค์กรอยู่

## ความปลอดภัย

- **ค่าเริ่มต้นไม่มีการยืนยันตัวตน** และเปิดพอร์ต 8805 ให้เครื่องอื่นในเครือข่ายเข้าถึงได้ (`PUBLISH_ADDR=0.0.0.0`) ผู้ที่เข้าถึงพอร์ตนี้ได้จะสั่งแก้ไฟล์ใน workspace และใช้โควตา LLM ของคุณได้ทันที
  หากไม่จำเป็น ให้กำหนด `PUBLISH_ADDR=127.0.0.1` ซึ่ง agent ที่อยู่ใน docker network เดียวกันจะยังเรียกใช้ได้ตามปกติ หรือกำหนด `MCP_AUTH_TOKEN` เพื่อบังคับให้ผู้เรียกต้องส่ง token
- ทั้งสองโหมดเขียนไฟล์ได้ เพราะเครื่องมือต้องแก้ไฟล์ ระบบรับเฉพาะ path ที่อยู่ภายใน workspace และทุกการแก้ไขจะมีไฟล์สำรองเสมอ
- ในโหมด `hermes` รหัสผ่าน dashboard เปิดสิทธิ์ทั้งหน้า dashboard ของ Hermes ไม่ใช่เฉพาะไฟล์ จึงควรเก็บไว้ใน `.env` เท่านั้น และเมื่อ server อยู่คนละเครื่องกับ Hermes ควรเชื่อมผ่าน HTTPS หรือเครือข่ายส่วนตัว (VPN) เพื่อไม่ให้รหัสผ่านและเนื้อหาไฟล์ถูกส่งแบบไม่เข้ารหัส
  API ไฟล์ของ Hermes ไม่ยอมให้อ่านไฟล์ค่าลับ เช่น `.env` อยู่แล้ว และระบบนี้เรียกเฉพาะไฟล์ภายใต้ `HERMES_WORKSPACE`
- API key ของ LLM ถูกเก็บไว้ในไฟล์ `.env` เท่านั้น ไม่ถูกส่งให้ agent และไฟล์นี้จะไม่ถูกส่งขึ้น git
- ข้อมูลการใช้งาน (`/usage`) ไม่มีข้อความที่ตรวจ มีเฉพาะจำนวน token ขนาด เวลา และชื่อไฟล์ไม่ถูกบันทึก แต่ยังบอกปริมาณการใช้งานได้ จึงใช้ token เดียวกับ `/mcp` เมื่อกำหนด `MCP_AUTH_TOKEN`

## สำหรับนักพัฒนา

โค้ดหลักอยู่ในโฟลเดอร์ `app/`

| ไฟล์ | หน้าที่ |
|---|---|
| `config.py` | อ่านและตรวจสอบการตั้งค่าจาก `.env` |
| `proofread.py` | แบ่งเอกสารเป็นช่วง สร้าง prompt เรียก LLM และตรวจคำตอบของ LLM |
| `prompt.py` | system prompt ที่มากับระบบ |
| `server.py` | MCP server เครื่องมือทั้งหมด `/health` การตรวจ token และการจัดการไฟล์ (ตรวจตำแหน่งไฟล์ สำรองไฟล์ เขียนบันทึก) |
| `workspace.py` | การเข้าถึง workspace ทั้งสองโหมด: โฟลเดอร์ที่ mount ไว้ (`local`) และ API ไฟล์ของ dashboard ของ Hermes (`hermes`) |
| `usage.py` | บันทึกและอ่านข้อมูลการใช้งาน (`/usage`) |
| `selftest.py` | ทดสอบหลังติดตั้ง (เรียก LLM จริง) |

ชุดทดสอบในโฟลเดอร์ `tests/` ใช้ LLM จำลอง จึงไม่ต้องมี LLM จริงและไม่เสียค่าใช้จ่าย สั่งทดสอบผ่าน Docker ได้โดยไม่ต้องติดตั้ง Python:

```bash
docker run --rm -v "$PWD:/w" -w /w -e UV_PROJECT_ENVIRONMENT=/tmp/venv python:3.12-slim \
  sh -c "pip install -q uv==0.13.1 && uv run --frozen pytest -q -p no:cacheprovider"
```

หากติดตั้ง [uv](https://docs.astral.sh/uv/) ไว้บนเครื่อง สั่ง `uv run pytest` ได้เลย

ไลบรารีทุกตัวถูกล็อกเวอร์ชันไว้ใน `uv.lock` หากแก้ `pyproject.toml` ให้เปลี่ยน `uv run --frozen pytest ...` ในคำสั่งข้างต้นเป็น `uv lock` แล้ว commit ไฟล์ `uv.lock` ที่เปลี่ยนไป
หากใช้ PowerShell ให้เปลี่ยน `$PWD` เป็น `${PWD}` และใช้ `` ` `` แทน `\` สำหรับขึ้นบรรทัดใหม่

## สัญญาอนุญาต

[MIT](LICENSE) © 2026 Chacharin Lertyosbordin
