"""腾讯云向量库连通性自测脚本（排错专用，可长期保留）。

============================================================================
用途
============================================================================
不依赖 kb-server 进程，直接调用 ``kb.kb.vectorstore_tencent`` 底层接口，
独立验证「kb 服务 → 腾讯云向量库」的连通性与基本读写/检索能力：

  1. 验证 ``.env`` 的腾讯云配置是否被 ``kb.config`` 正确读取；
  2. 验证能否连上向量库、能否拿到 database、列出 collection；
  3. 验证全链路：
        add_chunks  →  服务端 multilingual-e5-base 自动向量化入库
        query       →  服务端 embedding 语义检索召回
        delete_document → 按 doc_id 清理
        count_chunks / get_library_stats → 统计一致
  4. 打印每一步的耗时与结果，方便定位是哪一层出问题。

============================================================================
使用方法
============================================================================
在仓库根目录 ``kb/`` 下，用运行 kb-server 的同一个 Python 环境执行：

    # 用默认测试库 990001（仅写入一条 __selftest__ 临时文档，结束后删除）
    python scripts/test_tencent_conn.py

    # 验证某个真实知识库（注意：会在该库写入并删除一条测试文档）
    python scripts/test_tencent_conn.py --library-id 7

    # 同时顺带验证 chroma 后端能否正常工作（可选）
    python scripts/test_tencent_conn.py --also-chroma

说明：
  * 脚本只写入一条带特殊前缀 ``__selftest__`` 的临时文档，测试结束会删除它，
    不会 drop 任何 collection，也不会影响真实数据。
  * 脚本会把 ``VECTOR_BACKEND`` 临时切到 ``tencent`` 做本次测试，
    不会修改 ``.env`` 文件。
  * 若 ``tcvectordb`` 未安装或网络不通，脚本会在对应步骤明确报错并给出修复提示。

退出码：0 = 全部通过；1 = 存在失败项。
"""
from __future__ import annotations

import os
import sys
import time
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# 让脚本能 import 到 kb 包：本仓库的 kb 包位于 <repo_root>/kb/ 目录，
# 其包名恰好也是 ``kb``（见 kb/kb/pyproject.toml 的 package-dir 映射）。
# 把 repo_root 加入 sys.path 后即可 ``import kb`` 解析到 kb/kb/。
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kb.config import settings  # noqa: E402


# ---------------------------------------------------------------------------
# 简单的结果收集器
# ---------------------------------------------------------------------------
_RESULTS: list[tuple[str, bool, str]] = []


def _step(name: str, ok: bool, detail: str = "") -> bool:
    _RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def _timed(fn):
    """执行 fn 并返回 (ok, detail)，记录耗时。"""
    t0 = time.perf_counter()
    try:
        detail = fn()
        cost = (time.perf_counter() - t0) * 1000
        return True, f"{detail}  ({cost:.0f}ms)"
    except Exception as e:  # noqa: BLE001
        cost = (time.perf_counter() - t0) * 1000
        return False, f"{type(e).__name__}: {e}  ({cost:.0f}ms)"


def main() -> int:
    parser = argparse.ArgumentParser(description="腾讯云向量库连通性自测")
    parser.add_argument("--library-id", type=int, default=990001,
                        help="用于测试的知识库 ID（默认 990001 测试库）")
    parser.add_argument("--also-chroma", action="store_true",
                        help="额外验证 chroma 后端能否正常工作")
    args = parser.parse_args()

    library_id = args.library_id
    print("=" * 70)
    print("腾讯云向量库连通性自测")
    print("=" * 70)

    # ---- 0. 配置检查 -------------------------------------------------------
    print("\n[0] 当前 .env 配置（kb.config.Settings）")
    print(f"    VECTOR_BACKEND        = {settings.vector_backend}")
    print(f"    TENCENT_VECTOR_URL    = {settings.tencent_vector_url}")
    print(f"    TENCENT_VECTOR_USER   = {settings.tencent_vector_username}")
    print(f"    TENCENT_VECTOR_KEY    = {'***已配置***' if settings.tencent_vector_key else '<空>'}")
    print(f"    TENCENT_VECTOR_DB     = {settings.tencent_vector_database}")
    print(f"    TENCENT_EMBEDDING     = {settings.tencent_embedding_model}")
    print(f"    TENCENT_VECTOR_DIM    = {settings.tencent_vector_dim}")

    # 临时强制切到 tencent 后端做本次测试，不改 .env
    settings.vector_backend = "tencent"

    from kb import vectorstore_tencent as vs  # noqa: E402

    # ---- 1. 连通 + 列 collection ------------------------------------------
    print("\n[1] 连接向量库 / 获取 database / 列出 collection")

    def _connect():
        client = vs._get_client()
        db = vs._get_db()
        try:
            cols = client.list_collections(database_name=settings.tencent_vector_database)
            col_names = [c.name if hasattr(c, "name") else str(c) for c in (cols or [])]
        except Exception:
            col_names = ["(无法列出 collection，但不影响后续自建)"]
        return f"database={db.database_name if hasattr(db, 'database_name') else '?'}；collection 数={len(col_names)}"

    ok, detail = _timed(_connect)
    _step("向量库连通", ok, detail)

    # ---- 2. add_chunks ----------------------------------------------------
    print("\n[2] add_chunks（服务端 multilingual-e5-base 自动向量化）")
    doc_id = f"__selftest__{int(time.time())}"
    sample_texts = [
        "客户退货流程：先联系在线客服，填写退货申请表，寄回商品后 3 个工作日退款。",
        "本产品提供一年质保，非人为损坏可免费维修或更换。",
        "会员等级分为普通会员、银卡、金卡，金卡享受 9 折优惠。",
    ]
    chunks = [
        {
            "id": f"{doc_id}_{i}",
            "text": t,
            "doc_id": doc_id,
            "filename": "self_test_sample.txt",
        }
        for i, t in enumerate(sample_texts)
    ]

    def _add():
        vs.add_chunks(library_id, chunks)
        return f"已写入 {len(chunks)} 条（doc_id={doc_id}）"

    ok, detail = _timed(_add)
    _step("add_chunks 入库", ok, detail)
    if not ok:
        return _finalize()

    # ---- 3. count / stats --------------------------------------------------
    print("\n[3] count_chunks / get_library_stats")
    try:
        count = vs.count_chunks(library_id)
        stats = vs.get_library_stats(library_id)
        _step("统计读取", True, f"chunk_count={count}；stats={stats}")
    except Exception as e:  # noqa: BLE001
        _step("统计读取", False, f"{type(e).__name__}: {e}")

    # ---- 4. query（语义检索） ----------------------------------------------
    print("\n[4] query 语义检索（服务端 embedding）")
    for q in ["怎么办理退货？", "会员有折扣吗？"]:
        def _query(q=q):
            hits = vs.query(library_id, q, top_k=3)
            if not hits:
                raise RuntimeError("检索返回空，可能向量库索引尚未就绪或服务端 embedding 异常")
            return f"命中 {len(hits)} 条，首条前 40 字：{hits[0]['text'][:40]}"
        ok, detail = _timed(lambda q=q: _query(q))
        _step(f"query「{q}」", ok, detail)

    # ---- 5. get_document_chunks -------------------------------------------
    print("\n[5] get_document_chunks（按 doc_id 取回切片）")
    try:
        dc = vs.get_document_chunks(library_id, doc_id)
        _step("取回测试文档切片", len(dc) == len(chunks),
              f"切片数={len(dc)}（期望 {len(chunks)}）")
    except Exception as e:  # noqa: BLE001
        _step("取回测试文档切片", False, f"{type(e).__name__}: {e}")

    # ---- 6. delete_document + 清理校验 ------------------------------------
    print("\n[6] delete_document 清理测试数据")
    def _del():
        vs.delete_document(library_id, doc_id)
        remain = vs.get_document_chunks(library_id, doc_id)
        if remain:
            raise RuntimeError(f"删除后仍有 {len(remain)} 条残留")
        return f"已删除 doc_id={doc_id}"
    ok, detail = _timed(_del)
    _step("删除并校验", ok, detail)

    # ---- 7.（可选）chroma 后端 --------------------------------------------
    if args.also_chroma:
        print("\n[7] 可选：验证 chroma 后端")
        settings.vector_backend = "chroma"
        try:
            from kb import vectorstore_chroma as vsc
            vsc.add_chunks(library_id, chunks)
            hits = vsc.query(library_id, "退货流程", top_k=2)
            vsc.delete_document(library_id, doc_id)
            _step("chroma 后端读写", bool(hits), f"命中 {len(hits)} 条")
        except Exception as e:  # noqa: BLE001
            _step("chroma 后端读写", False, f"{type(e).__name__}: {e}")

    return _finalize()


def _finalize() -> int:
    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    print(f"结果：{passed}/{total} 通过")
    fails = [n for n, ok, _ in _RESULTS if not ok]
    if fails:
        print("失败项：")
        for n in fails:
            print(f"  - {n}")
        print("\n常见修复提示：")
        print("  * 连不通：检查 TENCENT_VECTOR_URL/KEY/USERNAME，确认网络可达、密钥正确")
        print("  * ImportError: 执行 pip install --no-deps tcvectordb "
              "&& pip install --no-deps cos-python-sdk-v5 && pip install ujson cachetools")
        print("  * 维基/索引错误：确认 TENCENT_VECTOR_DIM 与所选 embedding 模型维度一致")
        print("=" * 70)
        return 1
    print("全部通过 [OK]")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
