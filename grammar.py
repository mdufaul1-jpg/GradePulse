import json
from openai import OpenAI

MODEL_NAME = "openai/gpt-4.1"
GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference"


def review_grammar(client: OpenAI, assignment_text: str):
    """
    Performs an OPTIONAL grammar and writing review.

    IMPORTANT:
    This review must NEVER:
    - change submission readiness
    - recommend new rubric content
    - recommend new analysis
    - recommend additional sections

    It ONLY reviews writing quality.
    """

    prompt = f"""
You are GradePulse's optional Grammar & Writing Review.

This is NOT a grading review.
This is NOT a rubric review.
This is NOT a content review.

The assignment has ALREADY been determined to be ready to submit.

Your ONLY job is to identify writing improvements that could make the paper easier to read.

Allowed topics:
- grammar
- punctuation
- spelling
- sentence clarity
- awkward wording
- readability
- transitions
- conciseness

Do NOT suggest:
- adding content
- adding analysis
- adding examples
- adding citations
- adding sections
- changing the organization to improve the grade

Return ONLY valid JSON.

Schema:

{{
    "suggestions":[
        {{
            "issue":"...",
            "suggestion":"..."
        }}
    ]
}}

Return no more than FIVE suggestions.

Assignment:

{assignment_text[:12000]}
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": "You are a professional writing editor. Return only valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return json.loads(response.choices[0].message.content)