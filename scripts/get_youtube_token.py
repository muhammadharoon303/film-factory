"""ONE-TIME setup (needs a browser, e.g. your laptop - afterwards it can stay off forever).
1. Google Cloud Console -> new project -> enable "YouTube Data API v3"
2. OAuth consent screen -> External -> add yourself as test user -> then click PUBLISH APP (In production),
   otherwise refresh tokens expire after 7 days.
3. Credentials -> Create OAuth client ID -> Desktop app -> download JSON as client_secret.json (next to this script's cwd)
4. pip install google-auth-oauthlib && python scripts/get_youtube_token.py
5. Put the 3 printed values into GitHub repo Settings -> Secrets -> Actions.
"""
import json

from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", ["https://www.googleapis.com/auth/youtube.upload"])
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open("client_secret.json"))["installed"]
print("\nYT_CLIENT_ID     =", info["client_id"])
print("YT_CLIENT_SECRET =", info["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)
