import streamlit as st
import os
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
        chat_name = f"스토어 문의 ({len(chats) + 1})"
        welcome_msg = "안녕하세요! 네이버 스토어 고객센터 매니저입니다. 상품이나 배송에 대해 궁금하신 점을 말씀해주세요."
    else:
        chat_name = f"건강 상담 ({len(chats) + 1})"
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
# 2. 사이드바 구성 (멀티채팅 관리 및 설정)
# ==========================================
chats = load_chats()
current_chat_id = st.session_state.current_chat_id

with st.sidebar:
    st.title("💊 리틀약사 AI")
    
    # --- 자동화 봇 ---
    st.subheader("🤖 CS 자동화")
    if st.button("🚀 네이버 미답변 문의 AI 답변", use_container_width=True, type="primary"):
        st.session_state.page = "auto_reply"
        st.rerun()

    st.divider()

    # --- 멀티 채팅 세션 ---
    st.subheader("💬 상담 기록")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ 건강 상담", use_container_width=True):
            create_new_chat(chat_type="health")
            st.rerun()
    with col2:
        if st.button("➕ 스토어 문의", use_container_width=True):
            create_new_chat(chat_type="store")
            st.rerun()
        
    # 채팅 목록 출력
    for cid, chat_data in reversed(chats.items()):
        c_type = chat_data.get('chat_type', 'health')
        icon = "🛒" if c_type == "store" else "💊"
        is_active = (cid == current_chat_id and st.session_state.page == "chat")
        if st.button(
            f"{'▶ ' if is_active else ''}{icon} {chat_data['name']}",
            key=f"chat_btn_{cid}",
            use_container_width=True
        ):
            st.session_state.current_chat_id = cid
            st.session_state.page = "chat"
            st.rerun()

    # 채팅 삭제 (현재 선택된 채팅만 삭제 가능하도록)
    if st.button("🗑️ 현재 상담 삭제", use_container_width=True, type="secondary"):
        if current_chat_id in chats:
            db.delete_chat(current_chat_id)
            del chats[current_chat_id]
            # 다른 채팅으로 이동
            if chats:
                st.session_state.current_chat_id = list(chats.keys())[-1]
                st.session_state.page = "chat"
            else:
                create_new_chat()
            st.rerun()

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

else:
    # ----------------------------------------
    # [일반 채팅 상담] 화면
    # ----------------------------------------
    current_chat_type = chats[current_chat_id].get('chat_type', 'health')
    if current_chat_type == "store":
        st.title("🛒 스토어 문의")
    else:
        st.title("💊 상담 내용")
    chat_name = chats[current_chat_id]['name']
    st.caption(f"현재 상담: {chat_name}")

    # 현재 채팅방 메시지 렌더링
    messages = chats[current_chat_id]['messages']

    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("sources"):
                with st.expander("📚 참고한 과거 상담 내역", expanded=False):
                    for idx, src in enumerate(message["sources"], 1):
                        st.markdown(f"**{idx}. {src['subject']}**")
                        if src.get('date'):
                            st.caption(f"상담일: {src['date']}")

    # 사용자 입력 처리
    placeholder_text = "질문을 입력해주세요 (예: 배송 언제 되나요?)" if current_chat_type == "store" else "질문을 입력해주세요 (예: 임산부인데 철분제 추천해주세요)"
    if prompt := st.chat_input(placeholder_text):
        # API 키 확인
        if selected_model == "openai" and not os.environ.get("OPENAI_API_KEY"):
            st.warning("⚠️ 좌측 설정에서 OpenAI API 키를 먼저 저장해주세요!")
            st.stop()
        elif selected_model == "gemini" and not os.environ.get("GEMINI_API_KEY"):
            st.warning("⚠️ 좌측 설정에서 Gemini API 키를 먼저 저장해주세요!")
            st.stop()
            
        # 사용자 메시지 화면에 출력 및 저장
        messages.append({"role": "user", "content": prompt, "sources": []})
        db.add_message(current_chat_id, "user", prompt, [])

        # 첫 질문일 경우 채팅 제목 자동 변경 (welcome + user = 2개째)
        if len(messages) == 2:
            new_title = prompt[:15] + "..." if len(prompt) > 15 else prompt
            db.rename_chat(current_chat_id, new_title)

        with st.chat_message("user"):
            st.markdown(prompt)

        # 어시스턴트 응답 생성
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            
            with st.spinner("과거 기록을 검색하고 답변을 작성하고 있습니다..."):
                agent = load_agent()
                update_api_keys(agent, selected_model)
                    
                response_data = agent.generate_answer(prompt, top_k=3, use_model=selected_model, chat_type=current_chat_type)
                
                answer_text = response_data["answer"]
                sources = response_data["sources"]
                
            message_placeholder.markdown(answer_text)
            
            if sources:
                with st.expander("📚 참고한 과거 상담 내역", expanded=False):
                    for idx, src in enumerate(sources, 1):
                        st.markdown(f"**{idx}. {src['subject']}**")
                        if src.get('date'):
                            st.caption(f"상담일: {src['date']}")
            
            # 응답 저장
            db.add_message(current_chat_id, "assistant", answer_text, sources)

        st.rerun()
