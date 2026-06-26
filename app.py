import streamlit as st
import os

# Huggingface Hub / Streamlit Threading 버그(httpx client closed) 우회 및 오프라인 로드 강제
os.environ["HF_HUB_DISABLE_HTTP2"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"

import uuid
import gdown
from dotenv import load_dotenv, set_key
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

# 환경변수 로드
load_dotenv(ENV_FILE)

WELCOME_MESSAGE = "안녕하세요! 리틀약사 AI입니다. 건강과 영양제에 관한 궁금증을 해결해 드릴게요. 무엇을 도와드릴까요?"

# DB 테이블 초기화 (1회)
@st.cache_resource
def init_database():
    db.init_db()
    return True

@st.cache_resource
def download_vector_db():
    db_path = "data/counseling_vectors.db"
    if not os.path.exists(db_path):
        with st.spinner("최초 1회: 대용량 AI 벡터 DB를 다운로드 중입니다... (잠시만 기다려주세요)"):
            os.makedirs("data", exist_ok=True)
            file_id = '1RPutYmUeU5bgkGjpF-Hy0IIFu6FYLNEi'
            url = f'https://drive.google.com/uc?id={file_id}'
            gdown.download(url, db_path, quiet=False)
    return True

init_database()

def load_chats():
    return db.get_all_chats()

def create_new_chat(chat_type="health"):
    chat_id = str(uuid.uuid4())
    chats = db.get_all_chats()
    
    if chat_type == "store":
        chat_name = f"스마트스토어 ({len(chats) + 1})"
        welcome_msg = "안녕하세요! 네이버 스토어 고객센터 매니저입니다. 상품이나 배송에 대해 궁금하신 점을 말씀해주세요."
    else:
        chat_name = f"리틀랩스 ({len(chats) + 1})"
        welcome_msg = "안녕하세요! 리틀약사 AI입니다. 건강과 영양제에 관한 궁금증을 해결해 드릴게요. 무엇을 도와드릴까요?"
        
    db.create_chat(chat_id, chat_name, welcome_msg, chat_type)
    st.session_state.current_chat_id = chat_id
    st.session_state.page = "chat"
    return chat_id

# 세션 상태 초기화
if "page" not in st.session_state:
    st.session_state.page = "chat"

if "current_chat_id" not in st.session_state:
    chats = load_chats()
    if not chats:
        create_new_chat(chat_type="health")
    else:
        # 가장 최근 생성된 채팅 (혹은 첫번째)
        st.session_state.current_chat_id = list(chats.keys())[-1]

if "unanswered_list" not in st.session_state:
    st.session_state.unanswered_list = []

if "draft_answers" not in st.session_state:
    st.session_state.draft_answers = {}

# 에이전트 초기화 캐싱
@st.cache_resource
def load_agent():
    download_vector_db() # 에이전트 초기화 전 DB 다운로드 확인
    return QnAAgent()

def update_api_keys(agent, model_choice):
    if model_choice == "openai":
        agent.openai_api_key = os.environ.get("OPENAI_API_KEY")
        from openai import OpenAI
        agent.openai_client = OpenAI(api_key=agent.openai_api_key) if agent.openai_api_key else None
    elif model_choice == "gemini":
        agent.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        from google import genai
        agent.gemini_client = genai.Client(api_key=agent.gemini_api_key) if agent.gemini_api_key else None


# ==========================================
# 2. 사이드바 구성 (메뉴 관리)
# ==========================================
chats = load_chats()
current_chat_id = st.session_state.current_chat_id

with st.sidebar:
    st.title("💊 리틀약사 AI")
    
    # --- 자동화 봇 ---
    st.subheader("🤖 CS 자동화")
    if st.button("🚀 네이버 미답변 문의 처리", use_container_width=True, type="primary" if st.session_state.page == "auto_reply" else "secondary"):
        st.session_state.page = "auto_reply"
        st.rerun()
        
    if st.button("💊 리틀랩스 Q&A 생성", use_container_width=True, type="primary" if st.session_state.page == "littlelabs_qna" else "secondary"):
        st.session_state.page = "littlelabs_qna"
        st.rerun()
        
    st.write("")
    with st.expander("📁 Q&A 엑셀 가이드라인 업로드"):
        st.caption("새로운 엑셀 파일을 업로드하면 기존 가이드라인이 덮어씌워집니다.")
        uploaded_file = st.file_uploader("엑셀 파일 선택", type=["xlsx", "xls"])
        if uploaded_file is not None:
            if st.button("데이터베이스에 반영하기", use_container_width=True):
                with st.spinner("엑셀 데이터를 분석하고 학습하는 중입니다..."):
                    import naver_api_agent
                    agent = load_agent()
                    success, msg = naver_api_agent.ingest_excel_qa(uploaded_file, agent.model)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
                        
    st.divider()

    # --- 멀티 채팅 세션 (스마트스토어 전용) ---
    st.subheader("💬 스마트스토어 상담 기록")
    if st.button("➕ 스마트스토어 새 상담", use_container_width=True):
        create_new_chat(chat_type="store")
        st.rerun()
        
    # 채팅 목록 출력 (store 타입만)
    has_store_chats = False
    for cid, chat_data in reversed(chats.items()):
        if chat_data.get('chat_type') == "store":
            has_store_chats = True
            is_active = (cid == current_chat_id and st.session_state.page == "chat")
            if st.button(
                f"{'▶ ' if is_active else ''}🛒 {chat_data['name']}",
                key=f"chat_btn_{cid}",
                use_container_width=True
            ):
                st.session_state.current_chat_id = cid
                st.session_state.page = "chat"
                st.rerun()
                
    if not has_store_chats:
        st.caption("저장된 스마트스토어 상담 내역이 없습니다.")

    # API 설정 섹션 삭제됨 (기본적으로 환경변수의 OpenAI 키 사용)
    selected_model = "openai"

# ==========================================
# 3. 메인 화면 분기
# ==========================================

if st.session_state.page == "auto_reply":
    # ----------------------------------------
    # [네이버 미답변 자동화 모드] 화면
    # ----------------------------------------
    st.title("🚀 네이버 스토어 CS 자동화")
    st.markdown("네이버 커머스에 남아있는 **미답변 문의**를 실시간으로 가져오고, AI가 작성한 초안을 수정한 뒤 즉시 답변을 등록합니다.")

    if st.button("🔄 미답변 문의 가져오기 (최근 7일)"):
        with st.spinner("미답변 문의를 조회 중입니다..."):
            items = naver_api_agent.fetch_unanswered_inquiries(days=7)
            st.session_state.unanswered_list = items
            st.success(f"총 {len(items)}건의 미답변 문의를 찾았습니다.")

    items = st.session_state.unanswered_list
    if not items:
        st.info("현재 미답변 문의가 없습니다. 버튼을 눌러 새로고침 하세요.")
    else:
        st.divider()
        
        # 가져온 데이터를 리스트(표) 형태로 우선 보여주기
        import pandas as pd
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
            p_id = item.get('productId', '')
            title = item.get('title', item.get('questionTitle', '상품 문의'))
            content = item.get('question', item.get('content', item.get('questionContent', '')))
            create_date = item.get('createDate', '')
            
            # 날짜 포맷팅
            try:
                if create_date:
                    from datetime import datetime
                    dt = datetime.fromisoformat(create_date.replace("Z", "+00:00"))
                    create_date_str = dt.strftime("%Y-%m-%d %H:%M")
                else:
                    create_date_str = "알 수 없음"
            except Exception:
                create_date_str = create_date
                
            link_url = f"https://brand.naver.com/thelittles/products/{p_id}" if p_id else "https://brand.naver.com/thelittles/"
            
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**🛒 스마트스토어 문의** &nbsp;|&nbsp; <span style='color: #6b7280; font-size: 0.85em;'>문의번호: {q_id}</span>", unsafe_allow_html=True)
                with col2:
                    st.markdown(f"<div style='text-align: right; color: #6b7280; font-size: 0.85em;'>🕒 {create_date_str}</div>", unsafe_allow_html=True)
                
                st.markdown(f"### {title}")
                st.markdown(f"**상품명:** <a href='{link_url}' target='_blank' style='color: #2563eb; text-decoration: none;'>{p_name} ↗️</a>", unsafe_allow_html=True)
                
                st.info(f"**💬 고객 문의내용**\n\n{content}")
                
                st.write("") # 약간의 여백 추가
                
                # 초안 생성 버튼
                colA, colB = st.columns([1, 4])
                with colA:
                    if st.button(f"✨ AI 초안 생성", key=f"gen_{q_id}", use_container_width=True):
                        with st.spinner("AI가 과거 내역을 바탕으로 답변을 작성 중입니다..."):
                            query = f"[상품명] {p_name}\n[제목] {title}\n[질문] {content}"
                            response_data = agent.generate_answer(query, top_k=3, use_model=selected_model, chat_type="store")
                            st.session_state.draft_answers[q_id] = response_data["answer"]
                            st.rerun()
                
                # 답변 편집 영역
                draft = st.session_state.draft_answers.get(q_id, "")
                if draft:
                    edited_answer = st.text_area("답변 수정 (편집 후 전송할 수 있습니다)", value=draft, height=200, key=f"edit_{q_id}")
                    if st.button("📤 이 내용으로 네이버에 답변 등록", type="primary", key=f"post_{q_id}"):
                        with st.spinner("네이버로 답변을 전송하고 있습니다..."):
                            success, msg = naver_api_agent.post_inquiry_answer(q_id, edited_answer)
                            if success:
                                st.success(msg)
                                # 벡터 DB에 즉시 업데이트하여 다음 초안 작성 시 반영되도록 함
                                naver_api_agent.update_inquiry_to_db(q_id, p_name, title, content, edited_answer, agent.model)
                                # 리스트에서 제거
                                st.session_state.unanswered_list = [i for i in st.session_state.unanswered_list if str(i.get('questionId', i.get('inquiryNo', ''))) != q_id]
                                st.rerun()
                            else:
                                st.error(msg)
                
                st.divider()

elif st.session_state.page == "chat":
    # ----------------------------------------
    # [일반 채팅 상담] 화면 (스마트스토어 전용 - Q&A 폼 형식)
    # ----------------------------------------
    current_chat_type = chats[current_chat_id].get('chat_type', 'store')
    
    col_title, col_del = st.columns([4, 1])
    with col_title:
        st.title("🛒 스마트스토어 상담 (Q&A 형식)")
        chat_name = chats[current_chat_id]['name']
        st.caption(f"현재 상담: {chat_name}")
        
    with col_del:
        st.write("") # 타이틀 높이 여백
        st.write("")
        del_confirm_key = f"confirm_del_{current_chat_id}"
        
        if st.session_state.get(del_confirm_key, False):
            st.error("정말 삭제하시겠습니까?")
            col_y, col_n = st.columns(2)
            if col_y.button("✔️ 예", use_container_width=True, type="primary"):
                if current_chat_id in chats:
                    db.delete_chat(current_chat_id)
                    del chats[current_chat_id]
                    
                    # 다른 store 채팅으로 이동
                    store_chats = [cid for cid, c in chats.items() if c.get('chat_type') == 'store']
                    if store_chats:
                        st.session_state.current_chat_id = store_chats[-1]
                        st.session_state.page = "chat"
                    else:
                        st.session_state.page = "littlelabs_qna" # 기본 화면으로
                    
                    st.session_state[del_confirm_key] = False
                    st.rerun()
            if col_n.button("❌ 아니오", use_container_width=True):
                st.session_state[del_confirm_key] = False
                st.rerun()
        else:
            if st.button("🗑️ 현재 상담 삭제", use_container_width=True, type="secondary"):
                st.session_state[del_confirm_key] = True
                st.rerun()

    # 현재 채팅방 메시지 렌더링
    messages = chats[current_chat_id]['messages']
    real_messages = messages[1:] if len(messages) > 0 else []
    
    last_user_msg = next((m for m in reversed(real_messages) if m["role"] == "user"), None)
    last_asst_msg = next((m for m in reversed(real_messages) if m["role"] == "assistant"), None)
    
    default_q = last_user_msg["content"] if last_user_msg else ""
    default_a = last_asst_msg["content"] if last_asst_msg else ""
    default_sources = last_asst_msg["sources"] if last_asst_msg else []

    state_q_key = f"q_{current_chat_id}"
    state_a_key = f"draft_{current_chat_id}"
    state_src_key = f"sources_{current_chat_id}"
    
    if state_q_key not in st.session_state:
        st.session_state[state_q_key] = default_q
    if state_a_key not in st.session_state:
        st.session_state[state_a_key] = default_a
    if state_src_key not in st.session_state:
        st.session_state[state_src_key] = default_sources

    st.markdown("### ❓ 질문 입력창")
    placeholder_text = "질문을 입력해주세요 (예: 배송 언제 되나요?)"
    
    question_input = st.text_area("고객의 질문을 입력하세요", value=st.session_state[state_q_key], height=100, label_visibility="collapsed", placeholder=placeholder_text)
    
    if question_input != st.session_state[state_q_key]:
        st.session_state[state_q_key] = question_input

    col_gen, col_empty = st.columns([1, 4])
    with col_gen:
        if st.button("🔄 AI 답변 갱신", use_container_width=True):
            if not question_input.strip():
                st.warning("질문을 먼저 입력해주세요.")
            else:
                if selected_model == "openai" and not os.environ.get("OPENAI_API_KEY"):
                    st.warning("⚠️ 좌측 설정에서 OpenAI API 키를 먼저 저장해주세요!")
                elif selected_model == "gemini" and not os.environ.get("GEMINI_API_KEY"):
                    st.warning("⚠️ 좌측 설정에서 Gemini API 키를 먼저 저장해주세요!")
                else:
                    with st.spinner("AI가 답변을 생성 중입니다..."):
                        agent = load_agent()
                        update_api_keys(agent, selected_model)
                        
                        try:
                            response_data = agent.generate_answer(
                                question_input, 
                                top_k=3, 
                                use_model=selected_model, 
                                chat_type=current_chat_type, 
                                history=[]
                            )
                            answer_text = response_data["answer"]
                            sources = response_data["sources"]
                            
                            import re
                            if "[UPDATE_QNA]" in answer_text:
                                pattern = r"\[UPDATE_QNA\](.*?)\[/UPDATE_QNA\]"
                                match = re.search(pattern, answer_text, re.DOTALL | re.IGNORECASE)
                                if match:
                                    answer_text = re.sub(pattern, "", answer_text, flags=re.DOTALL | re.IGNORECASE).strip()
                            
                            st.session_state[state_a_key] = answer_text
                            st.session_state[state_src_key] = sources
                            st.rerun()
                        except Exception as e:
                            st.error(f"⚠️ 답변 생성 중 오류가 발생했습니다: {e}")

    st.divider()

    st.markdown("### 📝 답변창 (수정 가능)")
    draft = st.session_state.get(state_a_key, "")
    
    edited_answer = st.text_area("최종적으로 전송하거나 저장할 답변을 편집하세요.", value=draft, height=250, label_visibility="collapsed")
    
    if edited_answer != st.session_state.get(state_a_key, ""):
        st.session_state[state_a_key] = edited_answer

    sources = st.session_state.get(state_src_key, [])
    if sources:
        with st.expander("📚 참고한 과거 내역", expanded=False):
            for idx, src in enumerate(sources, 1):
                st.markdown(f"**{idx}. {src['subject']}**")
                if src.get('date'):
                    st.caption(f"상담일: {src['date']}")
                    
    st.write("")
    
    col_save, col_empty2 = st.columns([1, 4])
    with col_save:
        if st.button("💾 저장", type="primary", use_container_width=True):
            if not question_input.strip():
                st.warning("질문을 입력해주세요.")
            elif not edited_answer.strip():
                st.warning("답변을 입력해주세요.")
            else:
                if last_user_msg:
                    db.update_message(last_user_msg["id"], question_input, [])
                else:
                    db.add_message(current_chat_id, "user", question_input, [])
                    
                if last_asst_msg:
                    db.update_message(last_asst_msg["id"], edited_answer, sources)
                else:
                    db.add_message(current_chat_id, "assistant", edited_answer, sources)
                    
                new_title = question_input[:15] + "..." if len(question_input) > 15 else question_input
                db.rename_chat(current_chat_id, new_title)
                
                # 수정한 답변을 기반으로 벡터 DB 지식 베이스 업데이트
                agent = load_agent()
                agent.update_knowledge_base(current_chat_type, question_input, edited_answer)
                
                st.session_state[f"saved_{current_chat_id}"] = True
                st.rerun()
                
    if st.session_state.get(f"saved_{current_chat_id}"):
        st.success("답변과 지식이 성공적으로 저장되었습니다!")
        st.session_state[f"saved_{current_chat_id}"] = False

elif st.session_state.page == "littlelabs_qna":
    # ----------------------------------------
    # [단일 Q&A 생성] 화면
    # ----------------------------------------
    current_chat_type = "health"
    title = "💊 리틀랩스 Q&A"
    
    st.title(title)
    st.caption("고객 문의에 대한 AI 답변 초안을 생성하고, 지식 베이스에 추가합니다.")
    st.write("")

    state_q_key = f"q_{current_chat_type}"
    state_a_key = f"draft_{current_chat_type}"
    state_src_key = f"sources_{current_chat_type}"
    
    if state_q_key not in st.session_state:
        st.session_state[state_q_key] = ""
    if state_a_key not in st.session_state:
        st.session_state[state_a_key] = ""
    if state_src_key not in st.session_state:
        st.session_state[state_src_key] = []

    st.markdown("### ❓ 질문 입력창")
    placeholder_text = "질문을 입력해주세요 (예: 배송 언제 되나요?)" if current_chat_type == "store" else "질문을 입력해주세요 (예: 임산부인데 철분제 추천해주세요)"
    
    question_input = st.text_area("고객의 질문을 입력하세요", value=st.session_state[state_q_key], height=100, label_visibility="collapsed", placeholder=placeholder_text)
    
    if question_input != st.session_state[state_q_key]:
        st.session_state[state_q_key] = question_input

    col_gen, col_empty = st.columns([1, 4])
    with col_gen:
        if st.button("🔄 AI 답변 갱신", use_container_width=True):
            if not question_input.strip():
                st.warning("질문을 먼저 입력해주세요.")
            else:
                if selected_model == "openai" and not os.environ.get("OPENAI_API_KEY"):
                    st.warning("⚠️ 좌측 설정에서 OpenAI API 키를 먼저 저장해주세요!")
                elif selected_model == "gemini" and not os.environ.get("GEMINI_API_KEY"):
                    st.warning("⚠️ 좌측 설정에서 Gemini API 키를 먼저 저장해주세요!")
                else:
                    with st.spinner("AI가 답변을 생성 중입니다..."):
                        agent = load_agent()
                        update_api_keys(agent, selected_model)
                        
                        try:
                            response_data = agent.generate_answer(
                                question_input, 
                                top_k=3, 
                                use_model=selected_model, 
                                chat_type=current_chat_type, 
                                history=[]
                            )
                            answer_text = response_data["answer"]
                            sources = response_data["sources"]
                            
                            import re
                            if "[UPDATE_QNA]" in answer_text:
                                pattern = r"\[UPDATE_QNA\](.*?)\[/UPDATE_QNA\]"
                                match = re.search(pattern, answer_text, re.DOTALL | re.IGNORECASE)
                                if match:
                                    # 사용자가 '저장' 버튼을 누를 때 지식 DB에 저장되도록 자동 저장 로직 제거
                                    answer_text = re.sub(pattern, "", answer_text, flags=re.DOTALL | re.IGNORECASE).strip()
                            
                            st.session_state[state_a_key] = answer_text
                            st.session_state[state_src_key] = sources
                            st.rerun()
                        except Exception as e:
                            st.error(f"⚠️ 답변 생성 중 오류가 발생했습니다: {e}")

    st.divider()

    st.markdown("### 📝 답변창 (수정 가능)")
    draft = st.session_state.get(state_a_key, "")
    
    edited_answer = st.text_area("최종적으로 전송하거나 저장할 답변을 편집하세요.", value=draft, height=250, label_visibility="collapsed")
    
    if edited_answer != st.session_state.get(state_a_key, ""):
        st.session_state[state_a_key] = edited_answer

    sources = st.session_state.get(state_src_key, [])
    if sources:
        with st.expander("📚 참고한 과거 내역", expanded=False):
            for idx, src in enumerate(sources, 1):
                st.markdown(f"**{idx}. {src['subject']}**")
                if src.get('date'):
                    st.caption(f"상담일: {src['date']}")
                    
    st.write("")
    
    col_save, col_empty2 = st.columns([1, 4])
    with col_save:
        if st.button("💾 저장", type="primary", use_container_width=True):
            if not question_input.strip():
                st.warning("질문을 입력해주세요.")
            elif not edited_answer.strip():
                st.warning("답변을 입력해주세요.")
            else:
                # 수정한 답변을 기반으로 벡터 DB 지식 베이스 업데이트
                agent = load_agent()
                agent.update_knowledge_base(current_chat_type, question_input, edited_answer)
                
                st.session_state[f"saved_{current_chat_type}"] = True
                
                # 저장 후 입력창 초기화
                st.session_state[state_q_key] = ""
                st.session_state[state_a_key] = ""
                st.session_state[state_src_key] = []
                st.rerun()
                
    if st.session_state.get(f"saved_{current_chat_type}"):
        st.success("답변과 지식이 성공적으로 저장되었습니다!")
        st.session_state[f"saved_{current_chat_type}"] = False
