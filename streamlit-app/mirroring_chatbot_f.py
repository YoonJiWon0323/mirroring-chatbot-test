import streamlit as st
import json
from datetime import datetime
import time
import uuid
import os
import openai
import gspread
from google.oauth2.service_account import Credentials

# ✅ Google Sheets 접근 권한 범위
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# ✅ GCP 서비스 계정 인증
creds = Credentials.from_service_account_info(st.secrets["GCP_SERVICE_ACCOUNT"], scopes=scope)
gc = gspread.authorize(creds)

# ✅ OpenAI 키 설정
openai.api_key = st.secrets["OPENAI_API_KEY"]

# ✅ 구글 시트 연결 (자신의 문서 ID로 교체)
spreadsheet = gc.open_by_key("1TSfKYISlyU7tweTqIIuwXbgY43xt1POckUa4DSbeHJo")

# 시트 헤더 자동 삽입 함수
def insert_headers_if_empty(worksheet, headers):
    try:
        if not worksheet.get_all_values():  # 시트가 비어 있으면
            worksheet.append_row(headers)
    except Exception as e:
        st.error(f"헤더 추가 중 오류 발생: {e}")

# 시트 연결
survey_ws = spreadsheet.worksheet("survey")
conversation_ws = spreadsheet.worksheet("conversation")

# 시트가 비어 있다면 헤더 자동 삽입
insert_headers_if_empty(survey_ws, [
    "timestamp", "user_id", "mode", "gender", "age", "education", "job",
    "similarity", "trust", "enjoyment", "humanness", "reuse_intent", "usefulness",
    "style_prompt"
])

insert_headers_if_empty(conversation_ws, [
    "timestamp", "user_id", "role", "message"
])



# 세션 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_history" not in st.session_state:
    st.session_state.user_history = []
if st.session_state.get("phase") == "mode_selection":
    st.session_state.user_history = []
    st.session_state.style_prompt = ""
if "style_prompt" not in st.session_state:
    st.session_state.style_prompt = ""
if "phase" not in st.session_state:
    st.session_state.phase = "mode_selection"
if "consent_given" not in st.session_state:
    st.session_state.consent_given = False
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())[:8]

# 파트 0: 모드 선택
if st.session_state.phase == "mode_selection":
    st.subheader("시작하기 전에 한 가지를 선택해 주세요:")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("옵션 A"):
            st.session_state.chatbot_mode = "fixed"
            st.session_state.phase = "style_collection"
            st.rerun()
    with col2:
        if st.button("옵션 B"):
            st.session_state.chatbot_mode = "mirroring"
            st.session_state.phase = "style_collection"
            st.rerun()

# 말투 분석
if "chatbot_mode" in st.session_state:
    def update_style_prompt():
        history = "\n".join(st.session_state.user_history[-3:])
        prompt = f"""Analyze the user's writing style based on the following utterances:\n{history}\n\nSummarize the user's tone, formality, and personality. Be concise, and express the tone in Korean if possible."""
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        st.session_state.style_prompt = response.choices[0].message.content

# 파트 1: 말투 수집
if st.session_state.get("phase") == "style_collection":
    if "collection_index" not in st.session_state:
        st.session_state.collection_index = 0
    if st.session_state.collection_index == 0:
        st.session_state.messages = []
        initial_prompt = "안녕하세요! 오늘 하루 어땠는지 궁금해요. 날씨나 기분 같은 걸 말해줘요 :)"
        st.session_state.messages.append({"role": "assistant", "content": initial_prompt})
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    user_input = st.chat_input("챗봇과 대화해보세요")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        st.session_state.user_history.append(user_input)
        with st.chat_message("user"):
            st.markdown(user_input)
        if st.session_state.collection_index < 2:
            system_prompt = "You are a friendly chatbot collecting natural language samples from the user. Ask a new, casual and personal question each time based on their last reply."
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": system_prompt}, *st.session_state.messages]
            )
            bot_reply = response.choices[0].message.content
            st.session_state.messages.append({"role": "assistant", "content": bot_reply})
            with st.chat_message("assistant"):
                st.markdown(bot_reply)
            st.session_state.collection_index += 1
        else:
            update_style_prompt()
            st.session_state.phase = "pre_task_notice"
            st.rerun()

# 파트 1.5: 과업 안내
elif st.session_state.get("phase") == "pre_task_notice":
    st.markdown(f"📝 **당신의 말투 분석 결과:** {st.session_state.style_prompt}")
    if st.session_state.chatbot_mode == "fixed":
        notice_text = "안녕하세요. 챗봇과 함께 3분 동안 여행 계획을 세워보세요. 궁금한 점이 있으면 언제든지 물어보셔도 됩니다."
    else:
        prompt = f"다음 말투에 맞춰, 사용자에게 3분간 여행 계획 대화를 시작하도록 제안하는 한국어 문장을 만들어줘.\n말투 요약: {st.session_state.style_prompt}"
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        notice_text = response.choices[0].message.content.strip()
    st.session_state.notice_text = notice_text
    st.session_state.phase = "task_conversation"
    st.session_state.start_time = time.time()
    st.rerun()

# 파트 2: 여행 대화
elif st.session_state.get("phase") == "task_conversation":
    if "notice_inserted" not in st.session_state:
        st.session_state.messages.append({"role": "assistant", "content": st.session_state.notice_text})
        st.session_state.notice_inserted = True
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    user_input = st.chat_input("챗봇과 여행 계획을 대화해보세요")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        system_instruction = (
            "You are a formal, concise Korean chatbot. Respond politely in 존댓말, and avoid casual or playful expressions."
            if st.session_state.chatbot_mode == "fixed"
            else f"""You are a Korean chatbot that mirrors the user's style.\nHere is the style guide:\n{st.session_state.style_prompt}\nRespond naturally in that style."""
        )
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_instruction}, *st.session_state.messages[-6:]]
        )
        bot_reply = response.choices[0].message.content
        st.session_state.messages.append({"role": "assistant", "content": bot_reply})
        with st.chat_message("assistant"):
            st.markdown(bot_reply)
    if st.session_state.start_time and time.time() - st.session_state.start_time > 180:
        st.markdown("⏰ 시간이 다 되어 챗봇 대화를 종료합니다. 설문지로 이동합니다.")
        time.sleep(5)
        st.session_state.phase = "consent"
        st.rerun()

# 파트 3: 설문 + Google Sheets 저장
elif st.session_state.get("phase") == "consent":
    st.subheader("🔒 설문 응답")
    st.write("아래 항목에 응답해 주세요. 응답은 자동 저장되며, 대화 내용 저장은 선택사항입니다.")
    demo_gender = st.radio("성별을 선택해 주세요:", ["선택 안 함", "남성", "여성", "기타"])
    demo_age = st.selectbox("연령대를 선택해 주세요:", ["선택 안 함", "10대", "20대", "30대", "40대", "50대 이상"])
    demo_edu = st.selectbox("최종 학력을 선택해 주세요:", ["선택 안 함", "고등학교 졸업 이하", "대학교 재학/졸업", "대학원 재학/졸업"])
    demo_job = st.text_input("현재 직업을 입력해 주세요 (예: 대학생, 회사원 등)")

    # 설문 6개 문항
    scale = ["선택 안 함", "전혀 아니다", "아니다", "보통이다", "그렇다", "매우 그렇다"]
    q1 = st.radio("이 챗봇은 당신과 말투가 비슷하다고 느꼈나요?", scale)
    q2 = st.radio("이 챗봇은 믿을 만하다고 느꼈나요?", scale)
    q3 = st.radio("이 챗봇과의 대화가 즐거웠나요?", scale)
    q4 = st.radio("이 챗봇은 사람처럼 느껴졌나요?", scale)
    q5 = st.radio("이 챗봇을 다시 사용하고 싶으신가요?", scale)
    q6 = st.radio("이 챗봇이 제공한 여행 계획은 도움이 되었나요?", scale)
    save_chat = st.checkbox("✅ 대화 내용도 함께 저장하겠습니다")

    if st.button("제출 및 저장"):
    # 입력값 유효성 검사
        if (
            demo_gender == "선택 안 함" or
            demo_age == "선택 안 함" or
            demo_edu == "선택 안 함" or
            demo_job.strip() == "" or
            q1 == "선택 안 함" or
            q2 == "선택 안 함" or
            q3 == "선택 안 함" or
            q4 == "선택 안 함" or
            q5 == "선택 안 함" or
            q6 == "선택 안 함"
        ):
            st.warning("⚠️ 모든 항목을 빠짐없이 입력해 주세요. 빈 항목이 있으면 저장되지 않습니다.")

        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mode_label = "A" if st.session_state.chatbot_mode == "fixed" else "B"

        # 🟡 1. 설문 응답 저장 (survey 시트)
            survey_row = [
                timestamp,
                st.session_state.user_id,
                mode_label,
                demo_gender,
                demo_age,
                demo_edu,
                demo_job,
                q1, q2, q3, q4, q5, q6,
                st.session_state.style_prompt
            ]
            survey_ws.append_row(survey_row, value_input_option="USER_ENTERED")

    # 🟡 2. 대화 내용 저장 (conversation 시트)
            if save_chat:
                for msg in st.session_state.messages:
                    conversation_ws.append_row([
                        timestamp,
                        st.session_state.user_id,
                        msg["role"],
                        msg["content"]
                    ], value_input_option="USER_ENTERED")

            st.success("✅ 설문과 대화가 각각 Google Sheets에 저장되었습니다!")

