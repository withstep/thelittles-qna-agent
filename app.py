import streamlit as st
import os
import uuid
import time
import pandas as pd
from datetime import datetime

# Huggingface Hub / Streamlit Threading 버그(httpx client closed) 우회 및 오프라인 로드 강제
os.environ["HF_HUB_DISABLE_HTTP2"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TQDM_DISABLE"] = "1"

try:
    from transformers.utils import logging as hf_logging
    hf_logging.disable_progress_bar()
except ImportError:
    pass

import gdown
from dotenv import load_dotenv
from agent import QnAAgent
import db
import naver_api_agent

# ==========================================
# 1. 초기 설정 및 유틸리티
# ==========================================
st.set_page_config(
    page_title="리틀약사 AI 상담 에이전트",
    page_icon="💊",
    layout="wide"
)

CUSTOM_CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

html, body, .stApp {
    font-family: 'Pretendard', sans-serif;
}

/* Streamlit 고유 요소들 CSS 리셋 보호 */
.stApp h1, .stApp h2, .stApp h3 {
    font-weight: 700;
}

/* 기본 멀티페이지 사이드바 메뉴(app, admin 등) 숨김 */
[data-testid="stSidebarNav"] {
    display: none;
}

/* 버튼 마이크로 인터랙션 */
div.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    transition: all 0.2s ease-in-out !important;
}
div.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

/* 사이드바 버튼 텍스트 잘림 방지 */
[data-testid="stSidebar"] div.stButton > button {
    font-size: 0.85rem !important;
    padding: 0.4rem 0.1rem !important;
}
[data-testid="stSidebar"] div.stButton > button p {
    font-size: 0.85rem !important;
}

/* Primary 버튼 그라디언트 */
div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #00C73C 0%, #00992E 100%) !important;
    border: none !important;
    color: white !important;
}

</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

ENV_FILE = ".env"
load_dotenv(ENV_FILE)

# DB 테이블 초기화 (1회)
def init_database():
    db.init_db()
    return True

@st.cache_resource
def download_vector_db():
    db_path = "data/vectors_littlelabs.db"
    if not os.path.exists(db_path):
        with st.spinner("최초 1회: 대용량 AI 벡터 DB를 다운로드 중입니다... (잠시만 기다려주세요)"):
            os.makedirs("data", exist_ok=True)
            # 여기서는 편의상 예시로 다운로드하는 로직을 남깁니다
            file_id = '1RPutYmUeU5bgkGjpF-Hy0IIFu6FYLNEi'
            url = f'https://drive.google.com/uc?id={file_id}'
            gdown.download(url, db_path, quiet=False)
    return True

init_database()

def load_chats():
    return db.get_all_chats()

def create_new_chat(chat_type="qa_littlelabs"):
    chat_id = str(uuid.uuid4())
    chats = db.get_all_chats()
    
    chat_name = f"상담 기록 ({len(chats) + 1})"
    welcome_msg = "안녕하세요! 무엇을 도와드릴까요?"
        
    db.create_chat(chat_id, chat_name, welcome_msg, chat_type)
    st.session_state.current_chat_id = chat_id
    st.session_state.page = chat_type
    return chat_id

# 쿠키 컨트롤러 초기화 (최상단)
from streamlit_cookies_controller import CookieController
cookie_controller = CookieController()

# 로그인 세션 확인
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    saved_user_id = cookie_controller.get('auth_user_id')
    if saved_user_id:
        user = db.get_user_by_id(saved_user_id)
        if user:
            st.session_state.user = user

if not st.session_state.user:
    st.title("💊 리틀약사 AI 로그인")
    st.markdown("서비스를 이용하시려면 로그인이 필요합니다.")
    
    with st.form("user_login_form"):
        username = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인", use_container_width=True, type="primary")
        
        if submitted:
            user = db.verify_user(username, password)
            if user:
                st.session_state.user = user
                cookie_controller.set('auth_user_id', user['id'])
                st.success(f"환영합니다, {user['username']}님!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("아이디 또는 비밀번호가 잘못되었습니다.")
    st.stop()

# 세션 상태 초기화
if "page" not in st.session_state:
    st.session_state.page = "cs_thelittles"

if "unanswered_list" not in st.session_state:
    st.session_state.unanswered_list = {}

if "draft_answers" not in st.session_state:
    st.session_state.draft_answers = {}

@st.cache_resource(show_spinner="AI 모델 초기화 중...")
def load_agent():
    print("Loading new agent instance...")
    import agent
    return agent.QnAAgent()

def update_api_keys(agent, model_choice):
    if model_choice == "openai":
        agent.openai_api_key = os.environ.get("OPENAI_API_KEY")
        from openai import OpenAI
        agent.openai_client = OpenAI(api_key=agent.openai_api_key) if agent.openai_api_key else None
    elif model_choice == "gemini":
        agent.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        from google import genai
        agent.gemini_client = genai.Client(api_key=agent.gemini_api_key) if agent.gemini_api_key else None

selected_model = "openai"

# ==========================================
# 2. 사이드바 구성 (메뉴 관리)
# ==========================================

def nav_button(label, page_name):
    if st.button(label, key=page_name, use_container_width=True, type="primary" if st.session_state.page == page_name else "secondary"):
        st.session_state.page = page_name
        st.rerun()

with st.sidebar:
    st.title("💊 리틀약사 AI")
    
    st.markdown(f"**👤 {st.session_state.user['username']}**님 환영합니다.")
    if st.button("로그아웃", use_container_width=True):
        st.session_state.user = None
        cookie_controller.remove('auth_user_id')
        import streamlit.components.v1 as components
        components.html("""
            <script>
                document.cookie = "auth_user_id=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
                setTimeout(function() {
                    window.parent.location.reload();
                }, 100);
            </script>
        """, height=0)
        st.stop()
        
    st.divider()
    
    st.subheader("🤖 CS 자동화")
    nav_button("더리틀스 미답변", "cs_thelittles")
    nav_button("퓨어젠 미답변", "cs_puregen")
    nav_button("그린루트 미답변", "cs_greenroot")
    
    st.write("")
    st.subheader("🤖 고객 Q&A 자동화")
    nav_button("더리틀스", "qa_thelittles")
    nav_button("퓨어젠", "qa_puregen")
    nav_button("그린루트", "qa_greenroot")
    
    st.write("")
    st.subheader("💊 리틀랩스 Q&A")
    nav_button("리틀랩스 Q&A", "qa_littlelabs")

    if st.session_state.user.get("role") == "admin":
        st.divider()
        st.subheader("⚙️ 관리자 메뉴")
        
        st.markdown("**환경설정**")
        nav_button("Context 관리", "admin_context")
        
        st.write("")
        st.markdown("**Q&A 엑셀 가이드 업로드**")
        nav_button("더리틀스", "excel_thelittles")
        nav_button("퓨어젠", "excel_puregen")
        nav_button("그린루트", "excel_greenroot")
        nav_button("지식 DB 통합 관리", "admin_vector_db")
        
        st.write("")
        st.markdown("**회원관리**")
        nav_button("회원관리", "user_management")

# ==========================================
# 3. 메인 화면 분기
# ==========================================

# ----------------------------------------
# [관리자] 환경 설정 화면
# ----------------------------------------
if st.session_state.page == "admin_context":
    st.title("⚙️ Context 관리")
    st.markdown("AI 챗봇의 전반적인 동작 방식을 설정합니다.")
    
    st.subheader("💡 기본 필수 지침 (Context) 설정")
    st.caption("모든 AI 답변 생성 시 봇에게 전달될 공통 지침입니다. (예: 과대광고 방지, 어조 등)")
    
    default_context = "답변 작성 시 건강기능식품 및 의약품 과대광고 가이드라인을 엄격히 준수하세요. 질병의 예방 및 치료에 효능·효과가 있다고 오인될 수 있는 표현(예: '치료합니다', '완치됩니다', '부작용이 전혀 없습니다')은 절대 사용하지 마세요."
    current_context = db.get_setting("custom_context", default_context)
    
    if not db.get_setting("custom_context"):
        db.set_setting("custom_context", default_context)
        current_context = default_context
        
    custom_context = st.text_area("AI 지침 (Context)", value=current_context, height=200, help="답변 시 AI가 반드시 지켜야 할 사항을 입력하세요.")
    
    if st.button("💾 설정 저장", type="primary"):
        db.set_setting("custom_context", custom_context)
        st.success("설정이 저장되었습니다!")

elif st.session_state.page == "admin_vector_db":
    st.title("🗄️ 지식 DB 통합 관리")
    st.markdown("벡터 지식 베이스에 저장된 항목들을 조회, 수정, 삭제할 수 있습니다.")
    
    brand_map = {
        "더리틀스": "thelittles",
        "퓨어젠": "puregen",
        "그린루트": "greenroot"
    }
    
    selected_brand_ko = st.selectbox("관리할 브랜드를 선택하세요", list(brand_map.keys()))
    selected_brand_en = brand_map[selected_brand_ko]
    
    db_path = f'data/vectors_{selected_brand_en}.db'
    
    if not os.path.exists(db_path):
        st.warning(f"{selected_brand_ko} 브랜드의 지식 DB 파일이 아직 생성되지 않았습니다.")
    else:
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'")
        if not cursor.fetchone():
            st.warning("아직 저장된 지식 데이터가 없습니다.")
        else:
            if "db_limit" not in st.session_state:
                st.session_state.db_limit = 100
            if "last_search_q" not in st.session_state:
                st.session_state.last_search_q = ""
            if "last_selected_brand" not in st.session_state:
                st.session_state.last_selected_brand = ""
                
            search_q = st.text_input("지식 검색 (제목 또는 내용)", placeholder="검색어를 입력하세요...")
            
            if search_q != st.session_state.last_search_q or selected_brand_en != st.session_state.last_selected_brand:
                st.session_state.db_limit = 100
                st.session_state.last_search_q = search_q
                st.session_state.last_selected_brand = selected_brand_en
                
            query = "SELECT id, subject, product_name, chunk_text FROM chunks"
            params = []
            if search_q:
                query += " WHERE subject LIKE ? OR chunk_text LIKE ?"
                params.extend([f"%{search_q}%", f"%{search_q}%"])
                
            query += f" ORDER BY id DESC LIMIT {st.session_state.db_limit}"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            cursor.execute("SELECT COUNT(*) FROM chunks" + (" WHERE subject LIKE ? OR chunk_text LIKE ?" if search_q else ""), params)
            total_count = cursor.fetchone()[0]
            
            st.markdown(f"검색 결과: 총 **{total_count}**개 중 **{len(rows)}**개 표시")
            
            agent = load_agent()
            
            for row in rows:
                c_id, c_subject, c_product, c_text = row
                with st.expander(f"{c_id}. {c_subject} [{c_product}]"):
                    edit_subject = st.text_input("제목 (질문/주제)", value=c_subject, key=f"subj_{selected_brand_en}_{c_id}")
                    edit_text = st.text_area("내용 (답변/가이드)", value=c_text, height=150, key=f"text_{selected_brand_en}_{c_id}")
                    
                    col1, col2, _ = st.columns([2, 2, 6])
                    with col1:
                        if st.button("내용 및 벡터 업데이트", key=f"edit_{selected_brand_en}_{c_id}", type="primary", use_container_width=True):
                            with st.spinner("AI 벡터 임베딩 재생성 및 저장 중..."):
                                agent.edit_knowledge(selected_brand_en, c_id, edit_subject, edit_text)
                            st.success("성공적으로 수정되었습니다.")
                            import time
                            time.sleep(1)
                            st.rerun()
                    with col2:
                        if st.button("삭제", key=f"del_{selected_brand_en}_{c_id}", use_container_width=True):
                            agent.delete_knowledge(selected_brand_en, c_id)
                            st.success("삭제되었습니다.")
                            import time
                            time.sleep(1)
                            st.rerun()
                            
            if len(rows) < total_count:
                if st.button("➕ 100개 더보기", use_container_width=True):
                    st.session_state.db_limit += 100
                    st.rerun()
                            
        conn.close()

# ----------------------------------------
# [관리자] 회원 관리 화면
# ----------------------------------------
elif st.session_state.page == "user_management":
    if st.session_state.user.get("role") != "admin":
        st.error("접근 권한이 없습니다.")
        st.stop()
        
    st.title("👥 회원 관리")
    st.markdown("사용자 계정을 추가하거나 삭제합니다.")
    
    users = db.get_all_users()
    df = pd.DataFrame(users)
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    st.subheader("신규 계정 추가")
    with st.form("add_user_form"):
        new_username = st.text_input("아이디")
        new_password = st.text_input("비밀번호", type="password")
        new_role = st.selectbox("권한", ["user", "admin"])
        submitted = st.form_submit_button("사용자 추가")
        
        if submitted:
            if not new_username or not new_password:
                st.error("아이디와 비밀번호를 모두 입력해주세요.")
            else:
                success, msg = db.create_user(new_username, new_password, new_role)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
                    
    st.subheader("계정 삭제")
    with st.form("delete_user_form"):
        del_user_id = st.number_input("삭제할 사용자 ID (id 번호)", min_value=1, step=1)
        del_submitted = st.form_submit_button("사용자 삭제", type="primary")
        
        if del_submitted:
            if del_user_id == st.session_state.user["id"]:
                st.error("현재 로그인 중인 계정은 삭제할 수 없습니다.")
            else:
                db.delete_user(del_user_id)
                st.success("사용자가 삭제되었습니다.")
                st.rerun()

# ----------------------------------------
# [공통] Q&A 엑셀 가이드 업로드
# ----------------------------------------
elif st.session_state.page.startswith("excel_"):
    brand = st.session_state.page.replace("excel_", "")
    st.title(f"📁 {brand.upper()} Q&A 엑셀 가이드 관리")
    st.markdown("해당 브랜드의 지식 DB에 기준이 될 엑셀 가이드를 업로드하고 관리합니다.")
    
    st.subheader("📤 새 가이드 업로드")
    uploaded_file = st.file_uploader("엑셀 파일 선택", type=["xlsx", "xls"])
    if uploaded_file is not None:
        if st.button("업로드 및 지식 DB 반영", type="primary"):
            with st.spinner(f"{brand} 지식 DB를 업데이트 중입니다..."):
                os.makedirs(f"data/excels/{brand}", exist_ok=True)
                file_path = f"data/excels/{brand}/{uploaded_file.name}"
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                db.add_excel_file(brand, uploaded_file.name, file_path)
                
                agent = load_agent()
                success, msg = naver_api_agent.ingest_excel_qa(brand, file_path, agent.model)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
                time.sleep(1)
                st.rerun()

    st.divider()
    st.subheader("📋 업로드된 가이드 목록")
    files = db.get_excel_files(brand)
    
    if not files:
        st.info("업로드된 엑셀 가이드가 없습니다.")
    else:
        for f in files:
            with st.container(border=True):
                col1, col2, col3 = st.columns([6, 2, 2])
                with col1:
                    st.markdown(f"**{f['filename']}**")
                    st.caption(f"업로드 일시: {f['uploaded_at']}")
                with col2:
                    with open(f['filepath'], "rb") as file_to_download:
                        st.download_button(
                            label="⬇️ 다운로드",
                            data=file_to_download,
                            file_name=f['filename'],
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_{f['id']}"
                        )
                with col3:
                    if st.button("🗑️ 삭제", key=f"del_{f['id']}", type="secondary"):
                        db.delete_excel_file(f['id'])
                        # (선택) DB Chunk 테이블에서도 해당 엑셀 내용을 지우려면 별도 로직 필요.
                        st.success("삭제되었습니다.")
                        time.sleep(1)
                        st.rerun()

# ----------------------------------------
# [공통] CS 자동화 (네이버 미답변)
# ----------------------------------------
elif st.session_state.page.startswith("cs_"):
    brand = st.session_state.page.replace("cs_", "")
    st.title(f"🚀 {brand.upper()} CS 자동화")
    st.markdown("네이버 커머스에 남아있는 **미답변 문의**를 실시간으로 가져오고, AI가 답변 초안을 생성합니다.")

    if st.button("🔄 미답변 문의 가져오기 (최근 7일)"):
        with st.spinner("미답변 문의를 조회 중입니다..."):
            items = naver_api_agent.fetch_unanswered_inquiries(brand, days=7)
            
            if not isinstance(st.session_state.unanswered_list, dict):
                st.session_state.unanswered_list = {}
                
            st.session_state.unanswered_list[brand] = items
            st.success(f"총 {len(items)}건의 미답변 문의를 찾았습니다.")

    if not isinstance(st.session_state.unanswered_list, dict):
        st.session_state.unanswered_list = {}
        
    items = st.session_state.unanswered_list.get(brand, [])
    if not items:
        st.info("현재 미답변 문의가 없습니다. 버튼을 눌러 새로고침 하세요.")
    else:
        st.divider()
        df_items = pd.DataFrame([{
            "문의번호": str(item.get('questionId', item.get('inquiryNo', ''))),
            "상품명": item.get('productName', '상품명 없음'),
            "제목": item.get('title', item.get('questionTitle', '상품 문의')),
            "작성일": item.get('createDate', '')[:10] if item.get('createDate') else ''
        } for item in items])
        
        st.markdown("### 📋 미답변 문의 리스트")
        st.dataframe(df_items, use_container_width=True, hide_index=True)
        st.write("")
        
        agent = load_agent()
        update_api_keys(agent, selected_model)
        
        for item in items:
            q_id = str(item.get('questionId', item.get('inquiryNo', '')))
            p_name = item.get('productName', '상품명 없음')
            title = item.get('title', item.get('questionTitle', '상품 문의'))
            content = item.get('question', item.get('content', item.get('questionContent', '')))
            create_date = item.get('createDate', '알 수 없음')
            
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**🛒 스토어 문의** &nbsp;|&nbsp; <span style='color: #6b7280; font-size: 0.85em;'>문의번호: {q_id}</span>", unsafe_allow_html=True)
                with col2:
                    st.markdown(f"<div style='text-align: right; color: #6b7280; font-size: 0.85em;'>🕒 {create_date}</div>", unsafe_allow_html=True)
                
                st.markdown(f"### {title}")
                st.markdown(f"**상품명:** {p_name}")
                st.info(f"**💬 고객 문의내용**\n\n{content}")
                
                # 초안 생성 버튼
                colA, colB = st.columns([1, 4])
                with colA:
                    if st.button(f"✨ AI 초안 생성", key=f"gen_{q_id}", use_container_width=True):
                        with st.spinner("AI가 답변을 작성 중입니다..."):
                            query = f"[상품명] {p_name}\n[제목] {title}\n[질문] {content}"
                            response_data = agent.generate_answer(query, top_k=3, use_model=selected_model, chat_type=st.session_state.page)
                            st.session_state.draft_answers[q_id] = response_data["answer"]
                            st.rerun()
                
                # 답변 편집 영역
                draft = st.session_state.draft_answers.get(q_id, "")
                if draft:
                    edited_answer = st.text_area("답변 수정", value=draft, height=200, key=f"edit_{q_id}")
                    if st.button("📤 네이버에 답변 등록", type="primary", key=f"post_{q_id}"):
                        with st.spinner("답변을 전송하고 있습니다..."):
                            success, msg = naver_api_agent.post_inquiry_answer(brand, q_id, edited_answer)
                            if success:
                                st.success(msg)
                                naver_api_agent.update_inquiry_to_db(brand, q_id, p_name, title, content, edited_answer, agent.model)
                                st.session_state.unanswered_list[brand] = [i for i in st.session_state.unanswered_list.get(brand, []) if str(i.get('questionId', i.get('inquiryNo', ''))) != q_id]
                                st.rerun()
                            else:
                                st.error(msg)
            st.divider()

# ----------------------------------------
# [공통] Q&A 자동화 (박스형 목록 UI)
# ----------------------------------------
elif st.session_state.page.startswith("qa_"):
    brand = st.session_state.page.replace("qa_", "")
    page_title = "리틀랩스 Q&A" if brand == "littlelabs" else f"{brand.upper()} 고객 Q&A 자동화"
    
    selected_qa_key = f"selected_qa_{brand}"
    if selected_qa_key not in st.session_state:
        st.session_state[selected_qa_key] = None

    if st.session_state[selected_qa_key] is None:
        # --- Grid List View ---
        st.title(page_title)
        st.markdown("AI를 통해 새 질문과 답변을 생성하고 지식 DB에 저장합니다.")
        st.divider()
        
        chats = load_chats()
        filtered_chats = {cid: c for cid, c in chats.items() if c.get('chat_type') == st.session_state.page}
        
        items = ["NEW"] + list(reversed(filtered_chats.items()))
        cols_per_row = 3
        
        for i in range(0, len(items), cols_per_row):
            cols = st.columns(cols_per_row)
            for j in range(cols_per_row):
                if i + j < len(items):
                    item = items[i + j]
                    with cols[j]:
                        with st.container(border=True):
                            if item == "NEW":
                                st.write("")
                                st.write("")
                                if st.button("➕", key=f"btn_new_{brand}", use_container_width=True):
                                    st.session_state[selected_qa_key] = "NEW_DRAFT"
                                    st.rerun()
                                st.write("")
                                st.write("")
                            else:
                                cid, chat_data = item
                                q_msg = next((m for m in chat_data["messages"] if m["role"] == "user"), None)
                                q_text = q_msg["content"] if q_msg else chat_data["name"]
                                if len(q_text) > 40: q_text = q_text[:40] + "..."
                                
                                st.markdown(f"**Q.** {q_text}")
                                st.caption(f"등록일: {chat_data.get('created_at', '')[:10]}")
                                
                                col_a, col_b = st.columns(2)
                                with col_a:
                                    if st.button("상세", key=f"detail_{cid}", use_container_width=True):
                                        st.session_state[selected_qa_key] = cid
                                        st.rerun()
                                with col_b:
                                    if st.button("삭제", key=f"del_{cid}", use_container_width=True):
                                        db.delete_chat(cid)
                                        st.rerun()

    else:
        # --- Detail View ---
        cid = st.session_state[selected_qa_key]
        
        if cid == "NEW_DRAFT":
            q_text = ""
            a_msg = None
            q_msg = None
            created_at = ""
        else:
            chats = load_chats()
            if cid not in chats:
                st.session_state[selected_qa_key] = None
                st.rerun()
            chat_data = chats[cid]
            q_msg = next((m for m in chat_data["messages"] if m["role"] == "user"), None)
            q_text = q_msg["content"] if q_msg else chat_data["name"]
            a_msg = next((m for m in reversed(chat_data["messages"]) if m["role"] == "assistant" and m["content"] != "안녕하세요! 무엇을 도와드릴까요?"), None)
            created_at = chat_data.get('created_at', '')[:10]
        
        if st.button("◀ 목록으로 돌아가기"):
            st.session_state[selected_qa_key] = None
            st.rerun()
            
        st.title("상세페이지" if cid != "NEW_DRAFT" else "새 질문 등록")
        
        st.markdown("### ❓ 질문")
        edited_q = st.text_area("질문 내용", value=q_text, height=100, key=f"edit_q_{cid}", label_visibility="collapsed")
        if created_at:
            st.caption(f"등록일: {created_at}")
        
        st.markdown("### 💡 답변")
        
        agent = load_agent()
        update_api_keys(agent, selected_model)
        
        temp_ans_key = f"temp_ans_{cid}"
        temp_src_key = f"temp_src_{cid}"
        
        if temp_ans_key not in st.session_state:
            if a_msg:
                st.session_state[temp_ans_key] = a_msg["content"]
                st.session_state[temp_src_key] = a_msg.get("sources", [])
            else:
                st.session_state[temp_ans_key] = ""
                st.session_state[temp_src_key] = []
                
        col_gen, _ = st.columns([2, 8])
        with col_gen:
            if st.button("✨ AI 답변 생성"):
                if not edited_q.strip():
                    st.warning("먼저 질문 내용을 입력해주세요.")
                else:
                    with st.spinner("AI 답변 생성 중..."):
                        # 1. Save question to DB to prevent input loss on rerun
                        if cid == "NEW_DRAFT":
                            cid = create_new_chat(st.session_state.page)
                            db.add_message(cid, "user", edited_q, [])
                            db.rename_chat(cid, edited_q[:30] + ("..." if len(edited_q) > 30 else ""))
                            st.session_state[selected_qa_key] = cid
                        else:
                            if q_msg:
                                db.update_message(q_msg["id"], edited_q, [])
                            else:
                                db.add_message(cid, "user", edited_q, [])
                            db.rename_chat(cid, edited_q[:30] + ("..." if len(edited_q) > 30 else ""))

                        # 2. Generate Draft
                        res = agent.generate_answer(edited_q, top_k=3, use_model=selected_model, chat_type=st.session_state.page)
                        import re
                        ans_text = res["answer"]
                        if "[UPDATE_QNA]" in ans_text:
                            pattern = r"\[UPDATE_QNA\](.*?)\[/UPDATE_QNA\]"
                            match = re.search(pattern, ans_text, re.DOTALL | re.IGNORECASE)
                            if match:
                                ans_text = re.sub(pattern, "", ans_text, flags=re.DOTALL | re.IGNORECASE).strip()
                        
                        # 3. Save to DB automatically
                        if a_msg:
                            db.update_message(a_msg["id"], ans_text, res["sources"])
                        else:
                            db.add_message(cid, "assistant", ans_text, res["sources"])
                            
                        # 4. Store to session state with new cid if changed
                        new_temp_ans_key = f"temp_ans_{cid}"
                        new_temp_src_key = f"temp_src_{cid}"
                        st.session_state[new_temp_ans_key] = ans_text
                        st.session_state[f"edit_ans_{cid}"] = ans_text  # Force update widget state
                        st.session_state[new_temp_src_key] = res["sources"]
                        st.rerun()

        # Retrieve the ans using the CURRENT cid (in case it just changed)
        current_cid = st.session_state[selected_qa_key]
        current_temp_ans_key = f"temp_ans_{current_cid}"
        current_temp_src_key = f"temp_src_{current_cid}"
        
        edited_ans = st.text_area("답변 내용", value=st.session_state.get(current_temp_ans_key, ""), height=200, key=f"edit_ans_{current_cid}", label_visibility="collapsed")
        temp_src = st.session_state.get(current_temp_src_key, [])
        if temp_src:
            with st.expander("📚 참고한 지식 문헌"):
                for idx, src in enumerate(temp_src, 1):
                    st.markdown(f"{idx}. {src['subject']}")
                    
        col_save1, col_save2 = st.columns(2)
        with col_save1:
            if st.button("저장하기", use_container_width=True):
                if not edited_q.strip() or not edited_ans.strip():
                    st.warning("질문과 답변을 모두 입력해주세요.")
                else:
                    if current_cid == "NEW_DRAFT":
                        new_cid = create_new_chat(st.session_state.page)
                        db.add_message(new_cid, "user", edited_q, [])
                        db.add_message(new_cid, "assistant", edited_ans, temp_src)
                        db.rename_chat(new_cid, edited_q[:30] + ("..." if len(edited_q) > 30 else ""))
                        
                        del st.session_state[current_temp_ans_key]
                        del st.session_state[current_temp_src_key]
                        st.session_state[selected_qa_key] = None
                        st.success("새 Q&A 내역이 목록에 저장되었습니다.")
                        import time
                        time.sleep(1)
                        st.rerun()
                    else:
                        if q_msg:
                            db.update_message(q_msg["id"], edited_q, [])
                        else:
                            db.add_message(current_cid, "user", edited_q, [])
                            
                        if a_msg:
                            db.update_message(a_msg["id"], edited_ans, temp_src)
                        else:
                            db.add_message(current_cid, "assistant", edited_ans, temp_src)
                            
                        db.rename_chat(current_cid, edited_q[:30] + ("..." if len(edited_q) > 30 else ""))
                        st.success("질문과 답변 내역이 임시 저장되었습니다.")
        
        with col_save2:
            if st.button("DB저장", type="primary", use_container_width=True):
                if not edited_q.strip() or not edited_ans.strip():
                    st.warning("질문과 답변을 모두 입력해주세요.")
                else:
                    agent.update_knowledge_base(st.session_state.page, edited_q, edited_ans)
                    
                    if current_cid == "NEW_DRAFT":
                        new_cid = create_new_chat(st.session_state.page)
                        db.add_message(new_cid, "user", edited_q, [])
                        db.add_message(new_cid, "assistant", edited_ans, temp_src)
                        db.rename_chat(new_cid, edited_q[:30] + ("..." if len(edited_q) > 30 else ""))
                    else:
                        if q_msg:
                            db.update_message(q_msg["id"], edited_q, [])
                        else:
                            db.add_message(current_cid, "user", edited_q, [])
                            
                        if a_msg:
                            db.update_message(a_msg["id"], edited_ans, temp_src)
                        else:
                            db.add_message(current_cid, "assistant", edited_ans, temp_src)
                            
                        db.rename_chat(current_cid, edited_q[:30] + ("..." if len(edited_q) > 30 else ""))
                    
                    del st.session_state[current_temp_ans_key]
                    del st.session_state[current_temp_src_key]
                    st.session_state[selected_qa_key] = None
                    
                    st.success("답변이 저장되고 지식 DB에 반영되었습니다.")
                    import time
                    time.sleep(1)
                    st.rerun()
