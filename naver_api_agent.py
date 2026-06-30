import os
import time
import bcrypt
import base64
import requests
import sqlite3
import struct
from pathlib import Path
from sentence_transformers import SentenceTransformer

from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 1. 네이버 커머스 API 인증 설정
# ==========================================
API_HOST = "https://api.commerce.naver.com"
QNA_ENDPOINT = f"{API_HOST}/external/v1/contents/qnas"

def get_credentials(brand):
    from dotenv import load_dotenv
    load_dotenv(override=True)  # 최신 .env 파일 강제 리로드
    
    brand = brand.upper()
    client_id = os.environ.get(f"NAVER_CLIENT_ID_{brand}", "")
    client_secret = os.environ.get(f"NAVER_CLIENT_SECRET_{brand}", "")
    # Fallback to old format if not found
    if not client_id:
        client_id = os.environ.get("NAVER_CLIENT_ID", "")
        client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    return client_id, client_secret

# ==========================================
# 2. 새로운 폴더 및 DB 경로 설정
# ==========================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def get_db_path(brand):
    brand = brand.lower().replace("cs_", "").replace("qa_", "").replace("excel_", "")
    return DATA_DIR / f"vectors_{brand}.db"

# ==========================================
# 3. 인증 토큰(Access Token) 발급
# ==========================================
def get_access_token(brand):
    client_id, client_secret = get_credentials(brand)
    if not client_id or not client_secret:
        print(f"❌ {brand} API 인증 정보가 누락되었습니다.")
        return None
        
    timestamp = str(int(time.time() * 1000))
    password = f"{client_id}_{timestamp}"
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), client_secret.encode('utf-8'))
    client_secret_sign = base64.b64encode(hashed_pw).decode('utf-8')
    
    token_url = f"{API_HOST}/external/v1/oauth2/token"
    data = {
        'client_id': client_id,
        'timestamp': timestamp,
        'client_secret_sign': client_secret_sign,
        'grant_type': 'client_credentials',
        'type': 'SELF'
    }
    
    response = requests.post(token_url, data=data)
    if response.status_code == 200:
        return response.json().get('access_token')
    else:
        print(f"❌ 토큰 발급 실패 ({brand}): {response.text}")
        return None

# ==========================================
# 4. 네이버 문의 크롤링 (API 호출 - 전체 조회)
# ==========================================
def fetch_inquiries(brand):
    print(f"🌐 네이버 커머스 API에서 문의 내역을 호출합니다... ({brand})")
    
    access_token = get_access_token(brand)
    if not access_token:
        print("토큰 발급에 실패하여 크롤링을 중단합니다.")
        return []
        
    headers = {
        'Authorization': f"Bearer {access_token}",
        'content-type': 'application/json'
    }
    
    from datetime import datetime, timedelta
    
    all_inquiries = []
    end_date_time = datetime.now()
    start_date_time = end_date_time - timedelta(days=365)
    current_end = end_date_time
    
    while current_end > start_date_time:
        current_start = current_end - timedelta(days=30)
        if current_start < start_date_time:
            current_start = start_date_time
            
        from_date_str = current_start.strftime('%Y-%m-%dT%H:%M:%S+09:00')
        to_date_str = current_end.strftime('%Y-%m-%dT%H:%M:%S+09:00')
        
        page = 1
        while True:
            params = {
                'fromDate': from_date_str,
                'toDate': to_date_str,
                'page': page,
                'size': 100
            }
            url = f"{API_HOST}/external/v1/contents/qnas"
            
            max_retries = 10
            retry_count = 0
            success = False
            is_last_page = False
            
            while retry_count < max_retries:
                response = requests.get(url, headers=headers, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    contents = data.get('contents', [])
                    all_inquiries.extend(contents)
                    
                    if data.get('last', True) or page >= data.get('totalPages', 1):
                        is_last_page = True
                        
                    success = True
                    break 
                    
                elif response.status_code == 429:
                    import time
                    wait_time = 3 + (retry_count * 2)
                    print(f"⚠️ 요청량 초과(429). {wait_time}초 대기 후 재시도... ({retry_count+1}/{max_retries})")
                    time.sleep(wait_time)
                    retry_count += 1
                    
                else:
                    print(f"❌ API 오류: {response.text}")
                    break
                    
            if not success:
                print(f"❌ 데이터 수집 실패. (페이지 {page}) 구간 크롤링을 중단합니다.")
                break
                
            if is_last_page:
                break
                
            page += 1
            import time
            time.sleep(1)
                
        current_end = current_start - timedelta(seconds=1)

    print(f"✅ 전체 API 호출 완료! 총 {len(all_inquiries)}건의 데이터를 가져왔습니다.")
    return all_inquiries


def fetch_unanswered_inquiries(brand, days=7):
    """최근 N일간의 미답변 문의만 가져옵니다 (Streamlit 화면용)."""
    access_token = get_access_token(brand)
    if not access_token:
        return []
        
    headers = {
        'Authorization': f"Bearer {access_token}",
        'content-type': 'application/json'
    }
    
    from datetime import datetime, timedelta
    now = datetime.now()
    from_date_str = (now - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S+09:00')
    to_date_str = now.strftime('%Y-%m-%dT%H:%M:%S+09:00')
    
    params = {
        'fromDate': from_date_str,
        'toDate': to_date_str,
        'answered': 'false', 
        'page': 1,
        'size': 100
    }
    
    url = f"{API_HOST}/external/v1/contents/qnas"
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        return response.json().get('contents', [])
    return []


def post_inquiry_answer(brand, question_id, comment_content):
    """상품 문의 답변 등록 API (PUT)"""
    access_token = get_access_token(brand)
    if not access_token:
        return False, "토큰 발급 실패"
        
    headers = {
        'Authorization': f"Bearer {access_token}",
        'content-type': 'application/json'
    }
    
    url = f"{API_HOST}/external/v1/contents/qnas/{question_id}"
    payload = {
        "commentContent": comment_content
    }
    
    response = requests.put(url, headers=headers, json=payload)
    if response.status_code == 200:
        return True, "답변이 성공적으로 등록되었습니다."
    else:
        return False, f"오류 발생 ({response.status_code}): {response.text}"


# ==========================================
# 5. 임베딩 및 새로운 DB 저장 로직
# ==========================================
def load_embedding_model(model_name='paraphrase-multilingual-MiniLM-L12-v2'):
    print(f"🧠 임베딩 모델 로딩 중... ({model_name})")
    return SentenceTransformer(model_name)

def embedding_to_bytes(embedding):
    return struct.pack(f'{len(embedding)}f', *embedding)

def init_vector_db(db_path, embedding_dim):
    """새로운 독립적인 DB 테이블 구조를 생성합니다."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('embedding_dim', ?)", (str(embedding_dim),))
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inquiry_id TEXT UNIQUE,
            chunk_text TEXT,
            product_name TEXT,
            subject TEXT,
            is_answered INTEGER,
            embedding BLOB
        )
    ''')
    conn.commit()
    return conn

def process_and_save(brand="thelittles"):
    inquiries = fetch_inquiries(brand)
    if not inquiries:
        print("⚠️ 처리할 데이터가 없습니다. 프로세스를 종료합니다.")
        return

    model = load_embedding_model()
    dim = model.get_sentence_embedding_dimension()
    
    db_path = get_db_path(brand)
    conn = init_vector_db(str(db_path), dim)
    cursor = conn.cursor()
    
    print("🔄 청크 생성 및 임베딩 진행 중...")
    inserted_count = 0
    updated_count = 0
    
    for item in inquiries:
        q_id = str(item.get('questionId', item.get('inquiryNo', '')))
        p_name = item.get('productName', '상품명 없음')
        title = item.get('title', item.get('questionTitle', ''))
        content = item.get('content', item.get('questionContent', item.get('question', '')))
        
        is_answered = item.get('isAnswered', item.get('answered', False))
        answer = item.get('answerContent', item.get('answer', '')) if is_answered else '답변 대기중'
        
        chunk_text = f"[상품명] {p_name}\n[제목] {title}\n[질문] {content}\n[답변] {answer}"
        
        emb = model.encode(chunk_text, normalize_embeddings=True).tolist()
        emb_bytes = embedding_to_bytes(emb)
        
        cursor.execute("SELECT id FROM chunks WHERE inquiry_id = ?", (q_id,))
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute('''
                UPDATE chunks 
                SET chunk_text=?, product_name=?, subject=?, is_answered=?, embedding=?
                WHERE id=?
            ''', (chunk_text, p_name, title, 1 if is_answered else 0, emb_bytes, existing[0]))
            updated_count += 1
        else:
            cursor.execute('''
                INSERT INTO chunks (inquiry_id, chunk_text, product_name, subject, is_answered, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (q_id, chunk_text, p_name, title, 1 if is_answered else 0, emb_bytes))
            inserted_count += 1
            
    conn.commit()
    conn.close()
    
    print(f"\n🎉 작업 완료! 새로운 DB 생성/업데이트 완료")
    print(f"📁 DB 저장 위치: {db_path}")
    print(f"📊 신규 저장: {inserted_count}건 | 업데이트: {updated_count}건")

def update_inquiry_to_db(brand, q_id, p_name, title, content, answer, embedding_model=None):
    db_path = get_db_path(brand)
    
    if embedding_model is None:
        embedding_model = load_embedding_model()
        
    chunk_text = f"[상품명] {p_name}\n[제목] {title}\n[질문] {content}\n[답변] {answer}"
    emb = embedding_model.encode(chunk_text, normalize_embeddings=True).tolist()
    emb_bytes = embedding_to_bytes(emb)
    
    init_vector_db(str(db_path), embedding_model.get_sentence_embedding_dimension())
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM chunks WHERE inquiry_id = ?", (str(q_id),))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute('''
            UPDATE chunks 
            SET chunk_text=?, product_name=?, subject=?, is_answered=?, embedding=?
            WHERE id=?
        ''', (chunk_text, p_name, title, 1, emb_bytes, existing[0]))
    else:
        cursor.execute('''
            INSERT INTO chunks (inquiry_id, chunk_text, product_name, subject, is_answered, embedding)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (str(q_id), chunk_text, p_name, title, 1, emb_bytes))
        
    conn.commit()
    conn.close()
    print(f"✅ 문의 {q_id}에 대한 답변이 로컬 DB에 반영되었습니다. ({brand})")

def ingest_excel_qa(brand, file_path_or_bytes, embedding_model=None):
    import pandas as pd
    import uuid
    
    if embedding_model is None:
        embedding_model = load_embedding_model()
        
    db_path = get_db_path(brand)
    init_vector_db(str(db_path), embedding_model.get_sentence_embedding_dimension())
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        dfs = pd.read_excel(file_path_or_bytes, sheet_name=None, skiprows=2)
        
        inserted = 0
        for sheet_name, df in dfs.items():
            for index, row in df.iterrows():
                if len(row) < 3:
                    continue
                if pd.isna(row.iloc[1]) or pd.isna(row.iloc[2]):
                    continue
                    
                question = str(row.iloc[1]).strip()
                answer = str(row.iloc[2]).strip()
                
                if not question or not answer:
                    continue
                    
                q_id = f"excel_{uuid.uuid4().hex[:8]}"
                chunk_text = f"[엑셀 가이드라인: {sheet_name}]\n[고객문의/상황] {question}\n[모범답변] {answer}"
                
                # 중복 데이터 체크 (이미 동일한 내용이 등록되어 있으면 건너뛰기)
                cursor.execute("SELECT id FROM chunks WHERE chunk_text = ?", (chunk_text,))
                if cursor.fetchone():
                    continue
                    
                emb = embedding_model.encode(chunk_text, normalize_embeddings=True).tolist()
                emb_bytes = embedding_to_bytes(emb)
                
                cursor.execute('''
                    INSERT INTO chunks (inquiry_id, chunk_text, product_name, subject, is_answered, embedding)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (q_id, chunk_text, '가이드라인', 'Q&A 가이드라인', 1, emb_bytes))
                inserted += 1
            
        conn.commit()
        return True, f"성공적으로 {inserted}개의 Q&A 가이드라인을 DB에 반영했습니다."
    except Exception as e:
        conn.rollback()
        return False, f"엑셀 처리 중 오류 발생: {str(e)}"
    finally:
        conn.close()

if __name__ == "__main__":
    process_and_save("thelittles")
