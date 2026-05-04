import json
from src.ai.service import _get_model

async def analyze_spam_score(subject: str, content: str) -> dict:
    """
    Analyzes the subject and content of an email for spam using the generative AI model.
    Returns a dictionary with keys: is_spam (bool), score (float), reason (str).
    """
    prompt = f"""
You are a highly sensitive email spam filter, similar to Gmail's spam detection.
Analyze the following email subject and body.
Determine if it is spam or not.
Provide a spam score from 0.0 to 1.0, where 1.0 means highly likely to be spam, and 0.0 means definitely not spam.
If the score is >= 0.7, consider it spam.
Respond ONLY with a valid JSON object matching this schema without any markdown formatting like ```json:
{{
  "is_spam": boolean,
  "score": float,
  "reason": "string explaining why"
}}

Subject: {subject}
Body: {content}
"""
    model = _get_model()
    try:
        response = await model.generate_content_async(prompt)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        parsed = json.loads(text)
        return {
            "is_spam": bool(parsed.get("is_spam", False)),
            "score": float(parsed.get("score", 0.0)),
            "reason": str(parsed.get("reason", ""))
        }
    except Exception as e:
        return {"is_spam": False, "score": 0.0, "reason": f"Spam evaluation failed: {e}"}
