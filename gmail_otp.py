import base64
import datetime
import json
import os
import random
import re
import string
import time
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
]

FIRST_NAMES = [
    "alex", "sarah", "jorden", "taylor", "morgan", "casey", "riley",
    "jamie", "avery", "quinn", "blake", "hayden", "dakota", "reese",
    "chloe", "lucas", "mason", "ethan", "logan", "jacob", "mia", "zoe",
]


def generate_random_domain_email(domain: str = "nariwal.shop", prefix: str = "") -> str:
    """
    Generate a realistic unique random email address for the custom domain.
    Example: domain='nariwal.shop' -> 'chloexk482@nariwal.shop'
    """
    clean_domain = domain.strip().lstrip("@")
    if not clean_domain:
        clean_domain = "nariwal.shop"
    base = prefix.strip().lower() if prefix.strip() else random.choice(FIRST_NAMES).lower()
    rand_letters = "".join(random.choices(string.ascii_lowercase, k=3))
    rand_digits = "".join(random.choices(string.digits, k=3))
    return f"{base}{rand_letters}{rand_digits}@{clean_domain}"


def _safe_print(msg: str):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="ignore").decode("ascii"))


class GmailOTPFetcher:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.creds_path = os.path.join(base_dir, "credentials.json")
        self.token_path = os.path.join(base_dir, "token.json")
        self.service = None
        self.connected_email = "Not Connected"
        # Only stores message IDs whose OTP we actually consumed/typed
        self.consumed_message_ids = set()
        # Stores message IDs that existed in the inbox right when F2/F4 was pressed
        self.pre_signup_message_ids = set()
        # Server-side Gmail internalDate (ms) of the latest message when F2/F4 was pressed
        self.baseline_gmail_epoch_ms = 0

    def is_connected(self) -> bool:
        return self.service is not None

    def set_credentials_file(self, path: str):
        self.creds_path = path

    def try_silent_connect(self, log_fn=_safe_print) -> bool:
        """Try connecting silently if a valid token.json already exists (does not open browser)."""
        if not os.path.exists(self.token_path):
            return False
        try:
            with open(self.token_path, "r", encoding="utf-8") as f:
                token_info = json.load(f)
            creds = Credentials.from_authorized_user_info(token_info)
            if not creds.valid:
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(self.token_path, "w", encoding="utf-8") as f:
                        f.write(creds.to_json())
                else:
                    return False
            self.service = build("gmail", "v1", credentials=creds)
            profile = self.service.users().getProfile(userId="me").execute()
            self.connected_email = profile.get("emailAddress", "hussainnariwal@gmail.com")
            log_fn(f"✅ Gmail API Auto-Connected: {self.connected_email}")
            return True
        except Exception:
            self.service = None
            return False

    def authenticate(self, log_fn=_safe_print, force_new: bool = False) -> bool:
        """
        Authenticate with Gmail API using OAuth2 credentials.json and save token.json.
        Opens browser for hussainnariwal@gmail.com consent if token is missing/expired.
        """
        creds = None
        if not force_new and os.path.exists(self.token_path):
            try:
                with open(self.token_path, "r", encoding="utf-8") as f:
                    token_info = json.load(f)
                creds = Credentials.from_authorized_user_info(token_info)
            except Exception:
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token and not force_new:
                try:
                    log_fn("🔄 Refreshing Gmail OAuth token...")
                    creds.refresh(Request())
                except Exception:
                    creds = None

            if not creds:
                if not os.path.exists(self.creds_path):
                    log_fn(f"❌ credentials.json not found at: {self.creds_path}")
                    return False
                log_fn("🌐 Opening Google OAuth login in browser (Login with hussainnariwal@gmail.com)...")
                flow = InstalledAppFlow.from_client_secrets_file(self.creds_path, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(self.token_path, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())
                log_fn("✅ Gmail OAuth token saved to token.json!")

        self.service = build("gmail", "v1", credentials=creds)
        try:
            profile = self.service.users().getProfile(userId="me").execute()
            self.connected_email = profile.get("emailAddress", "hussainnariwal@gmail.com")
        except Exception:
            self.connected_email = "hussainnariwal@gmail.com"
        log_fn(f"✅ Gmail API Connected: {self.connected_email}")
        return True

    def snapshot_existing_messages(self):
        """
        Snapshot current top message IDs and Gmail's server clock right when the user
        starts typing the email (F2/F4), so any new message arriving after this is
        detected 100% reliably without local PC clock skew issues.
        """
        if not self.service:
            self.try_silent_connect()
        if not self.service:
            return
        try:
            res = (
                self.service.users()
                .messages()
                .list(userId="me", maxResults=15, includeSpamTrash=True)
                .execute()
            )
            msgs = res.get("messages", [])
            self.pre_signup_message_ids = {m["id"] for m in msgs}
            if msgs:
                top_msg = (
                    self.service.users()
                    .messages()
                    .get(userId="me", id=msgs[0]["id"], format="minimal")
                    .execute()
                )
                self.baseline_gmail_epoch_ms = int(top_msg.get("internalDate", "0"))
        except Exception:
            pass

    def _extract_body_text(self, payload: dict) -> str:
        """Recursively extract plain/HTML text from Gmail message payload."""
        texts = []
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data")

        if body_data:
            try:
                decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
                if "html" in mime_type:
                    decoded = re.sub(r"<(script|style).*?>.*?</\1>", " ", decoded, flags=re.S | re.I)
                    decoded = re.sub(r"<[^>]+>", " ", decoded)
                texts.append(decoded)
            except Exception:
                pass

        for part in payload.get("parts", []):
            texts.append(self._extract_body_text(part))

        return "\n".join(t for t in texts if t)

    @staticmethod
    def extract_otp_from_text(text: str, custom_regex: str = "") -> Optional[str]:
        """
        Extract OTP verification code from email subject/snippet/body.
        Supports numeric 4-8 digit codes, alphanumeric 6-char codes, or custom regex.
        """
        if not text:
            return None

        clean = re.sub(r"\s+", " ", text)

        if custom_regex.strip():
            try:
                m = re.search(custom_regex.strip(), clean)
                if m:
                    return m.group(1) if m.groups() else m.group(0)
            except Exception:
                pass

        # 1. Contextual 4-8 digit numeric code near keywords (code, otp, verification, verify, login, pin)
        kw_num = r"(?:code|otp|verification|verify|login|pin|passcode)[^0-9]{1,40}\b(\d{4,8})\b"
        m = re.search(kw_num, clean, flags=re.IGNORECASE)
        if m:
            return m.group(1)

        # 2. Standalone 6-digit numeric code (most common for Meta, Google & website signups)
        six_digits = re.findall(r"\b(\d{6})\b", clean)
        if six_digits:
            return six_digits[0]

        # 3. Contextual 6-character alphanumeric uppercase/digit code
        kw_alnum = r"(?:code|otp|verification|verify)[^A-Za-z0-9]{1,30}\b([A-Z0-9]{6})\b"
        m2 = re.search(kw_alnum, clean, flags=re.IGNORECASE)
        if m2:
            cand = m2.group(1)
            if any(ch.isdigit() for ch in cand):
                return cand

        # 4. Fallback 4-8 digit number (skipping years like 2024..2029)
        other_digits = re.findall(r"\b(\d{4,8})\b", clean)
        for c in other_digits:
            if len(c) == 4 and c.startswith("202"):
                continue
            return c

        return None

    def wait_for_otp(
        self,
        target_email: Optional[str] = None,
        min_epoch_ms: int = 0,
        timeout_sec: int = 90,
        poll_interval: float = 1.0,
        custom_regex: str = "",
        trash_after_read: bool = False,
        log_fn=_safe_print,
        stop_check_fn=lambda: False,
    ) -> Optional[str]:
        """
        Ultra-Fast (<1s) Direct Mailbox OTP Fetcher:
        - Queries `messages.list(userId='me', maxResults=8)` directly WITHOUT `q=` search index lag!
        - Checks newest messages first.
        - Matches `target_email` (or any forwarded email on `@nariwal.shop` / `mobile.j3pro@gmail.com`).
        - Extracts OTP from Subject + Snippet first (instant!), then full body.
        """
        if not self.service:
            if not self.try_silent_connect(log_fn=log_fn):
                if not self.authenticate(log_fn=log_fn):
                    return None

        now_ms = int(time.time() * 1000)
        if min_epoch_ms <= 0:
            # Look back 3 minutes if triggered manually via F7 or Test button
            effective_min_ms = now_ms - 180_000
        else:
            # Allow a generous 45-second grace window to prevent PC clock skew or fast email arrival issues
            effective_min_ms = min_epoch_ms - 45_000

        log_fn(
            f"📩 Checking Gmail ({self.connected_email}) for OTP | Target: [{target_email or 'Latest Forwarded Email'}]..."
        )

        start_wait = time.perf_counter()
        attempt = 0

        while time.perf_counter() - start_wait < timeout_sec:
            if stop_check_fn():
                log_fn("⏹ OTP wait stopped.")
                return None

            attempt += 1
            try:
                # Direct mailbox list (NO `q=` filter -> zero Gmail search indexing delay!)
                res = (
                    self.service.users()
                    .messages()
                    .list(userId="me", maxResults=8, includeSpamTrash=True)
                    .execute()
                )
                messages = res.get("messages", [])

                for msg_meta in messages:
                    msg_id = msg_meta["id"]

                    # Skip only if we already consumed & typed this exact message's OTP
                    if msg_id in self.consumed_message_ids:
                        continue

                    # If we took a pre-signup snapshot right before F2/F4, skip messages that were already in the inbox before F2/F4
                    # UNLESS the user didn't press F2/F4 (e.g. manual F7 test)
                    if min_epoch_ms > 0 and msg_id in self.pre_signup_message_ids:
                        continue

                    msg = (
                        self.service.users()
                        .messages()
                        .get(userId="me", id=msg_id, format="full")
                        .execute()
                    )

                    internal_date_ms = int(msg.get("internalDate", "0"))

                    # Check freshness: either arrived after pre-signup Gmail baseline or within effective time window
                    if self.baseline_gmail_epoch_ms > 0 and min_epoch_ms > 0:
                        if internal_date_ms < (self.baseline_gmail_epoch_ms - 10_000):
                            continue
                    elif internal_date_ms < effective_min_ms:
                        continue

                    payload = msg.get("payload", {})
                    headers = payload.get("headers", [])
                    subject = ""
                    recipient_headers = ""
                    to_display = ""
                    for h in headers:
                        hname = h.get("name", "").lower()
                        hval = h.get("value", "")
                        if hname == "subject":
                            subject = hval
                        elif hname == "to":
                            to_display = hval
                            recipient_headers += " " + hval
                        elif hname in (
                            "delivered-to",
                            "x-forwarded-to",
                            "x-forwarded-for",
                            "x-original-to",
                            "envelope-to",
                            "cc",
                        ):
                            recipient_headers += " " + hval

                    snippet = msg.get("snippet", "")
                    body_text = self._extract_body_text(payload)
                    fast_text = f"{subject}\n{snippet}"
                    full_text = f"{subject}\n{snippet}\n{body_text}"

                    # Recipient check: match target_email if specified
                    if target_email:
                        combined_haystack = (recipient_headers + " " + full_text).lower()
                        if target_email.lower() not in combined_haystack:
                            continue

                    # Try fast extraction from Subject + Snippet first, then full body
                    otp = self.extract_otp_from_text(fast_text, custom_regex=custom_regex)
                    if not otp:
                        otp = self.extract_otp_from_text(full_text, custom_regex=custom_regex)

                    if otp:
                        self.consumed_message_ids.add(msg_id)
                        recv_time_str = datetime.datetime.fromtimestamp(internal_date_ms / 1000.0).strftime("%H:%M:%S")
                        matched_for = target_email or to_display or "Forwarded Inbox"
                        elapsed_fetch = time.perf_counter() - start_wait
                        log_fn(
                            f"🎉 FRESH OTP Found in {elapsed_fetch:.1f}s! Sent To: [{matched_for}] | Code: [{otp}] | Email Time: {recv_time_str}"
                        )
                        if trash_after_read:
                            try:
                                self.service.users().messages().trash(userId="me", id=msg_id).execute()
                            except Exception:
                                pass
                        return otp

            except Exception as e:
                log_fn(f"⚠️ Gmail poll attempt #{attempt}: {e}")

            end_poll = time.perf_counter() + poll_interval
            while time.perf_counter() < end_poll:
                if stop_check_fn():
                    return None
                time.sleep(0.15)

        log_fn(f"❌ Timeout ({timeout_sec}s): No fresh OTP email arrived for [{target_email or 'signup'}].")
        return None
