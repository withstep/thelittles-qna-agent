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
CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
API_HOST = "https://api.commerce.naver.com"

# ※ 참고: 스마트스토어 API 권한에 따라 엔드포인트가 다를 수 있습니다.
# 상품 Q&A 조회 (가장 일반적인 엔드포인트)
QNA_ENDPOINT = f"{API_HOST}/external/v1/contents/qnas"

# ==========================================
# 2. 새로운 폴더 및 DB 경로 설정
# ==========================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "naver_data"  # 새로운 폴더
DB_PATH = DATA_DIR / "naver_vectors.db"  # 새로운 DB 파일

# 새로운 data 폴더 생성
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================
# 3. 인증 토큰(Access Token) 발급
# ==========================================
def get_access_token():
    """
    네이버 커머스 API 규격에 맞춘 bcrypt 서명 생성 후,
    OAuth2 토큰 발급 엔드포인트를 호출하여 Access Token을 받아옵니다.
    """
    timestamp = str(int(time.time() * 1000))
    password = f"{CLIENT_ID}_{timestamp}"
    # Client Secret을 salt로 사용하여 bcrypt 해시 생성
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), CLIENT_SECRET.encode('utf-8'))
    client_secret_sign = base64.b64encode(hashed_pw).decode('utf-8')
    
    token_url = f"{API_HOST}/external/v1/oauth2/token"
    data = {
        'client_id': CLIENT_ID,
        'timestamp': timestamp,
        'client_secret_sign': client_secret_sign,
        'grant_type': 'client_credentials',
        'type': 'SELF'
    }
    
    response = requests.post(token_url, data=data)
    if response.status_code == 200:
        return response.json().get('access_token')
    else:
        print(f"❌ 토큰 발급 실패: {response.text}")
        return None

# ==========================================
# 4. 네이버 문의 크롤링 (API 호출 - 전체 조회)
# ==========================================
def fetch_inquiries():
    print("🌐 네이버 커머스 API에서 문의 내역을 호출합니다...")
    
    access_token = get_access_token()
    if not access_token:
        print("토큰 발급에 실패하여 크롤링을 중단합니다.")
        return []
        
    headers = {
        'Authorization': f"Bearer {access_token}",
        'content-type': 'application/json'
    }
    
    from datetime import datetime, timedelta
    
    all_inquiries = []
    
    # 1년(365일)치 데이터를 30일 단위로 끊어서 조회 (기간 제한 에러 방지)
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
            
            # 429 Rate Limit 처리를 위한 재시도 로직
            max_retries = 5
            retry_count = 0
            success = False
            
            while retry_count < max_retries:
                response = requests.get(url, headers=headers, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    contents = data.get('contents', [])
                    all_inquiries.extend(contents)
                    
                    # 다음 페이지가 없으면 루프 탈출 조건
                    if data.get('last', True) or page >= data.get('totalPages', 1):
                        success = True
                        break
                    page += 1
                    break # 성공했으므로 재시도 루프 탈출하여 다음 페이지 진행
                    
                elif response.status_code == 429:
                    import time
                    print(f"⚠️ 요청량 초과(429). 2초 대기 후 재시도... ({retry_count+1}/{max_retries})")
                    time.sleep(2)
                    retry_count += 1
                    
                else:
                    print(f"❌ API 호출 실패 (상태 코드 {response.status_code})")
                    print(f"구간: {from_date_str} ~ {to_date_str}, 응답: {response.text}")
                    break  # 429 이외의 오류는 재시도하지 않음
            
            # 재시도 루프를 빠져나왔을 때 성공이 아니면 다음 구간(월)으로 넘어감
            if not success and response.status_code != 200:
                break
                
        # 다음 구간으로 이동
        current_end = current_start - timedelta(seconds=1)

    print(f"✅ 전체 API 호출 완료! 총 {len(all_inquiries)}건의 데이터를 가져왔습니다.")
    return all_inquiries


def fetch_unanswered_inquiries(days=7):
    """최근 N일간의 미답변 문의만 가져옵니다 (Streamlit 화면용)."""
    access_token = get_access_token()
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
        'answered': 'false', # 미답변만 필터링
        'page': 1,
        'size': 100
    }
    
    url = f"{API_HOST}/external/v1/contents/qnas"
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        return response.json().get('contents', [])
    return []


def post_inquiry_answer(question_id, comment_content):
    """상품 문의 답변 등록 API (PUT)"""
    access_token = get_access_token()
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
    
    # 메타데이터 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('embedding_dim', ?)", (str(embedding_dim),))
    
    # 새로운 청크 테이블 (네이버 전용 스키마)
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

def process_and_save():
    inquiries = fetch_inquiries()
    if not inquiries:
        print("⚠️ 처리할 데이터가 없습니다. 프로세스를 종료합니다.")
        return

    # 모델 준비
    model = load_embedding_model()
    dim = model.get_sentence_embedding_dimension()
    
    # DB 준비 (naver_data/naver_vectors.db)
    conn = init_vector_db(str(DB_PATH), dim)
    cursor = conn.cursor()
    
    print("🔄 청크 생성 및 임베딩 진행 중...")
    inserted_count = 0
    updated_count = 0
    
    for item in inquiries:
        # 네이버 API 스펙에 맞춰 JSON 키 맵핑
        # (API 버전에 따라 필드명이 다를 수 있으므로 범용적으로 get 처리)
        q_id = str(item.get('questionId', item.get('inquiryNo', '')))
        p_name = item.get('productName', '상품명 없음')
        title = item.get('title', item.get('questionTitle', ''))
        content = item.get('content', item.get('questionContent', ''))
        
        # 답변 여부 및 내용 처리
        is_answered = item.get('isAnswered', item.get('answered', False))
        answer = item.get('answerContent', '') if is_answered else '답변 대기중'
        
        # 핵심: [상품명] 맥락을 주입한 청크 텍스트 생성
        chunk_text = f"[상품명] {p_name}\n[제목] {title}\n[질문] {content}\n[답변] {answer}"
        
        # 임베딩 배열(Vector) 생성
        emb = model.encode(chunk_text, normalize_embeddings=True).tolist()
        emb_bytes = embedding_to_bytes(emb)
        
        # 기존에 같은 문의(inquiry_id)가 있는지 확인
        cursor.execute("SELECT id FROM chunks WHERE inquiry_id = ?", (q_id,))
        existing = cursor.fetchone()
        
        if existing:
            # 업데이트 로직
            cursor.execute('''
                UPDATE chunks 
                SET chunk_text=?, product_name=?, subject=?, is_answered=?, embedding=?
                WHERE id=?
            ''', (chunk_text, p_name, title, 1 if is_answered else 0, emb_bytes, existing[0]))
            updated_count += 1
        else:
            # 신규 삽입 로직
            cursor.execute('''
                INSERT INTO chunks (inquiry_id, chunk_text, product_name, subject, is_answered, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (q_id, chunk_text, p_name, title, 1 if is_answered else 0, emb_bytes))
            inserted_count += 1
            
    conn.commit()
    conn.close()
    
    print(f"\n🎉 작업 완료! 새로운 DB 생성/업데이트 완료")
    print(f"📁 DB 저장 위치: {DB_PATH}")
    print(f"📊 신규 저장: {inserted_count}건 | 업데이트: {updated_count}건")

if __name__ == "__main__":
    process_and_save()
