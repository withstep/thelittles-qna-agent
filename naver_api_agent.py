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
    try:
        inquiries = fetch_inquiries(brand)
        if not inquiries:
            print("⚠️ 처리할 데이터가 없습니다. 프로세스를 종료합니다.")
            return True, 0, 0

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
        return True, inserted_count, updated_count
    except Exception as e:
        print(f"❌ 동기화 중 에러 발생: {e}")
        return False, 0, 0

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
                
                # 새 제목 생성 (시트명 + 질문)
                new_subject = f"[{sheet_name}] {question}"
                if len(new_subject) > 80:
                    new_subject = new_subject[:77] + "..."
                
                cursor.execute('''
                    INSERT INTO chunks (inquiry_id, chunk_text, product_name, subject, is_answered, embedding)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (q_id, chunk_text, '가이드라인', new_subject, 1, emb_bytes))
                inserted += 1
            
        conn.commit()
        return True, f"성공적으로 {inserted}개의 Q&A 가이드라인을 DB에 반영했습니다."
    except Exception as e:
        conn.rollback()
        return False, f"엑셀 처리 중 오류 발생: {str(e)}"
    finally:
        conn.close()

def _get_sheet_service():
    """Google Sheets API 클라이언트 (서비스 계정)."""
    import json
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds_info = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_info:
        # .env 파일 폴백 로드
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path) as ef:
                for line in ef:
                    if line.startswith("GOOGLE_SERVICE_ACCOUNT_JSON="):
                        creds_info = line.split("=", 1)[1].strip().strip('"')
                        break
    if not creds_info:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON이 설정되지 않았습니다.")

    creds = Credentials.from_service_account_info(
        json.loads(creds_info),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    return build("sheets", "v4", credentials=creds)


def get_sheet_id(brand):
    """브랜드별 구글 시트 ID 반환 (환경변수 GOOGLE_SHEET_ID_<BRAND>)."""
    return os.environ.get(f"GOOGLE_SHEET_ID_{brand.upper()}")


def sync_google_sheet_qa(brand, sheet_id=None, embedding_model=None):
    """브랜드 구글 시트 → 지식 DB 동기화.

    원본 Q&A 엑셀 양식(제품 Q&A 그린루트/엘앤/퓨어젠 구글시트)을 그대로 읽는다.
    각 탭의 실제 구조에 맞춰 파싱한다:
    - 제품 탭(오메가3 등): 1행=제품명(단일 셀), 2행=헤더(구분/질문/답변), 3행부터 B열=질문 C열=답변
      (예외: 피부오메가7은 1행부터 헤더)
    - 확인요청&제안 탭: 4행이 헤더(기존 답변.../대체 답변), 5행부터 B열=기존답변(질문 맥락) C열=대체 답변(지침)
      → "지침: C열" 형태의 상담 가이드 청크로 저장
    - 주문&배송 탭: A열 단일 열, 주제행(1단어) 다음 답변행이 반복되는 구조 → 주제+본문 결합
    - 종합문의(엘앤/퓨어젠): 1행=타이틀, 2행부터 A열=주제/질문, B열=답변
    - 종합문의(그린루트): 1행=타이틀, 2행부터 A열=질문, B열=답변 (중간 빈행 이후 재개 포함)

    - 각 청크는 gsheet_<brand>_<탭명해시>_<행번호> 소스 ID로 저장 → 수정 시 갱신, 삭제 시 제거
    Returns: (success, message)
    """
    if sheet_id is None:
        sheet_id = get_sheet_id(brand)
    if not sheet_id:
        return False, f"{brand} 브랜드의 구글 시트 ID가 설정되지 않았습니다. (GOOGLE_SHEET_ID_{brand.upper()})"

    if embedding_model is None:
        embedding_model = load_embedding_model()

    db_path = get_db_path(brand)
    init_vector_db(str(db_path), embedding_model.get_sentence_embedding_dimension())
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    import hashlib

    def cell(row, idx):
        return str(row[idx]).strip() if len(row) > idx and str(row[idx]).strip() else ""

    def parse_tab(title, rows):
        """하나의 탭을 [(row_no, chunk_type, question, answer)]로 파싱."""
        out = []
        if not rows:
            return out
        if title.startswith("확인요청&제안"):
            # 4행 헤더, 5행부터 B=기존답변/질문맥락, C=대체 답변(상담 지침)
            for i, row in enumerate(rows, 1):
                if i <= 4:
                    continue
                q, a = cell(row, 1), cell(row, 2)
                if q or a:
                    out.append((i, "상담지침", q or "(질문 원문 없음)", a))
        elif title == "주문&배송":
            # A열 단일 열: 주제 행 다음 답변 행
            pending = None
            for i, row in enumerate(rows, 1):
                v = cell(row, 0)
                if not v:
                    continue
                if pending is None:
                    pending = (i, v)
                else:
                    out.append((i, "주문배송", pending[1], v))
                    pending = None
        elif title == "종합문의" and brand == "greenroot":
            # 1행 타이틀, 2행부터 A=질문 B=답변
            for i, row in enumerate(rows, 1):
                if i <= 1:
                    continue
                q, a = cell(row, 0), cell(row, 1)
                if q and a:
                    out.append((i, "종합문의", q, a))
        else:
            # 제품 탭 + 엘앤/퓨어젠 종합문의
            # 헤더 감지: '질문'이 B열에 있는 행을 찾아 그 다음 행부터 데이터
            # (피부오메가7처럼 1행이 헤더인 경우도 자동 처리)
            start = 1
            for i, row in enumerate(rows, 1):
                if cell(row, 1) == "질문":
                    start = i + 1
                    break
            else:
                # 헤더 없으면 1행이 단일 타이틀(제품명)인지 확인
                if len(rows[0]) >= 2 and cell(rows[0], 1):
                    start = 1
                else:
                    start = 2
            for i, row in enumerate(rows, 1):
                if i < start:
                    continue
                q, a = cell(row, 1), cell(row, 2)
                if q and a and q != "질문":
                    out.append((i, "제품QA", q, a))
        return out

    try:
        service = _get_sheet_service()
        meta = service.spreadsheets().get(
            spreadsheetId=sheet_id, fields="sheets.properties.title").execute()
        titles = [s["properties"]["title"] for s in meta["sheets"]]
        result = service.spreadsheets().values().batchGet(
            spreadsheetId=sheet_id,
            ranges=[f"'{t}'!A1:Z2000" for t in titles]).execute()

        sheet_items = {}  # row_no -> (chunk_text, product_name, subject)
        for title, vr in zip(titles, result.get("valueRanges", [])):
            rows = vr.get("values", [])
            for row_no, ctype, question, answer in parse_tab(title, rows):
                q_id = f"gsheet_{brand}_{hashlib.md5(title.encode()).hexdigest()[:6]}_{row_no}"
                chunk_text = (f"[구글시트 가이드라인: {brand} / {title} / {ctype}]\n"
                              f"[고객문의/상황] {question}\n[모범답변/지침] {answer}")
                subject = f"[{title}] {question}"
                if len(subject) > 80:
                    subject = subject[:77] + "..."
                sheet_items[q_id] = (chunk_text, "가이드라인", subject)

        prefix = f"gsheet_{brand}_"
        cursor.execute("SELECT inquiry_id, id FROM chunks WHERE inquiry_id LIKE ?", (prefix + "%",))
        existing = {r[0]: r[1] for r in cursor.fetchall()}

        inserted = updated = 0
        for q_id, (chunk_text, pname, subject) in sheet_items.items():
            emb = embedding_model.encode(chunk_text, normalize_embeddings=True).tolist()
            emb_bytes = embedding_to_bytes(emb)
            if q_id in existing:
                cursor.execute("UPDATE chunks SET chunk_text=?, product_name=?, subject=?, embedding=? WHERE id=?",
                               (chunk_text, pname, subject, emb_bytes, existing[q_id]))
                updated += 1
            else:
                cursor.execute("""INSERT INTO chunks (inquiry_id, chunk_text, product_name, subject, is_answered, embedding)
                                  VALUES (?, ?, ?, ?, 1, ?)""",
                               (q_id, chunk_text, pname, subject, emb_bytes))
                inserted += 1

        removed = 0
        for q_id, cid in existing.items():
            if q_id not in sheet_items:
                cursor.execute("DELETE FROM chunks WHERE id=?", (cid,))
                removed += 1

        conn.commit()
        return True, (f"구글 시트 동기화 완료 — 신규 {inserted}건, 갱신 {updated}건, "
                      f"삭제 {removed}건 (총 청크: {len(sheet_items)}건, 탭 {len(titles)}개)")
    except Exception as e:
        conn.rollback()
        return False, f"구글 시트 동기화 중 오류 발생: {str(e)}"
    finally:
        conn.close()


if __name__ == "__main__":
    process_and_save("thelittles")
