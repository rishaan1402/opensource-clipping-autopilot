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
    print("Ada refresh_token:", bool(creds.refresh_token))
    print("Expiry:", creds.expiry)

    if not creds.refresh_token:
        raise RuntimeError("Tidak ada refresh_token. Generate ulang dengan prompt='consent' dan access_type='offline'.")

    print("Mencoba refresh token...")
    creds.refresh(Request())

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print("Refresh OK.")
    print("Token valid setelah refresh:", creds.valid)
    print("Expiry baru:", creds.expiry)

    youtube = build("youtube", "v3", credentials=creds)

    resp = youtube.channels().list(
        part="snippet,contentDetails",
        mine=True
    ).execute()

    items = resp.get("items", [])
    if not items:
        print("Token valid, tapi tidak menemukan channel YouTube.")
        return

    channel = items[0]
    print("Channel terdeteksi:", channel["snippet"]["title"])
    print("Channel ID:", channel["id"])

if __name__ == "__main__":
    main()