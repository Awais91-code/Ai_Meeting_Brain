"""Test configured generation using synthetic evidence; never print credentials."""
from app.services.ai_provider import complete

if __name__ == "__main__":
    try:
        answer = complete([
            {"role":"system", "content":"Answer only from evidence. Evidence: The release deadline is Friday."},
            {"role":"user", "content":"What is the release deadline?"},
        ])
        print("AI response:", answer)
        if "friday" not in answer.lower():
            raise RuntimeError("AI smoke test did not return the expected fact")
    except Exception as error:
        print("AI check failed:", type(error).__name__)
        raise SystemExit(1)
