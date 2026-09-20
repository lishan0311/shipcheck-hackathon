# Optional Gemini AI fallback

ShipCheck uses TF-IDF and Logistic Regression as its primary five-category
classifier. Gemini is an optional fallback for messages that the local model
marks as uncertain and for seven fields that the deterministic parser cannot
locate. It is not used to decide whether SI and BL values match.

## Behaviour

1. The local classifier routes confident messages without calling Gemini.
2. For an uncertain message, Gemini may propose one of the five allowed
   categories in structured JSON.
3. ShipCheck accepts a category suggestion only at or above `GEMINI_MIN_CONFIDENCE`
   (default `0.90`). Lower-confidence suggestions remain in human review.
4. For field assistance, Gemini can fill only a field marked `Required field not
   found.` It cannot replace a deterministic extraction. Its proposed value and
   quoted evidence must both occur in the attachment text, and the existing
   field normalizer must accept the value.
5. Gemini quota errors (`429`), rejected credentials, network errors, invalid
   output and timeouts never fail an email or the web application. The email
   stays in the existing human-review route.
6. The server stops calling Gemini after a quota error, after three consecutive
   failures, or after `GEMINI_MAX_REQUESTS` calls. Restarting the service resets
   this local circuit breaker.

## Configuration

Create an API key in Google AI Studio, then add only the key to the root `.env`:

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash-lite
GEMINI_TIMEOUT_SECONDS=8
GEMINI_MAX_REQUESTS=20
GEMINI_MIN_CONFIDENCE=0.90
```

Restart the backend. `GET /api/health` includes an `ai_assistant` object that
shows whether Gemini is configured, enabled, rate-limited or circuit-broken.
Never commit `.env` or expose the key through a `VITE_` variable.

For Render, add the same values in the service environment settings, then
redeploy. Keep the request limit conservative during the hackathon demo.
