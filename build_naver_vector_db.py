import sqlite3
import json
import struct
import os
from pathlib import Path

# 임베딩 함수 및 모델 로더 (build_vector_db에서 차용)
def load_embedding_model(model_name: str = 'paraphrase-multilingual-MiniLM-L12-v2'):
    from sentence_transformers import SentenceTransformer
    print(f"임베딩 모델 로딩: {model_name}")
    model = SentenceTransformer(model_name)
    return model

def embedding_to_bytes(embedding: list) -> bytes:
    return struct.pack(f'{len(embedding)}f', *embedding)

def process_naver_inquiries(json_path: str, db_path: str):
    """
    네이버 스토어 문의 JSON 데이터를 읽어 임베딩하고 기존 벡터 DB에 추가합니다.
    """
    print(f"--- 네이버 스토어 문의 데이터 DB 추가 시작 ---")
    
    if not os.path.exists(json_path):
        print(f"오류: {json_path} 파일을 찾을 수 없습니다.")
        return
        
    if not os.path.exists(db_path):
        print(f"오류: 기존 벡터 DB({db_path})가 존재하지 않습니다. 먼저 build_vector_db.py를 실행하세요.")
        return

    # 1. JSON 데이터 로드
    with open(json_path, 'r', encoding='utf-8') as f:
        inquiries = json.load(f)
        
    print(f"불러온 데이터 수: {len(inquiries)}건")

    # 2. Chunk 생성
    chunks = []
    for item in inquiries:
        # 질문과 답변이 모두 있는 경우 결합하여 텍스트 생성
        q_title = item.get('questionTitle', '')
        q_content = item.get('questionContent', '')
        a_content = item.get('answerContent', '')
        p_name = item.get('productName', '')
        
        # [상품명] 맥락을 강제 주입하여 LLM 환각 방지
        chunk_text = f"[상품명] {p_name}\n[제목] {q_title}\n[질문] {q_content}\n[답변] {a_content}"
        
        chunks.append({
            'wr_id': item.get('inquiryNo', ''),
            'chunk_type': 'store_qna',  # 네이버 데이터 식별자
            'chunk_text': chunk_text,
            'ca_name': p_name,
            'wr_subject': q_title,
            'wr_datetime': item.get('questionDate', ''),
            'wr_qna_ok': '1' if item.get('answered') else '0'
        })
        
    # 3. 임베딩 생성
    model = load_embedding_model()
    texts = [c['chunk_text'] for c in chunks]
    print(f"임베딩 생성 중...")
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    embeddings = embeddings.tolist()

    # 4. DB에 삽입 (Upsert 또는 Append)
    print(f"DB에 데이터 삽입 중...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    inserted_count = 0
    for chunk, emb in zip(chunks, embeddings):
        # 중복 방지를 위해 기존 inquiryNo (wr_id)가 있는지 확인
        cursor.execute("SELECT id FROM chunks WHERE wr_id = ? AND chunk_type = 'store_qna'", (chunk['wr_id'],))
        existing = cursor.fetchone()
        
        emb_bytes = embedding_to_bytes(emb)
        
        if existing:
            # 업데이트 로직 (답변이 달렸거나 수정된 경우)
            row_id = existing[0]
            cursor.execute('''
                UPDATE chunks 
                SET chunk_text=?, ca_name=?, wr_subject=?, wr_datetime=?, wr_qna_ok=?, embedding=?
                WHERE id=?
            ''', (
                chunk['chunk_text'], chunk['ca_name'], chunk['wr_subject'], 
                chunk['wr_datetime'], chunk['wr_qna_ok'], emb_bytes, row_id
            ))
            
            # FTS 업데이트
            cursor.execute('''
                UPDATE chunks_fts 
                SET chunk_text=?, wr_subject=?, ca_name=?
                WHERE rowid=?
            ''', (chunk['chunk_text'], chunk['wr_subject'], chunk['ca_name'], row_id))
            
        else:
            # 새 레코드 추가
            cursor.execute('''
                INSERT INTO chunks (wr_id, chunk_type, chunk_text, ca_name, wr_subject, wr_datetime, wr_qna_ok, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                chunk['wr_id'], chunk['chunk_type'], chunk['chunk_text'],
                chunk['ca_name'], chunk['wr_subject'], chunk['wr_datetime'], 
                chunk['wr_qna_ok'], emb_bytes
            ))
            row_id = cursor.lastrowid
            
            # FTS 인덱스 추가
            cursor.execute('''
                INSERT INTO chunks_fts(rowid, chunk_text, wr_subject, ca_name)
                VALUES (?, ?, ?, ?)
            ''', (row_id, chunk['chunk_text'], chunk['wr_subject'], chunk['ca_name']))
            
            inserted_count += 1

    conn.commit()
    conn.close()
    
    print(f"--- 네이버 데이터 DB 업데이트 완료 (신규 삽입: {inserted_count}건) ---")

if __name__ == '__main__':
    base_dir = Path(__file__).parent
    json_path = base_dir / 'data' / 'naver_qna_sample.json'
    db_path = base_dir / 'data' / 'counseling_vectors.db'
    process_naver_inquiries(str(json_path), str(db_path))
