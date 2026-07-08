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


def instructor_guidance(style):
    if style == "Lenient":
        return (
            "Instructor grading style: Lenient. Only require revisions for clear, meaningful gaps. "
            "Do not recommend revisions for minor polish, stylistic preference, or small ambiguities if the uploaded assignment substantially meets the criteria."
        )
    if style == "Average":
        return (
            "Instructor grading style: Average. Use a balanced review. Require revisions when rubric coverage is meaningfully incomplete, weak, or unclear."
        )
    if style == "Strict":
        return (
            "Instructor grading style: Strict. Require stronger, more explicit evidence before recommending Ready to Submit. "
            "If a rubric area is only implied, thinly supported, or difficult to locate, treat that as a meaningful risk."
        )
    return (
        "Instructor grading style: Unknown. Do not assume the instructor is lenient or strict. "
        "Use the uploaded rubric and instructions as the primary standard."
    )


def clean_result(result, target_grade):
    status = result.get("status", "Unable to Evaluate")

    if status == "Ready to Submit":
        result["top_improvements"] = []

    if status == "Revision Required":
        improvements = result.get("top_improvements", [])

        if len(improvements) > 3:
            result["top_improvements"] = improvements[:3]

        if len(improvements) < 3:
            filler = [
                {
                    "improvement": "Add direct evidence that clearly addresses a missing or weak rubric requirement.",
                    "why_it_matters": "GradePulse should only count evidence when it directly supports the uploaded requirement."
                },
                {
                    "improvement": "Revise the assignment so the main topic clearly matches the uploaded assignment instructions.",
                    "why_it_matters": "A topic mismatch makes the selected target unlikely even if the writing is otherwise clear."
                },
                {
                    "improvement": "Use explicit wording from the assignment instructions or rubric to show each requirement is addressed.",
                    "why_it_matters": "Direct alignment reduces ambiguity and makes the submission easier to evaluate."
                },
            ]
            result["top_improvements"] = improvements + filler[:3 - len(improvements)]

    if status == "Unable to Evaluate":
        result["top_improvements"] = []

    if (
        target_grade >= 95
        and result.get("status") == "Ready to Submit"
        and result.get("confidence") == "High"
    ):
        result["confidence"] = "Medium"
        result["summary"] = (
            result.get("summary", "")
            + " Because the selected target is exceptionally high, this recommendation should be interpreted as submission readiness rather than a prediction of a perfect or near-perfect instructor score."
        )

    return result


def call_github_model(deliverable_text, requirements_text, target_grade, grading_style):
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
    style_guidance = instructor_guidance(grading_style)

    prompt = f"""
You are GradePulse, an assignment submission-readiness evaluator.

Purpose:
GradePulse helps students decide whether submitting an assignment is a reasonable decision for a user-selected target grade.
GradePulse is NOT a grading tool and must NOT predict or display a numeric grade.

Core philosophy:
- GradePulse should reduce unnecessary editing.
- GradePulse should catch meaningful omissions, mismatches, or weaknesses.
- GradePulse should not encourage perfectionism or invent problems.
- A submission can be ready to submit even if an instructor might still give feedback.
- This is a submission-readiness evaluation, not an editing service.

Instructor context:
{style_guidance}

Evidence rules:
- Evaluate ONLY against the uploaded assignment, instructions, rubrics, and guidance.
- Never invent assignment requirements, rubric criteria, or missing expectations.
- Never invent evidence from the completed assignment.
- Never assume a requirement is met unless the completed assignment directly supports it.
- Do not count loosely related ideas as evidence.
- Do not infer that a rubric criterion is partially satisfied from vaguely related concepts.
- Evidence must be responsive to the specific rubric criterion or instruction being evaluated.
- If evidence is related but not actually responsive to the requirement, say that clearly.
- If evidence cannot be located, say "No supporting evidence found."
- If evidence is incomplete or ambiguous, lower confidence instead of guessing.
- Do not reward or penalize criteria that are not explicitly included in the uploaded rubric, instructions, or guidance.
- Do not use numeric estimated grades in your response.

Confidence rules:
- Confidence means confidence in the readiness decision, not confidence in the final instructor grade.
- Use High confidence when there is a clear match or clear mismatch between the assignment and the uploaded criteria.
- Use Medium confidence when the decision depends on judgment, interpretation, quality, or borderline evidence.
- Use Low confidence only when information is missing, unreadable, insufficient, conflicting, or too ambiguous to evaluate reliably.
- A clearly wrong assignment matched to a clear rubric should usually be Revision Required with High confidence.

Decision rules:
Ready to Submit:
- Return this when the uploaded assignment reasonably satisfies the uploaded grading criteria for the selected target and instructor grading style.
- Do not search for optional improvements simply because they could exist.
- Do not require perfection.
- If status is Ready to Submit, return ZERO improvements.

Revision Required:
- Return this when meaningful deficiencies, mismatches, or omissions make the selected target appear unreasonable for the selected instructor grading style.
- The deficiencies should be significant enough that a reasonable instructor would likely deduct points or question whether the target has been met.
- Recommend revisions only if they would materially improve the likelihood of reaching the user's selected target.
- If status is Revision Required, return EXACTLY THREE meaningful, high-impact improvements. No more and no fewer.

Unable to Evaluate:
- Return this only when there is insufficient information to make a reliable readiness decision.
- Explain what information is missing.
- If status is Unable to Evaluate, return ZERO improvements.

Special guidance for high targets 95-100:
- Apply a somewhat stricter review.
- However, do NOT invent weaknesses simply because the target is high.
- If the submission appears complete and reasonably satisfies the uploaded materials, it may still be Ready to Submit.
- In those cases, confidence should usually be Medium unless the evidence is exceptionally strong.

Target grade selected by user: {target_grade}
Instructor grading style selected by user: {grading_style}

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
                    "content": """
You are GradePulse, an assignment submission-readiness evaluator.

Rules:
1. Never invent requirements, rubric criteria, assignment content, or evidence.
2. Evidence must directly support the specific requirement being evaluated.
3. Do not treat loosely related content as partial evidence.
4. If content is related but not responsive to the rubric, say it is not responsive.
5. Confidence means confidence in your readiness decision, not confidence in the final instructor score.
6. Clear match or clear mismatch = High confidence.
7. Borderline quality judgment = Medium confidence.
8. Missing, unreadable, conflicting, or insufficient information = Low confidence.
9. Ready to Submit must return zero improvements.
10. Revision Required must return exactly three improvements.
11. Unable to Evaluate must return zero improvements and explain what is missing.
12. Always return valid JSON that exactly matches the required schema.
"""
                },
                {"role": "user", "content": prompt},
            ],
        )

        result = json.loads(response.choices[0].message.content)
        return clean_result(result, target_grade)

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

grading_style = st.radio(
    "Instructor grading style",
    ["Unknown", "Lenient", "Average", "Strict"],
    horizontal=True,
    help="Use this only if you have a sense of how the instructor typically applies rubrics."
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
            result = call_github_model(
                deliverable_text,
                requirements_text,
                target_grade,
                grading_style
            )

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
            st.metric("Instructor Style", grading_style)
            st.metric("Confidence", confidence)
            st.write(result.get("summary", ""))

            st.subheader("Top 3 Improvements")
            improvements = result.get("top_improvements", [])
            if improvements:
                for item in improvements[:3]:
                    st.write(f"**{item.get('improvement', '')}**")
                    st.write(f"- Why it matters: {item.get('why_it_matters', '')}")

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
    "GradePulse constraint: Ready to Submit returns no improvements; Revision Required returns exactly three improvements; Unable to Evaluate explains what is missing."
)