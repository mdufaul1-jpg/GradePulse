import streamlit as st
from docx import Document
from pypdf import PdfReader
import io

st.set_page_config(page_title="GradePulse", page_icon="📘", layout="wide")

st.title("📘 GradePulse")
st.subheader("Know when your assignment is ready to submit.")

st.write(
    "Upload your completed assignment and any grading context "
    "(rubric, instructions, expanded details, professor guidance). "
    "GradePulse evaluates whether your work appears ready to meet your target grade."
)

st.divider()

target_grade = st.number_input(
    "Target grade (%)",
    min_value=0,
    max_value=100,
    value=90,
    step=1,
)

deliverable_file = st.file_uploader(
    "Upload completed assignment",
    type=["pdf", "docx", "txt"],
    accept_multiple_files=False,
)

context_files = st.file_uploader(
    "Upload grading context files",
    type=["pdf", "docx", "txt"],
    accept_multiple_files=True,
)


def extract_text_from_file(uploaded_file):
    if uploaded_file is None:
        return ""

    file_name = uploaded_file.name.lower()
    file_bytes = uploaded_file.read()

    try:
        if file_name.endswith(".txt"):
            return file_bytes.decode("utf-8", errors="ignore")

        if file_name.endswith(".docx"):
            doc = Document(io.BytesIO(file_bytes))
            return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

        if file_name.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(file_bytes))
            text = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text.append(page_text)
            return "\n".join(text)

    except Exception as e:
        return f"[Error reading file: {e}]"

    return ""


def check_evaluability(deliverable_text, context_text):
    issues = []

    if not deliverable_text.strip():
        issues.append("No readable completed assignment was provided.")

    if not context_text.strip():
        issues.append("No readable grading context was provided.")

    if len(context_text.strip()) < 300:
        issues.append("Grading context appears too short to reliably identify criteria.")

    if len(deliverable_text.strip()) < 300:
        issues.append("Completed assignment appears too short to evaluate reliably.")

    if issues:
        return False, issues

    return True, []


if st.button("Evaluate Assignment"):
    deliverable_text = extract_text_from_file(deliverable_file)

    context_texts = []
    if context_files:
        for file in context_files:
            context_texts.append(f"--- {file.name} ---\n{extract_text_from_file(file)}")

    context_text = "\n\n".join(context_texts)

    st.divider()

    evaluable, issues = check_evaluability(deliverable_text, context_text)

    if not evaluable:
        st.error("🔴 Unable to Evaluate")
        st.write("GradePulse cannot confidently estimate a grade yet.")
        st.write("Please address the following:")
        for issue in issues:
            st.write(f"- {issue}")

    else:
        st.success("Files uploaded and readable.")
        st.info(
            "Evaluation engine coming next: this step will connect the uploaded text "
            "to GitHub Models and apply the GradePulse decision rules."
        )

        with st.expander("Preview completed assignment text"):
            st.text_area("Completed assignment", deliverable_text[:5000], height=300)

        with st.expander("Preview grading context text"):
            st.text_area("Grading context", context_text[:5000], height=300)

st.divider()

st.caption(
    "GradePulse constraint: the app may only recommend revisions when it has enough "
    "information to evaluate the work and the estimated grade is below the target."
)