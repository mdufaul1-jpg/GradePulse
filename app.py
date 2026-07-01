import os
import io
import json
import streamlit as st
from docx import Document
from pypdf import PdfReader
from openai import OpenAI

st.set_page_config(page_title="GradePulse", page_icon="📘", layout="wide")

MODEL_NAME = "openai/gpt-5"
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
        issues.append("No readable assignment requirements were provided.")

    if len(requirements_text.strip()) < 300:
        issues.append("Assignment requirements appear too short to reliably identify expectations.")

    if len(deliverable_text.strip()) < 300:
        issues.append("Completed assignment appears too short to evaluate reliably.")

    return issues


def call_github_model(deliverable_text, requirements_text, target_grade):
    token = os.getenv("GITHUB_TOKEN")

    if not token:
        return {
            "status": "Unable to Evaluate",
            "estimated_grade": None,
            "confidence": "Low",
            "summary": "GitHub token is not set. The app cannot connect to GitHub Models.",
            "criteria": [],
            "top_improvements": [],
        }

    client = OpenAI(
        base_url=GITHUB_MODELS_ENDPOINT,
        api_key=token,
    )

    prompt = f"""
You are GradePulse, a submission readiness evaluator.

Core rules:
- Do not invent missing assignment requirements.
- Evaluate only against the uploaded assignment requirements, rubrics, and guidance.
- If there is not enough information to evaluate reliably, return "Unable to Evaluate."
- If estimated_grade >= target_grade and confidence is High, return "Ready to Submit."
- If estimated_grade < target_grade and confidence is High, return "Revision Required."
- If target is met, do not recommend edits.
- If revision is required, provide exactly the top 3 specific improvements most likely to help the assignment reach the target.

Target grade: {target_grade}

ASSIGNMENT REQUIREMENTS:
{requirements_text[:12000]}

COMPLETED ASSIGNMENT:
{deliverable_text[:12000]}

Return ONLY valid JSON using this schema:
{{
  "status": "Ready to Submit" | "Revision Required" | "Unable to Evaluate",
  "estimated_grade": number or null,
  "confidence": "High" | "Medium" | "Low",
  "summary": "brief explanation",
  "criteria": [
    {{
      "criterion": "name of criterion or requirement",
      "evidence_found": "specific evidence from assignment or 'Not found'",
      "assessment": "brief assessment",
      "score_estimate": "points/percent/qualitative estimate if available"
    }}
  ],
  "top_improvements": [
    {{
      "improvement": "specific change",
      "why_it_matters": "criterion or requirement affected",
      "estimated_impact": "estimated point or grade impact"
    }}
  ]
}}
"""

    response = client.chat.completions.create(
       model="openai/gpt-5",
        messages=[
            {"role": "system", "content": "You are a careful evaluator that returns only valid JSON."},
            {"role": "user", "content": prompt},
        ],
    )

    raw_text = response.choices[0].message.content

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {
            "status": "Unable to Evaluate",
            "estimated_grade": None,
            "confidence": "Low",
            "summary": "The model returned a response that was not valid JSON.",
            "criteria": [],
            "top_improvements": [],
            "raw_response": raw_text,
        }


st.title("📘 GradePulse")
st.subheader("Know when your assignment is ready to submit.")

st.write(
    "Upload your completed assignment and any documents that define how it will be evaluated. "
    "GradePulse checks whether your work appears ready to meet your target grade."
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
        st.write("GradePulse cannot confidently estimate a grade yet.")
        for issue in issues:
            st.write(f"- {issue}")

    else:
        with st.spinner("Evaluating with GitHub Models..."):
            result = call_github_model(deliverable_text, requirements_text, target_grade)

        status = result.get("status", "Unable to Evaluate")
        estimated_grade = result.get("estimated_grade")
        confidence = result.get("confidence", "Low")

        if status == "Ready to Submit":
            st.success("🟢 Ready to Submit")
            st.metric("Estimated Grade", estimated_grade)
            st.metric("Confidence", confidence)
            st.write(result.get("summary", "Target appears to be met."))
            st.subheader("No revisions recommended.")

        elif status == "Revision Required":
            st.warning("🟡 Revision Required")
            st.metric("Estimated Grade", estimated_grade)
            st.metric("Target Grade", target_grade)
            st.metric("Confidence", confidence)
            st.write(result.get("summary", ""))

            st.subheader("Top 3 Improvements")
            for item in result.get("top_improvements", []):
                st.write(f"**{item.get('improvement', '')}**")
                st.write(f"- Why it matters: {item.get('why_it_matters', '')}")
                st.write(f"- Estimated impact: {item.get('estimated_impact', '')}")

        else:
            st.error("🔴 Unable to Evaluate")
            st.metric("Confidence", confidence)
            st.write(result.get("summary", "Not enough information to evaluate reliably."))

        with st.expander("Criterion-by-criterion review"):
            for criterion in result.get("criteria", []):
                st.write(f"**{criterion.get('criterion', '')}**")
                st.write(f"- Evidence found: {criterion.get('evidence_found', '')}")
                st.write(f"- Assessment: {criterion.get('assessment', '')}")
                st.write(f"- Score estimate: {criterion.get('score_estimate', '')}")

        if "raw_response" in result:
            with st.expander("Raw model response"):
                st.write(result["raw_response"])

st.divider()

st.caption(
    "GradePulse constraint: the app only recommends revisions when it has enough information "
    "to evaluate the work and the estimated grade is below the target."
)