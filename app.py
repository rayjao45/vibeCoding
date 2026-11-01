import json

import streamlit as st
from openai import OpenAI
from pypdf import PdfReader
from supabase import Client, create_client


st.set_page_config(
    page_title="AI 학습 정리 노트",
    page_icon="📚",
    layout="wide",
)

st.title("AI 학습 정리 노트")
st.write("PDF를 업로드하면 문서의 텍스트를 바로 확인할 수 있습니다.")


@st.cache_resource
def get_supabase_client() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


def get_summary_preview(summary: object) -> str:
    if isinstance(summary, dict):
        preview = summary.get("핵심 요약", "")
    else:
        preview = ""
    return str(preview).replace("\n", " ").strip()[:160]

if "summary_result" not in st.session_state:
    st.session_state.summary_result = None
if "summary_source" not in st.session_state:
    st.session_state.summary_source = None
if "summary_record_id" not in st.session_state:
    st.session_state.summary_record_id = None
if "quiz_result" not in st.session_state:
    st.session_state.quiz_result = None

with st.sidebar:
    st.header("문서 업로드")
    uploaded_file = st.file_uploader(
        "PDF 파일 업로드",
        type=["pdf"],
        accept_multiple_files=False,
    )
    st.divider()
    st.subheader("문서 정보")
    if uploaded_file is None:
        st.caption("업로드된 문서가 없습니다.")

reader = None
total_pages = 0
pdf_error = None
page_texts = []
full_text = ""

if uploaded_file is not None:
    try:
        reader = PdfReader(uploaded_file)
        total_pages = len(reader.pages)
        page_texts = [
            (page.extract_text() or "").strip()
            for page in reader.pages
        ]
        full_text = "\n\n".join(text for text in page_texts if text)

        summary_source = (uploaded_file.name, uploaded_file.size)
        if st.session_state.summary_source != summary_source:
            st.session_state.summary_result = None
            st.session_state.summary_record_id = None
            st.session_state.quiz_result = None
            st.session_state.summary_source = summary_source
    except Exception as error:
        pdf_error = error
else:
    st.session_state.summary_result = None
    st.session_state.summary_source = None
    st.session_state.summary_record_id = None
    st.session_state.quiz_result = None

with st.sidebar:
    if uploaded_file is not None:
        st.caption("파일명")
        st.write(uploaded_file.name)
        st.metric("총 페이지 수", total_pages)

original_tab, summary_tab, quiz_tab, history_tab = st.tabs(
    ["원문", "요약", "퀴즈", "저장 기록"]
)
with original_tab:
    if pdf_error is not None:
        st.error(f"PDF를 읽는 중 문제가 발생했습니다: {pdf_error}")
    elif reader is None:
        st.info("사이드바에서 PDF 파일을 업로드하면 페이지별 원문이 표시됩니다.")
    else:
        st.subheader("페이지별 텍스트")
        for page_number, page_text in enumerate(page_texts, start=1):
            with st.expander(f"{page_number}페이지", expanded=page_number == 1):
                if page_text:
                    st.text_area(
                        f"{page_number}페이지 텍스트",
                        value=page_text,
                        height=300,
                        label_visibility="collapsed",
                    )
                else:
                    st.info("이 페이지에서 추출할 수 있는 텍스트가 없습니다.")

with summary_tab:
    st.subheader("PDF 요약")
    if pdf_error is not None:
        st.error(f"PDF를 읽는 중 문제가 발생했습니다: {pdf_error}")
    elif not full_text:
        st.info("요약할 텍스트가 있는 PDF를 먼저 업로드하세요.")
    else:
        if st.button("요약하기", type="primary"):
            system_prompt = (
                "다음 PDF 텍스트를 분석하고, 핵심 요약(3문장), 주요 키워드(5개), "
                "난이도(상/중/하)를 JSON으로 반환하세요. "
                'JSON 키는 "핵심 요약", "주요 키워드", "난이도"를 사용하세요.'
            )
            try:
                client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                with st.spinner("PDF를 요약하는 중입니다..."):
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": full_text},
                        ],
                        response_format={"type": "json_object"},
                    )
                content = response.choices[0].message.content or "{}"
                st.session_state.summary_result = json.loads(content)
            except KeyError:
                st.error("OpenAI API 키가 설정되지 않았습니다. st.secrets를 확인하세요.")
            except json.JSONDecodeError:
                st.error("요약 결과를 JSON으로 해석하지 못했습니다.")
            except Exception as error:
                st.error(f"요약 중 문제가 발생했습니다: {error}")

        summary_result = st.session_state.summary_result
        if summary_result:
            st.subheader("핵심 요약")
            st.write(summary_result.get("핵심 요약", "결과가 없습니다."))

            st.subheader("주요 키워드")
            keywords = summary_result.get("주요 키워드", [])
            if isinstance(keywords, list):
                for keyword in keywords:
                    st.markdown(f"- {keyword}")
            else:
                st.write(keywords)

            st.subheader("난이도")
            st.write(summary_result.get("난이도", "결과가 없습니다."))

            if st.button("저장", disabled=st.session_state.summary_record_id is not None):
                try:
                    insert_response = (
                        get_supabase_client()
                        .table("summaries")
                        .insert(
                            {
                                "filename": uploaded_file.name,
                                "summary": summary_result,
                            }
                        )
                        .select("id")
                        .single()
                        .execute()
                    )
                    st.session_state.summary_record_id = insert_response.data["id"]
                    st.success("요약 결과를 저장했습니다.")
                except Exception as error:
                    st.error(f"요약 결과 저장 중 문제가 발생했습니다: {error}")

with quiz_tab:
    st.subheader("학습 퀴즈")
    summary_result = st.session_state.summary_result
    summary_record_id = st.session_state.summary_record_id

    if not summary_result:
        st.info("요약 탭에서 먼저 PDF 요약을 만들어주세요.")
    elif summary_record_id is None:
        st.info("퀴즈를 만들려면 요약 결과를 먼저 저장해주세요.")
    else:
        if st.button("퀴즈 생성", type="primary"):
            quiz_system_prompt = """당신은 학습 퀴즈를 만드는 도우미입니다.
주어진 요약을 바탕으로 4지선다 퀴즈 3문항을 만드세요.
각 문항은 question, options(4개), answer(정답 인덱스, 0부터 시작), explanation을 포함해야 합니다.
결과는 {"questions": [...]} 형태의 JSON으로 반환하세요.
"""
            try:
                client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                with st.spinner("요약을 바탕으로 퀴즈를 만드는 중입니다..."):
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": quiz_system_prompt},
                            {
                                "role": "user",
                                "content": json.dumps(
                                    summary_result,
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                        response_format={"type": "json_object"},
                    )
                content = response.choices[0].message.content or "{}"
                quiz_result = json.loads(content)
                questions = quiz_result.get("questions", [])
                if not isinstance(questions, list) or len(questions) != 3:
                    raise ValueError("퀴즈 결과에 3개 문항이 필요합니다.")

                (
                    get_supabase_client()
                    .table("summaries")
                    .update({"quiz": quiz_result})
                    .eq("id", summary_record_id)
                    .execute()
                )
                st.session_state.quiz_result = quiz_result
                st.success("퀴즈를 저장했습니다.")
            except KeyError:
                st.error("OpenAI API 키가 설정되지 않았습니다. st.secrets를 확인하세요.")
            except json.JSONDecodeError:
                st.error("퀴즈 결과를 JSON으로 해석하지 못했습니다.")
            except Exception as error:
                st.error(f"퀴즈 생성 또는 저장 중 문제가 발생했습니다: {error}")

        quiz_result = st.session_state.quiz_result
        if quiz_result:
            for question_number, question in enumerate(
                quiz_result.get("questions", []),
                start=1,
            ):
                st.markdown(f"### {question_number}. {question.get('question', '')}")
                options = question.get("options", [])
                answer_index = int(question.get("answer", -1))
                selected_index = st.radio(
                    "보기",
                    options=range(len(options)),
                    format_func=lambda option: f"{option + 1}. {options[option]}",
                    index=None,
                    key=f"quiz-answer-{summary_record_id}-{question_number}",
                    label_visibility="collapsed",
                )
                if selected_index is not None:
                    if selected_index == answer_index:
                        st.success("정답입니다.")
                    else:
                        st.error(f"오답입니다. 정답: {answer_index + 1}번")
                    st.info(question.get("explanation", "해설이 없습니다."))

with history_tab:
    st.subheader("저장 기록")
    try:
        records_response = (
            get_supabase_client()
            .table("summaries")
            .select("id, filename, summary, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        records = records_response.data or []

        if not records:
            st.info("저장된 요약 기록이 없습니다.")
        for record in records:
            record_columns = st.columns([5, 1])
            with record_columns[0]:
                st.markdown(f"**{record.get('filename', '이름 없음')}**")
                st.caption(
                    f"{record.get('created_at', '시간 없음')} · "
                    f"{get_summary_preview(record.get('summary'))}"
                )
            with record_columns[1]:
                if st.button("삭제", key=f"delete-{record['id']}"):
                    try:
                        get_supabase_client().table("summaries").delete().eq(
                            "id", record["id"]
                        ).execute()
                        st.rerun()
                    except Exception as error:
                        st.error(f"기록 삭제 중 문제가 발생했습니다: {error}")
    except Exception as error:
        st.error(f"저장 기록을 불러오는 중 문제가 발생했습니다: {error}")
