from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN_FILE = ".credentials/youtube_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

def main():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    print("Token valid:", creds.valid)
    print("Token expired:", creds.expired)
    print("Has refresh_token:", bool(creds.refresh_token))
    print("Expiry:", creds.expiry)

    if not creds.refresh_token:
        raise RuntimeError("No refresh_token. Regenerate with prompt='consent' and access_type='offline'.")

    print("Attempting token refresh...")
    creds.refresh(Request())

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print("Refresh OK.")
    print("Token valid after refresh:", creds.valid)
    print("New expiry:", creds.expiry)

    youtube = build("youtube", "v3", credentials=creds)

    resp = youtube.channels().list(
        part="snippet,contentDetails",
        mine=True
    ).execute()

    items = resp.get("items", [])
    if not items:
        print("Token valid, but no YouTube channel found.")
        return

    channel = items[0]
    print("Channel detected:", channel["snippet"]["title"])
    print("Channel ID:", channel["id"])

if __name__ == "__main__":
    main()
