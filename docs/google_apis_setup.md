# Google APIs for Marc (Gmail + Calendar + Drive + Maps)

## 1. Enable APIs

Same Google Cloud project as your Desktop OAuth client:

1. [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com)
2. [Google Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com)
3. [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com)
4. Maps (API key, not OAuth):
   - [Places API](https://console.cloud.google.com/apis/library/places-backend.googleapis.com)
   - [Directions API](https://console.cloud.google.com/apis/library/directions-backend.googleapis.com)
   - Create a key: [Credentials](https://console.cloud.google.com/apis/credentials) → **API key**

Add your Google account under **OAuth consent screen → Test users**.

## 2. Files / env

| Item | Path / env |
|------|------------|
| OAuth Desktop JSON | `data/gmail_credentials.json` |
| Token (after auth) | `data/google_token.json` |
| Gemini planner | `.env` → `GEMINI_API_KEY=` |
| Maps (optional) | `.env` → `GOOGLE_MAPS_API_KEY=` (falls back to Gemini key) |

## 3. Authorize (re-consent for Calendar + Drive)

```powershell
cd C:\Users\ranjith\mark-laptop
python main.py google-auth --force
```

(`gmail-auth` is an alias.)

## 4. Try

```text
summarize my email
what's on my calendar
search drive for resume
directions to airport
maps coffee near me
```

## Scopes

- `gmail.modify`
- `calendar`
- `drive.readonly`
