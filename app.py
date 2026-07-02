import os
import io
import json
import streamlit as st
from docx import Document
from pypdf import PdfReader
from openai import OpenAI

st.set_page_config(page_title="GradePulse", page_icon="📘", layout="wide")

MODEL_NAME = "openai/gpt-4.1"
GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference"


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


def check_evaluability(deliverable_text, requirements_text):
    issues = []

    if not deliverable_text.strip():
        issues.append("No readable completed assignment was provided.")

    if not requirements_text.strip():
        issues.append("No readable assignment requirements, rubric, or guidance were provided.")

    if len(requirements_text.strip()) < 300:
        issues.append("Uploaded guidance appears too short to reliably identify assignment expectations.")

    if len(deliverable_text.strip()) < 300:
        issues.append("Completed assignment appears too short to evaluate reliably.")

    return issues


def soften_high_target_confidence(result, target_grade):
    if (
        target_grade >= 95
        and result.get("status") == "Ready to Submit"
        and result.get("confidence") == "High"
    ):
        result["confidence"] = "Moderate"
        result["summary"] = (
            result.get("summary", "")
            + " Because the selected target is exceptionally high, this recommendation should be interpreted as submission readiness rather than a prediction of a perfect or near-perfect instructor score."
        )

    return result


def call_github_model(deliverable_text, requirements_text, target_grade):
    token = os.getenv("GITHUB_TOKEN")

    if not token:
        return {
            "status": "Unable to Evaluate",
            "confidence": "Low",
            "summary": "GitHub token is not set. The app cannot connect to GitHub Models.",
            "criteria": [],
            "top_improvements": [],
        }

    client = OpenAI(base_url=GITHUB_MODELS_ENDPOINT, api_key=token)

    prompt = f"""
You are GradePulse, a submission-readiness assistant.

Purpose:
GradePulse helps students decide whether submitting an assignment is a reasonable decision for a user-selected target grade.
GradePulse is NOT a grading tool and must NOT predict or display a numeric grade.

Core philosophy:
- GradePulse should reduce unnecessary editing.
- GradePulse should catch meaningful omissions or weaknesses.
- GradePulse should not encourage perfectionism or invent problems.
- A submission can be ready to submit even if an instructor might still give feedback.

Important behavior rules:
- Do not invent missing assignment requirements.
- Do not invent evidence from the completed assignment.
- Evaluate only against the uploaded instructions, rubrics, and guidance.
- If you cannot find evidence in the completed assignment, say "No supporting evidence found."
- Do not use numeric estimated grades in your response.
- Do not provide optional polish suggestions when the status is Ready to Submit.

Decision rules:
Ready to Submit:
- Return this when the uploaded assignment reasonably satisfies the uploaded grading criteria for the selected target.
- Do not search for optional improvements simply because they could exist.
- Do not require perfection.

Revision Required:
- Return this only when meaningful deficiencies exist that make the selected target appear unreasonable.
- The deficiencies should be significant enough that a reasonable instructor would likely deduct points.
- Provide exactly three improvements.

Unable to Evaluate:
- Return this only when there is insufficient information to make a reliable readiness decision.

Special guidance for high targets 95-100:
- Apply a somewhat stricter review.
- However, do NOT invent weaknesses simply because the target is high.
- If the submission appears complete and reasonably satisfies the uploaded materials, it may still be Ready to Submit.
- In those cases, confidence should usually be Moderate unless the evidence is exceptionally strong.

Target grade selected by user: {target_grade}

UPLOADED INSTRUCTIONS, RUBRICS, AND GUIDANCE:
{requirements_text[:12000]}

COMPLETED ASSIGNMENT:
{deliverable_text[:12000]}

Return ONLY valid JSON using this schema:
{{
  "status": "Ready to Submit" | "Revision Required" | "Unable to Evaluate",
  "confidence": "High" | "Medium" | "Low",
  "summary": "brief explanation of the readiness decision",
  "criteria": [
    {{
      "criterion": "name of requirement, rubric area, or expectation",
      "evidence_found": "specific evidence from completed assignment or 'No supporting evidence found'",
      "assessment": "brief assessment based only on uploaded materials"
    }}
  ],
  "top_improvements": [
    {{
      "improvement": "specific change",
      "why_it_matters": "criterion or requirement affected"
    }}
  ]
}}
"""

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": "You are a careful evaluator. Return only valid JSON. Never invent evidence.",
                },
                {"role": "user", "content": prompt},
            ],
        )

        raw_text = response.choices[0].message.content
        result = json.loads(raw_text)
        return soften_high_target_confidence(result, target_grade)

    except json.JSONDecodeError:
        return {
            "status": "Unable to Evaluate",
            "confidence": "Low",
            "summary": "The model responded, but the response was not valid JSON.",
            "criteria": [],
            "top_improvements": [],
        }

    except Exception as e:
        return {
            "status": "Unable to Evaluate",
            "confidence": "Low",
            "summary": f"Model connection error: {e}",
            "criteria": [],
            "top_improvements": [],
        }


st.title("📘 GradePulse")
st.subheader("Know when your assignment is ready to submit.")

st.write(
    "Upload your completed assignment and any documents that define how it will be evaluated. "
    "GradePulse checks whether submitting now appears reasonable for your selected target."
)

st.info(
    "GradePulse is intended for submission-readiness reassurance only. It cannot guarantee your project "
    "will score at or above your target because instructors may use additional course content, expectations, "
    "and professional judgment when applying a rubric. GradePulse compares your uploaded assignment against "
    "the uploaded instructions, rubric, and guidance to determine whether your target grade appears to be a "
    "reasonable outcome based on the information provided."
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

requirements_files = st.file_uploader(
    "Upload instructions, rubrics, and guidance",
    type=["pdf", "docx", "txt"],
    accept_multiple_files=True,
)

if st.button("Evaluate Assignment"):
    deliverable_text = extract_text_from_file(deliverable_file)

    requirements_texts = []
    if requirements_files:
        for file in requirements_files:
            requirements_texts.append(f"--- {file.name} ---\n{extract_text_from_file(file)}")

    requirements_text = "\n\n".join(requirements_texts)

    st.divider()

    issues = check_evaluability(deliverable_text, requirements_text)

    if issues:
        st.error("🔴 Unable to Evaluate")
        st.write("GradePulse cannot confidently evaluate submission readiness yet.")
        for issue in issues:
            st.write(f"- {issue}")

    else:
        with st.spinner("Evaluating submission readiness with GitHub Models..."):
            result = call_github_model(deliverable_text, requirements_text, target_grade)

        status = result.get("status", "Unable to Evaluate")
        confidence = result.get("confidence", "Low")

        if status == "Ready to Submit":
            st.success("🟢 Ready to Submit")
            st.metric("Confidence", confidence)
            st.write(result.get("summary", "The assignment appears ready to submit for the selected target."))
            st.subheader("No revisions recommended.")

        elif status == "Revision Required":
            st.warning("🟡 Revision Required")
            st.metric("Target Grade", target_grade)
            st.metric("Confidence", confidence)
            st.write(result.get("summary", ""))

            st.subheader("Top 3 Improvements")
            improvements = result.get("top_improvements", [])
            if improvements:
                for item in improvements[:3]:
                    st.write(f"**{item.get('improvement', '')}**")
                    st.write(f"- Why it matters: {item.get('why_it_matters', '')}")
            else:
                st.write("No specific improvements were returned.")

        else:
            st.error("🔴 Unable to Evaluate")
            st.metric("Confidence", confidence)
            st.write(result.get("summary", "Not enough information to evaluate reliably."))

        with st.expander("Criterion-by-criterion review"):
            criteria = result.get("criteria", [])
            if criteria:
                for criterion in criteria:
                    st.write(f"**{criterion.get('criterion', '')}**")
                    st.write(f"- Evidence found: {criterion.get('evidence_found', '')}")
                    st.write(f"- Assessment: {criterion.get('assessment', '')}")
                    st.divider()
            else:
                st.write("No criterion review was returned.")

st.divider()

st.caption(
    "GradePulse constraint: the app only recommends revisions when it has enough information "
    "to evaluate the work and determines the selected target is not yet a reasonable outcome."
)