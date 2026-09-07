"""
Apple 메모(상담 지식)를 임베딩하여 data/vectors_notes.db 생성

사용처:
  EC2 컨테이너 내부에서 실행 (sentence-transformers 모델 사용)
    docker exec littlelabs-qna python build_notes_vector_db.py

입력:
  data/notes_raw.json  — Apple 메모에서 추출한 Q&A 지식 원본
    형식: [{"title": str, "folder": str, "content": str}, ...]

청킹 규칙:
  - "—————" 구분선 및 "<주제>" 헤더 기준으로 주제 단위 분할
  - 각 청크에 "[주제] {title}" 프리픽스 부여 (기존 chunk_text 포맷과 일관)
  - 브랜드 철학(마케팅 전략) 메모는 제외

스키마: 기존 vectors_*.db의 chunks 테이블과 동일
  (id, inquiry_id, chunk_text, product_name, subject, is_answered, embedding)
  embedding: 384차원 float32 (paraphrase-multilingual-MiniLM-L12-v2, normalized)
"""

import json
import os
import re
import sqlite3
import struct
import sys

DB_PATH = "data/vectors_notes.db"
RAW_PATH = "data/notes_raw.json"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EXCLUDED_TITLES = {"브랜드 철학"}  # 마케팅 내부 전략 문서 — 상담 지식에서 제외
MIN_CHUNK_LEN = 120  # 너무 짧은 조각(링크 목록 등) 제외


def init_db(conn: sqlite3.Connection):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inquiry_id TEXT,
            chunk_text TEXT,
            product_name TEXT,
            subject TEXT,
            is_answered TEXT,
            embedding BLOB
        );
        """
    )


def split_into_chunks(title: str, content: str) -> list:
    """주제 구분선/헤더 기준 분할 후, 길이 기준으로 과대 청크 재분할."""
    # 구분선(— 3개 이상)으로 1차 분할
    parts = re.split(r"\s*-{3,}\s*", content)
    chunks = []
    for part in parts:
        part = part.strip()
        if len(part) < MIN_CHUNK_LEN:
            continue
        # 1500자 초과 시 문단 경계로 재분할 (1200자 목표, 약간 겹침 없이)
        if len(part) > 1500:
            paragraphs = re.split(r"\n\s*\n", part)
            buf = ""
            for p in paragraphs:
                if len(buf) + len(p) > 1200 and buf:
                    chunks.append(buf.strip())
                    buf = p
                else:
                    buf = (buf + "\n\n" + p).strip()
            if buf.strip():
                chunks.append(buf.strip())
        else:
            chunks.append(part)

    # 프리픽스: 청크 내 "<주제>" 헤더가 있으면 그것을 제목으로 사용
    out = []
    for c in chunks:
        m = re.match(r"<([^>]+)>", c)
        subject = m.group(1).strip() if m else title
        text = f"[주제] {subject}\n{c}"
        out.append({"subject": subject, "chunk_text": text})
    return out


def main():
    if not os.path.exists(RAW_PATH):
        print(f"오류: {RAW_PATH} 파일이 없습니다. 먼저 Apple 메모 추출 결과를 배치하세요.")
        sys.exit(1)

    notes = json.load(open(RAW_PATH, encoding="utf-8"))
    notes = [n for n in notes if n.get("title") not in EXCLUDED_TITLES]
    print(f"대상 메모: {[n['title'] for n in notes]}")

    records = []
    for n in notes:
        for c in split_into_chunks(n["title"], n.get("content", "")):
            records.append({
                "inquiry_id": f"note_{n['title']}_{records.__len__()}",
                "chunk_text": c["chunk_text"],
                "product_name": "메모지식",  # retriever의 source_boost 대상 아님(일반 청크 취급)
                "subject": c["subject"],
                "is_answered": "1",
            })
    print(f"생성 청크 수: {len(records)}")

    from sentence_transformers import SentenceTransformer
    print(f"임베딩 모델 로딩: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    cur = conn.cursor()

    # 재실행 시 중복 방지: 기존 메모지식 청크 삭제 후 재삽입
    cur.execute("DELETE FROM chunks WHERE product_name = '메모지식'")

    texts = [r["chunk_text"] for r in records]
    print("임베딩 생성 중...")
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    for r, emb in zip(records, embeddings):
        cur.execute(
            "INSERT INTO chunks (inquiry_id, chunk_text, product_name, subject, is_answered, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                r["inquiry_id"],
                r["chunk_text"],
                r["product_name"],
                r["subject"],
                r["is_answered"],
                struct.pack(f"{len(emb)}f", *emb.tolist()),
            ),
        )

    cur.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('embedding_dim', ?)", (str(len(embeddings[0])),))
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM chunks")
    print(f"완료: {DB_PATH} 총 {cur.fetchone()[0]} 청크")
    conn.close()


if __name__ == "__main__":
    main()
