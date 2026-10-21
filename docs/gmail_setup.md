# Gmail setup for Marc

See the full Google setup (Gmail + Calendar + Drive + Maps): [google_apis_setup.md](google_apis_setup.md).

Marc can search, summarize, and send Gmail after a one-time OAuth.

## 1. Google Cloud

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable **Gmail API** (APIs & Services → Library → Gmail API → Enable).
4. Configure the **OAuth consent screen** (External is fine for personal use; add your Google account as a test user).
5. Create credentials: **OAuth client ID** → Application type **Desktop app**.
6. Download the JSON client secrets file.

## 2. Install files

Copy the downloaded JSON to:

```text
C:\Users\ranjith\mark-laptop\data\gmail_credentials.json
```

Install Python packages if needed:

```powershell
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
```

## 3. Authorize

```powershell
cd C:\Users\ranjith\mark-laptop
python main.py google-auth
```

A browser window opens — sign in and Allow. Token is saved to `data/google_token.json`.

Readonly-only (no send):

```powershell
python main.py google-auth --readonly
```

After enabling Calendar/Drive APIs, re-consent:

```powershell
python main.py google-auth --force
```

## 4. Try it

```text
summarize my email
what was the last email I have received
search mail for invoice
send email to alex saying hello
```

Put real addresses in `config/contacts.json` first — empty or `example.com` emails are refused.

If you hear “Authorize Gmail first…”, credentials or token are missing — repeat steps 2–3.

## Scopes

- Default `google-auth`: `gmail.modify` + `calendar` + `drive.readonly`.
- `--readonly`: readonly variants only (summarize/search; compose will ask to re-auth).
