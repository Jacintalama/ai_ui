"""Generate .docx/.pdf from a markdown subset. Internal-only (X-Internal-Secret,
same gate as fusion); consumed by the "Documents" native OWUI tool. Content is
never logged - the log line carries only format and byte sizes."""
import base64
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from doc_builder import blocks_to_docx, blocks_to_pdf, blocks_to_pptx, parse_blocks
from routes_fusion import _require_internal

router = APIRouter(prefix="/files")

MAX_MD_BYTES = 200_000
MAX_OUT_BYTES = 5_000_000
MIMES = {
    "docx": ("application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document"),
    "pdf": "application/pdf",
    "pptx": ("application/vnd.openxmlformats-officedocument"
             ".presentationml.presentation"),
}
BUILDERS = {"docx": blocks_to_docx, "pdf": blocks_to_pdf, "pptx": blocks_to_pptx}


def build_filename(title: str, fmt: str, now: datetime = None) -> str:
    base = re.sub(r"[^\w\-]", "_", (title or "").strip()) or "document"
    ts = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{base[:80]}_{ts}.{fmt}"


class GenerateBody(BaseModel):
    title: str = Field(default="", max_length=150)
    markdown: str = Field(min_length=1)
    format: Literal["docx", "pdf", "pptx"]


@router.post("/generate")
async def generate_file(body: GenerateBody,
                        x_internal_secret: str = Header(default="")):
    _require_internal(x_internal_secret)
    if len(body.markdown.encode("utf-8")) > MAX_MD_BYTES:
        raise HTTPException(status_code=413,
                            detail="Document text is too long (200 KB max).")
    blocks = parse_blocks(body.markdown)
    try:
        data = BUILDERS[body.format](body.title, blocks)
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Could not build the {body.format}: {e}")
    if len(data) > MAX_OUT_BYTES:
        raise HTTPException(status_code=413,
                            detail="Generated file exceeds 5 MB.")
    print(f"[files] generated {body.format} "
          f"({len(body.markdown)} chars in, {len(data)} bytes out)", flush=True)
    return {"filename": build_filename(body.title, body.format),
            "b64": base64.b64encode(data).decode("ascii"),
            "size": len(data),
            "mime": MIMES[body.format]}
