import asyncio
import json
from unittest.mock import patch, AsyncMock

async def test_spam_detection():
    print("Running spam detection tests...")
    
    with patch('src.ai.spam_detector._get_model') as mock_get_model:
        # Mock the GenerativeModel instance and its generate_content_async method
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model
        
        from src.ai.spam_detector import analyze_spam_score
        
        # 1. Test obvious spam
        spam_subject = "WIN A FREE IPHONE NOW!!!"
        spam_body = "Click here immediately to claim your free iphone. No credit card required. 100% free!"
        print(f"\nTesting spam email: Subject='{spam_subject}'")
        
        # Configure mock for spam
        mock_response_spam = AsyncMock()
        mock_response_spam.text = '{"is_spam": true, "score": 0.95, "reason": "Mentions free iphone and urgency"}'
        mock_model.generate_content_async.return_value = mock_response_spam
        
        spam_res = await analyze_spam_score(spam_subject, spam_body)
        print(f"Result: {spam_res}")
        assert spam_res["is_spam"] is True, "Expected obvious spam to be classified as spam"
        assert spam_res["score"] >= 0.7, "Expected spam score to be >= 0.7"
        
        # 2. Test safe content
        safe_subject = "Weekly Team Update - Q3 Goals"
        safe_body = "Hi team, please find attached the progress report for Q3 goals. Let me know if you have any questions."
        print(f"\nTesting safe email: Subject='{safe_subject}'")
        
        # Configure mock for safe
        mock_response_safe = AsyncMock()
        mock_response_safe.text = '{"is_spam": false, "score": 0.1, "reason": "Looks like standard internal communication"}'
        mock_model.generate_content_async.return_value = mock_response_safe
        
        safe_res = await analyze_spam_score(safe_subject, safe_body)
        print(f"Result: {safe_res}")
        assert safe_res["is_spam"] is False, "Expected safe email to NOT be classified as spam"
        assert safe_res["score"] < 0.7, "Expected safe score to be < 0.7"
        
        print("\nAll spam detection tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_spam_detection())
