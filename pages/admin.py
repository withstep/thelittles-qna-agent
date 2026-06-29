import streamlit as st
import db
import time

st.set_page_config(
    page_title="관리자 로그인",
    page_icon="🔒",
)

# Ensure DB is initialized
db.init_db()

# 쿠키 컨트롤러 초기화
from streamlit_cookies_controller import CookieController
cookie_controller = CookieController()

if "user" not in st.session_state:
    st.session_state.user = None

# 쿠키에서 세션 복원 시도
if not st.session_state.user:
    saved_user_id = cookie_controller.get('auth_user_id')
    if saved_user_id:
        user = db.get_user_by_id(saved_user_id)
        if user:
            st.session_state.user = user

if st.session_state.user and st.session_state.user.get("role") == "admin":
    st.success("이미 관리자로 로그인되어 있습니다. 메인 화면으로 이동합니다.")
    time.sleep(1)
    st.switch_page("app.py")
    st.stop()

st.title("🔒 관리자 전용 로그인")
st.markdown("관리자 전용 접근 페이지입니다.")

with st.form("admin_login_form"):
    username = st.text_input("관리자 아이디")
    password = st.text_input("비밀번호", type="password")
    submitted = st.form_submit_button("로그인", use_container_width=True, type="primary")
    
    if submitted:
        user = db.verify_user(username, password)
        if user and user["role"] == "admin":
            st.session_state.user = user
            cookie_controller.set('auth_user_id', user['id'])
            st.success(f"관리자 로그인 성공! 환영합니다, {user['username']}님. 메인 화면으로 이동합니다.")
            time.sleep(1)
            st.switch_page("app.py")
        else:
            st.error("관리자 계정 정보가 일치하지 않거나 권한이 없습니다.")
