"""文档管理路由：上传（解析+切分+向量化）、删除。"""
import datetime
import uuid

from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException

from app.loader import load_file
from app.vectorstore import add_chunks, delete_document

router = APIRouter(prefix="/kb", tags=["document"])


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    user_id: int = Form(...),
    library_id: int = Form(...),
):
    data = await file.read()
    filename = file.filename or "unknown"
    try:
        chunks = load_file(filename, data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文档解析失败：{e}")
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="文档没有可解析的文本内容，可能为扫描版 PDF、图片或空文件，请上传包含可检索文本的 PDF / Word / Excel / Markdown / TXT"
        )

    doc_id = str(uuid.uuid4())
    for c in chunks:
        c["doc_id"] = doc_id
        c["id"] = f"{doc_id}_{c['id']}"

    try:
        add_chunks(library_id, chunks)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"向量化入库失败：{e}")

    return {
        "docId": doc_id,
        "filename": filename,
        "chunkCount": len(chunks),
        "status": "ready",
        "createdAt": datetime.datetime.now().isoformat(),
    }


@router.delete("/documents/{doc_id}")
def delete_document_api(
    doc_id: str,
    user_id: int = Query(..., description="调用方用户ID（与 library_id 用于权限校验，向量清理仅依赖 library_id+doc_id）"),
    library_id: int = Query(..., description="知识库ID，决定清哪个 Chroma collection"),
):
    try:
        delete_document(library_id, doc_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除向量失败：{e}")
    return {"deleted": True}
