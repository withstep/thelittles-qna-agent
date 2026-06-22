"""
littlelabs-qna-agent: SQL 데이터를 chunking + embedding하여 SQLite 벡터 DB 생성

처리 흐름:
1. SQL 덤프 파일에서 INSERT 데이터를 파싱
2. 각 상담 레코드를 의미 있는 chunk로 분할
3. sentence-transformers로 한국어 임베딩 생성
4. SQLite DB에 원본 데이터 + 벡터 저장
"""

import sqlite3
import re
import json
import struct
import os
import sys
import html
from pathlib import Path

# ============================================================
# 1. SQL INSERT 파서
# ============================================================

def clean_html(text: str) -> str:
    """HTML 태그 제거 및 엔티티 디코딩"""
    if not text:
        return ""
    # HTML 엔티티 디코딩
    text = html.unescape(text)
    # HTML 태그 제거
    text = re.sub(r'<[^>]+>', '', text)
    # \\r\\n -> 실제 줄바꿈
    text = text.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
    # 연속 공백/줄바꿈 정리
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def parse_sql_value(val: str) -> str:
    """SQL 값 문자열 파싱 (따옴표 제거, 이스케이프 처리)"""
    val = val.strip()
    if val.upper() == 'NULL':
        return ''
    if val.startswith("'") and val.endswith("'"):
        val = val[1:-1]
        # MySQL 이스케이프 처리
        val = val.replace("\\'", "'")
        val = val.replace('\\"', '"')
        val = val.replace('\\\\', '\\')
        return val
    return val


def parse_insert_values(sql_content: str):
    """
    INSERT INTO ... VALUES (...), (...), ...; 형태의 SQL에서
    각 레코드를 파싱합니다.
    
    대용량 파일을 위해 라인 단위로 처리합니다.
    """
    # 컬럼 순서 (SQL 파일에서 확인됨)
    columns = [
        'wr_id', 'wr_num', 'wr_reply', 'wr_parent', 'wr_is_comment',
        'wr_comment', 'wr_comment_reply', 'ca_name', 'wr_option',
        'wr_subject', 'wr_content', 'wr_link1', 'wr_link2',
        'wr_link1_hit', 'wr_link2_hit', 'wr_hit', 'wr_good', 'wr_nogood',
        'mb_id', 'wr_password', 'wr_name', 'wr_email', 'wr_homepage',
        'wr_datetime', 'wr_file', 'wr_last', 'wr_ip',
        'wr_facebook_user', 'wr_twitter_user',
        'wr_1', 'wr_2', 'wr_3', 'wr_4', 'wr_5', 'wr_6', 'wr_7',
        'wr_8', 'wr_9', 'wr_10', 'wr_trackback',
        'wr_qna', 'wr_qna_ok', 'wr_qna_html', 'wr_admin', 'date2', 'wr_is_temp'
    ]
    
    records = []
    
    # 괄호 단위로 레코드 추출 (정규식 대신 상태 머신 사용)
    # INSERT ... VALUES 뒤의 각 (...) 를 추출
    
    in_values = False
    buffer = ""
    
    for line in sql_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('--') or line.startswith('/*') or line.startswith('SET ') or line.startswith('CREATE ') or line.startswith('/*!'):
            continue
        
        if line.startswith('INSERT INTO'):
            in_values = True
            # 기존 버퍼 처리
            if buffer:
                records.extend(extract_records_from_buffer(buffer, columns))
            # VALUES 이후 부분 추출
            values_idx = line.find('VALUES')
            if values_idx == -1:
                values_idx = line.find('values')
            if values_idx != -1:
                buffer = line[values_idx + 6:].strip()
            continue
        
        if in_values:
            buffer += ' ' + line
    
    if buffer:
        records.extend(extract_records_from_buffer(buffer, columns))
        
    return records


def extract_records_from_buffer(buffer: str, columns: list) -> list:
    """버퍼에서 괄호로 감싸진 레코드를 추출합니다."""
    records = []
    i = 0
    n = len(buffer)
    
    while i < n:
        # '(' 찾기
        while i < n and buffer[i] != '(':
            i += 1
        if i >= n:
            break
        
        i += 1  # '(' 스킵
        
        # 이 괄호 안의 값들을 추출
        values = []
        current_val = ""
        in_string = False
        depth = 0
        
        while i < n:
            ch = buffer[i]
            
            if in_string:
                if ch == '\\' and i + 1 < n:
                    current_val += ch + buffer[i + 1]
                    i += 2
                    continue
                elif ch == "'":
                    # 연속 따옴표 체크 (MySQL 이스케이프)
                    if i + 1 < n and buffer[i + 1] == "'":
                        current_val += "''"
                        i += 2
                        continue
                    in_string = False
                    current_val += ch
                    i += 1
                    continue
                else:
                    current_val += ch
                    i += 1
                    continue
            
            if ch == "'":
                in_string = True
                current_val += ch
                i += 1
                continue
            
            if ch == '(':
                depth += 1
                current_val += ch
                i += 1
                continue
            
            if ch == ')':
                if depth > 0:
                    depth -= 1
                    current_val += ch
                    i += 1
                    continue
                else:
                    # 레코드 종료
                    values.append(parse_sql_value(current_val.strip()))
                    i += 1
                    break
            
            if ch == ',' and depth == 0:
                values.append(parse_sql_value(current_val.strip()))
                current_val = ""
                i += 1
                continue
            
            current_val += ch
            i += 1
        
        # 값들을 컬럼에 매핑
        if len(values) >= len(columns):
            record = dict(zip(columns, values[:len(columns)]))
            records.append(record)
        elif len(values) > 0:
            # 컬럼 수가 맞지 않아도 가능한 만큼 매핑
            record = dict(zip(columns[:len(values)], values))
            records.append(record)
    
    return records


# ============================================================
# 2. Chunking 전략
# ============================================================

def create_chunks_from_record(record: dict) -> list:
    """
    하나의 상담 레코드에서 의미 있는 chunk들을 생성합니다.
    
    Chunk 유형:
    1. qa_pair: 질문-답변 쌍 (핵심 chunk)
    2. health_info: 건강정보 (성별, 나이, 관심분야, 임산부 여부 등)
    3. checklist: 체크리스트 정보 (상담 카테고리만)
    4. product_info: 제품 관련 정보 (현재 섭취 제품, 관심 제품)
    """
    chunks = []
    wr_id = record.get('wr_id', '')
    ca_name = record.get('ca_name', '')
    wr_subject = record.get('wr_subject', '')
    wr_content = clean_html(record.get('wr_content', ''))
    wr_qna = clean_html(record.get('wr_qna', ''))
    wr_name = record.get('wr_name', '')
    wr_datetime = record.get('wr_datetime', '')
    wr_qna_ok = record.get('wr_qna_ok', '0')
    
    # 댓글은 건너뛰기
    if record.get('wr_is_comment', '0') != '0':
        return chunks
    
    # 질문이나 답변이 비어있으면 건너뛰기
    if not wr_content and not wr_qna:
        return chunks
    
    # 건강정보 구성
    gender = record.get('wr_1', '')
    wr_2 = record.get('wr_2', '')
    age_parts = wr_2.split('|') if wr_2 else ['']
    age = age_parts[0] if age_parts else ''
    age_detail = age_parts[1] if len(age_parts) > 1 and age_parts[1] else ''
    
    wr_3 = record.get('wr_3', '')
    interests = [x for x in wr_3.split('|') if x] if wr_3 else []
    
    wr_4 = record.get('wr_4', '')
    pregnancy_parts = wr_4.split('|') if wr_4 else ['']
    pregnancy = pregnancy_parts[0] if pregnancy_parts else ''
    
    wr_5 = record.get('wr_5', '')  # 체중
    wr_6 = record.get('wr_6', '')  # 현재 섭취 제품
    wr_7 = record.get('wr_7', '')  # 관심 제품
    wr_10 = record.get('wr_10', '')  # 상태
    
    # 건강정보 텍스트 구성
    health_info_parts = []
    if gender:
        health_info_parts.append(f"성별: {gender}")
    if age:
        age_str = f"나이: {age}"
        if age_detail:
            age_str += f" ({age_detail})"
        health_info_parts.append(age_str)
    if interests:
        health_info_parts.append(f"관심분야: {', '.join(interests)}")
    if pregnancy:
        health_info_parts.append(f"임산부/수유부: {pregnancy}")
    if wr_5:
        health_info_parts.append(f"체중: {wr_5}")
    
    health_info_text = '; '.join(health_info_parts) if health_info_parts else ''
    
    # 제품 정보
    product_parts = []
    if wr_6:
        product_parts.append(f"현재 섭취중: {wr_6}")
    if wr_7:
        product_parts.append(f"관심 제품: {wr_7}")
    product_text = '; '.join(product_parts)
    
    # --- Chunk 1: QA 쌍 (핵심) ---
    if wr_content or wr_qna:
        qa_text_parts = []
        qa_text_parts.append(f"[제목] {wr_subject}")
        if ca_name:
            qa_text_parts.append(f"[카테고리] {ca_name}")
        if health_info_text:
            qa_text_parts.append(f"[건강정보] {health_info_text}")
        if product_text:
            qa_text_parts.append(f"[제품정보] {product_text}")
        if wr_content:
            qa_text_parts.append(f"[질문] {wr_content}")
        if wr_qna:
            qa_text_parts.append(f"[답변] {wr_qna}")
        
        qa_text = '\n'.join(qa_text_parts)
        
        # 토큰 수 제한 (약 512 토큰 ≈ 1500자 한국어 기준)
        # 너무 긴 경우 분할
        if len(qa_text) > 2000:
            # 질문 chunk
            q_text_parts = []
            q_text_parts.append(f"[제목] {wr_subject}")
            if ca_name:
                q_text_parts.append(f"[카테고리] {ca_name}")
            if health_info_text:
                q_text_parts.append(f"[건강정보] {health_info_text}")
            if product_text:
                q_text_parts.append(f"[제품정보] {product_text}")
            if wr_content:
                q_text_parts.append(f"[질문] {wr_content}")
            
            q_text = '\n'.join(q_text_parts)
            chunks.append({
                'wr_id': wr_id,
                'chunk_type': 'question',
                'chunk_text': q_text[:2000],
                'ca_name': ca_name,
                'wr_subject': wr_subject,
                'wr_datetime': wr_datetime,
                'wr_qna_ok': wr_qna_ok,
            })
            
            # 답변 chunk
            if wr_qna:
                a_text_parts = []
                a_text_parts.append(f"[제목] {wr_subject}")
                if ca_name:
                    a_text_parts.append(f"[카테고리] {ca_name}")
                if health_info_text:
                    a_text_parts.append(f"[건강정보] {health_info_text}")
                a_text_parts.append(f"[답변] {wr_qna}")
                
                a_text = '\n'.join(a_text_parts)
                
                # 답변이 여전히 길면 추가 분할
                if len(a_text) > 2000:
                    # 2000자씩 분할
                    for idx in range(0, len(a_text), 1800):
                        chunk_part = a_text[idx:idx + 2000]
                        chunks.append({
                            'wr_id': wr_id,
                            'chunk_type': 'answer',
                            'chunk_text': chunk_part,
                            'ca_name': ca_name,
                            'wr_subject': wr_subject,
                            'wr_datetime': wr_datetime,
                            'wr_qna_ok': wr_qna_ok,
                        })
                else:
                    chunks.append({
                        'wr_id': wr_id,
                        'chunk_type': 'answer',
                        'chunk_text': a_text,
                        'ca_name': ca_name,
                        'wr_subject': wr_subject,
                        'wr_datetime': wr_datetime,
                        'wr_qna_ok': wr_qna_ok,
                    })
        else:
            chunks.append({
                'wr_id': wr_id,
                'chunk_type': 'qa_pair',
                'chunk_text': qa_text,
                'ca_name': ca_name,
                'wr_subject': wr_subject,
                'wr_datetime': wr_datetime,
                'wr_qna_ok': wr_qna_ok,
            })
    
    return chunks


# ============================================================
# 3. 임베딩 생성
# ============================================================

def load_embedding_model(model_name: str = 'paraphrase-multilingual-MiniLM-L12-v2'):
    """sentence-transformers 모델 로드"""
    from sentence_transformers import SentenceTransformer
    print(f"임베딩 모델 로딩: {model_name}")
    model = SentenceTransformer(model_name)
    print(f"모델 로딩 완료. 임베딩 차원: {model.get_sentence_embedding_dimension()}")
    return model


def generate_embeddings(model, texts: list, batch_size: int = 64) -> list:
    """텍스트 리스트에 대한 임베딩 생성"""
    import numpy as np
    all_embeddings = []
    total = len(texts)
    
    for i in range(0, total, batch_size):
        batch = texts[i:i + batch_size]
        embeddings = model.encode(batch, show_progress_bar=False, normalize_embeddings=True)
        all_embeddings.extend(embeddings.tolist())
        
        processed = min(i + batch_size, total)
        if processed % (batch_size * 5) == 0 or processed == total:
            print(f"  임베딩 생성 진행: {processed}/{total} ({processed/total*100:.1f}%)")
    
    return all_embeddings


def embedding_to_bytes(embedding: list) -> bytes:
    """임베딩 벡터를 바이트로 변환 (SQLite BLOB 저장용)"""
    return struct.pack(f'{len(embedding)}f', *embedding)


def bytes_to_embedding(data: bytes, dim: int) -> list:
    """바이트를 임베딩 벡터로 변환"""
    return list(struct.unpack(f'{dim}f', data))


# ============================================================
# 4. SQLite 벡터 DB 생성
# ============================================================

def create_vector_db(db_path: str, chunks: list, embeddings: list, embedding_dim: int):
    """SQLite 벡터 DB를 생성합니다."""
    
    if os.path.exists(db_path):
        os.remove(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 메타데이터 테이블
    cursor.execute('''
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)",
                   ('embedding_model', 'paraphrase-multilingual-MiniLM-L12-v2'))
    cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)",
                   ('embedding_dim', str(embedding_dim)))
    cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)",
                   ('total_chunks', str(len(chunks))))
    cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)",
                   ('source', 'g5_write_counseling2'))
    cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)",
                   ('description', '리틀약사 건강기능식품 상담 Q&A 벡터 데이터베이스'))
    
    # 청크 + 임베딩 테이블
    cursor.execute('''
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wr_id TEXT,
            chunk_type TEXT,
            chunk_text TEXT,
            ca_name TEXT,
            wr_subject TEXT,
            wr_datetime TEXT,
            wr_qna_ok TEXT,
            embedding BLOB
        )
    ''')
    
    # 데이터 삽입
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        emb_bytes = embedding_to_bytes(emb)
        cursor.execute('''
            INSERT INTO chunks (wr_id, chunk_type, chunk_text, ca_name, wr_subject, wr_datetime, wr_qna_ok, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            chunk['wr_id'],
            chunk['chunk_type'],
            chunk['chunk_text'],
            chunk['ca_name'],
            chunk['wr_subject'],
            chunk['wr_datetime'],
            chunk['wr_qna_ok'],
            emb_bytes
        ))
        
        if (i + 1) % 1000 == 0 or (i + 1) == len(chunks):
            print(f"  DB 삽입 진행: {i + 1}/{len(chunks)}")
    
    # 검색 최적화를 위한 인덱스
    cursor.execute('CREATE INDEX idx_wr_id ON chunks(wr_id)')
    cursor.execute('CREATE INDEX idx_chunk_type ON chunks(chunk_type)')
    cursor.execute('CREATE INDEX idx_ca_name ON chunks(ca_name)')
    cursor.execute('CREATE INDEX idx_wr_qna_ok ON chunks(wr_qna_ok)')
    cursor.execute('CREATE INDEX idx_wr_datetime ON chunks(wr_datetime)')
    
    # 전문검색(FTS) 테이블 - 키워드 기반 하이브리드 검색용
    cursor.execute('''
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            chunk_text,
            wr_subject,
            ca_name,
            content='chunks',
            content_rowid='id'
        )
    ''')
    
    # FTS 테이블에 데이터 동기화
    cursor.execute('''
        INSERT INTO chunks_fts(rowid, chunk_text, wr_subject, ca_name)
        SELECT id, chunk_text, wr_subject, ca_name FROM chunks
    ''')
    
    conn.commit()
    
    # 통계 출력
    cursor.execute("SELECT COUNT(*) FROM chunks")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT wr_id) FROM chunks")
    unique_records = cursor.fetchone()[0]
    cursor.execute("SELECT chunk_type, COUNT(*) FROM chunks GROUP BY chunk_type")
    type_counts = cursor.fetchall()
    
    print(f"\n=== DB 생성 완료 ===")
    print(f"DB 경로: {db_path}")
    print(f"총 청크 수: {total}")
    print(f"고유 상담 레코드 수: {unique_records}")
    print(f"청크 유형별 수:")
    for t, c in type_counts:
        print(f"  - {t}: {c}")
    
    db_size = os.path.getsize(db_path)
    print(f"DB 파일 크기: {db_size / 1024 / 1024:.1f} MB")
    
    conn.close()


# ============================================================
# 5. 검색 유틸리티 (AI 에이전트용)
# ============================================================

def cosine_similarity(a: list, b: list) -> float:
    """코사인 유사도 계산"""
    import numpy as np
    a = np.array(a)
    b = np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def search_similar(db_path: str, query_embedding: list, top_k: int = 5, 
                   chunk_type: str = None, min_similarity: float = 0.3) -> list:
    """
    벡터 유사도 기반 검색
    
    Args:
        db_path: SQLite DB 경로
        query_embedding: 쿼리 임베딩 벡터
        top_k: 반환할 최대 결과 수
        chunk_type: 필터할 chunk 유형 (None이면 전체)
        min_similarity: 최소 유사도 임계값
    
    Returns:
        [(similarity, chunk_dict), ...] 형태의 리스트
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 임베딩 차원 조회
    cursor.execute("SELECT value FROM metadata WHERE key='embedding_dim'")
    dim = int(cursor.fetchone()[0])
    
    # 모든 청크 로드 (추후 ANN 인덱스 적용 가능)
    if chunk_type:
        cursor.execute(
            "SELECT id, wr_id, chunk_type, chunk_text, ca_name, wr_subject, wr_datetime, wr_qna_ok, embedding "
            "FROM chunks WHERE chunk_type = ?", (chunk_type,)
        )
    else:
        cursor.execute(
            "SELECT id, wr_id, chunk_type, chunk_text, ca_name, wr_subject, wr_datetime, wr_qna_ok, embedding "
            "FROM chunks"
        )
    
    results = []
    for row in cursor.fetchall():
        emb = bytes_to_embedding(row[8], dim)
        sim = cosine_similarity(query_embedding, emb)
        if sim >= min_similarity:
            results.append((sim, {
                'id': row[0],
                'wr_id': row[1],
                'chunk_type': row[2],
                'chunk_text': row[3],
                'ca_name': row[4],
                'wr_subject': row[5],
                'wr_datetime': row[6],
                'wr_qna_ok': row[7],
            }))
    
    results.sort(key=lambda x: x[0], reverse=True)
    conn.close()
    return results[:top_k]


def search_fts(db_path: str, query: str, top_k: int = 10) -> list:
    """
    FTS5 전문검색 (키워드 기반)
    
    Args:
        db_path: SQLite DB 경로
        query: 검색 쿼리
        top_k: 최대 결과 수
    
    Returns:
        [{chunk_dict}, ...] 형태의 리스트
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT c.id, c.wr_id, c.chunk_type, c.chunk_text, c.ca_name, 
               c.wr_subject, c.wr_datetime, c.wr_qna_ok, 
               chunks_fts.rank
        FROM chunks_fts
        JOIN chunks c ON chunks_fts.rowid = c.id
        WHERE chunks_fts MATCH ?
        ORDER BY chunks_fts.rank
        LIMIT ?
    ''', (query, top_k))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            'id': row[0],
            'wr_id': row[1],
            'chunk_type': row[2],
            'chunk_text': row[3],
            'ca_name': row[4],
            'wr_subject': row[5],
            'wr_datetime': row[6],
            'wr_qna_ok': row[7],
            'fts_rank': row[8],
        })
    
    conn.close()
    return results


def hybrid_search(db_path: str, model, query: str, top_k: int = 5,
                  vector_weight: float = 0.7, fts_weight: float = 0.3) -> list:
    """
    하이브리드 검색 (벡터 + FTS)
    
    Args:
        db_path: SQLite DB 경로
        model: sentence-transformers 모델
        query: 검색 쿼리
        top_k: 최대 결과 수
        vector_weight: 벡터 검색 가중치
        fts_weight: FTS 검색 가중치
    
    Returns:
        결합된 검색 결과 리스트
    """
    # 벡터 검색
    query_emb = model.encode(query, normalize_embeddings=True).tolist()
    vector_results = search_similar(db_path, query_emb, top_k=top_k * 2)
    
    # FTS 검색
    fts_results = search_fts(db_path, query, top_k=top_k * 2)
    
    # 점수 결합 (Reciprocal Rank Fusion 방식)
    scores = {}
    
    for rank, (sim, chunk) in enumerate(vector_results):
        chunk_id = chunk['id']
        if chunk_id not in scores:
            scores[chunk_id] = {'chunk': chunk, 'score': 0}
        scores[chunk_id]['score'] += vector_weight * (1.0 / (rank + 1))
    
    for rank, chunk in enumerate(fts_results):
        chunk_id = chunk['id']
        if chunk_id not in scores:
            scores[chunk_id] = {'chunk': chunk, 'score': 0}
        scores[chunk_id]['score'] += fts_weight * (1.0 / (rank + 1))
    
    # 점수순 정렬
    ranked = sorted(scores.values(), key=lambda x: x['score'], reverse=True)
    return ranked[:top_k]


# ============================================================
# 6. 메인 실행
# ============================================================

def main():
    base_dir = Path(__file__).parent
    sql_file = base_dir / 'docs' / 'g5_write_counseling2.sql'
    db_path = base_dir / 'data' / 'counseling_vectors.db'
    
    # data 디렉토리 생성
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("리틀약사 상담 Q&A 벡터 DB 생성기")
    print("=" * 60)
    
    # Step 1: SQL 파싱
    print(f"\n[1/4] SQL 파일 파싱: {sql_file}")
    print(f"  파일 크기: {sql_file.stat().st_size / 1024 / 1024:.1f} MB")
    
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    records = parse_insert_values(sql_content)
    print(f"  파싱된 레코드 수: {len(records)}")
    
    if not records:
        print("ERROR: 레코드가 파싱되지 않았습니다.")
        sys.exit(1)
    
    # Step 2: Chunking
    print(f"\n[2/4] Chunking 수행")
    all_chunks = []
    skipped = 0
    
    for record in records:
        chunks = create_chunks_from_record(record)
        if chunks:
            all_chunks.extend(chunks)
        else:
            skipped += 1
    
    print(f"  생성된 총 청크 수: {len(all_chunks)}")
    print(f"  건너뛴 레코드 수: {skipped}")
    
    # 청크 유형별 통계
    type_counts = {}
    for chunk in all_chunks:
        t = chunk['chunk_type']
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, c in sorted(type_counts.items()):
        print(f"  - {t}: {c}")
    
    # Step 3: 임베딩 생성
    print(f"\n[3/4] 임베딩 생성")
    model = load_embedding_model()
    embedding_dim = model.get_sentence_embedding_dimension()
    
    texts = [chunk['chunk_text'] for chunk in all_chunks]
    embeddings = generate_embeddings(model, texts, batch_size=64)
    print(f"  임베딩 생성 완료: {len(embeddings)}개, 차원: {embedding_dim}")
    
    # Step 4: SQLite DB 생성
    print(f"\n[4/4] SQLite 벡터 DB 생성")
    create_vector_db(str(db_path), all_chunks, embeddings, embedding_dim)
    
    # 검증 테스트
    print(f"\n{'=' * 60}")
    print("검증 테스트: 샘플 검색")
    print("=" * 60)
    
    test_queries = [
        "유산균 추천해주세요",
        "임산부 오메가3",
        "아이 아토피 유산균",
    ]
    
    for query in test_queries:
        print(f"\n쿼리: '{query}'")
        query_emb = model.encode(query, normalize_embeddings=True).tolist()
        results = search_similar(str(db_path), query_emb, top_k=3)
        
        for rank, (sim, chunk) in enumerate(results, 1):
            print(f"  [{rank}] 유사도: {sim:.4f} | 유형: {chunk['chunk_type']} | "
                  f"제목: {chunk['wr_subject'][:30]}")
    
    print(f"\n✅ 완료! DB 경로: {db_path}")


if __name__ == '__main__':
    main()
