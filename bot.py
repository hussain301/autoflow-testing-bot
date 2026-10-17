import csv
import ctypes
import datetime
import json
import os
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk
from pynput import keyboard, mouse
from pynput.keyboard import Controller as KeyboardController, Key, KeyCode
from pynput.mouse import Button, Controller as MouseController

from gmail_otp import GmailOTPFetcher, generate_random_domain_email
from smart_vision import (
    extract_anchor_info_at_cursor,
    grab_full_screen_pil,
    pil_to_base64,
    smart_locate_target_on_screen,
)

# Set CustomTkinter macOS Dark Appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Win32 constants for full-screen hardware input
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000


def apply_macos_dark_window_style(window):
    """Enable Windows 11 immersive dark titlebar & rounded corners via DWM API."""
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark_mode = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode)
        )
        # DWMWA_WINDOW_CORNER_PREFERENCE = 33 (2 = DWMWCP_ROUND)
        corner_pref = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref)
        )
    except Exception:
        pass


def get_full_screen_bounds():
    """Get full screen width, height, and virtual screen origin (supports single & multi-monitor)."""
    user32 = ctypes.windll.user32
    vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    vw = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    vh = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    pw = user32.GetSystemMetrics(0)   # SM_CXSCREEN (Primary Width)
    ph = user32.GetSystemMetrics(1)   # SM_CYSCREEN (Primary Height)
    if vw <= 0 or vh <= 0:
        vw, vh = pw, ph
    return {
        "origin_x": vx,
        "origin_y": vy,
        "width": vw,
        "height": vh,
        "primary_width": pw,
        "primary_height": ph,
    }


def serialize_key(k):
    """Convert pynput key object into a JSON-serializable dict."""
    if isinstance(k, Key):
        return {"type": "special", "value": k.name}
    elif isinstance(k, KeyCode):
        return {
            "type": "char",
            "char": k.char,
            "vk": k.vk,
        }
    return {"type": "unknown", "value": str(k)}


def deserialize_key(data):
    """Restore pynput key object from serialized dict."""
    k_type = data.get("type")
    if k_type == "special":
        name = data.get("value")
        return getattr(Key, name, None)
    elif k_type == "char":
        vk = data.get("vk")
        char = data.get("char")
        if vk is not None:
            return KeyCode.from_vk(vk)
        elif char is not None:
            return KeyCode.from_char(char)
    return None


def serialize_button(btn):
    """Convert pynput mouse Button into string name."""
    return btn.name if hasattr(btn, "name") else str(btn)


def deserialize_button(name):
    """Restore pynput mouse Button from string name."""
    return getattr(Button, name, Button.left)


# ==================== macOS SONOMA COLOR PALETTE ====================
BG_MAIN = "#0B0C10"          # Deep macOS Obsidian background
CARD_BG = "#13151C"          # Elevated Bento Card surface
CARD_INNER = "#0D0E14"       # Recessed input/pill surface
CARD_BORDER = "#222634"      # Subtle 1px hairline border
TEXT_PRIMARY = "#F3F4F6"     # Crisp white text
TEXT_SECONDARY = "#9CA3AF"   # Muted label text
TEXT_MUTED = "#6B7280"       # Subtle caption text
ACCENT_BLUE = "#3B82F6"      # macOS System Blue
ACCENT_INDIGO = "#6366F1"    # Raycast Indigo
ACCENT_GREEN = "#10B981"     # macOS Emerald Green
ACCENT_RED = "#EF4444"       # macOS Crimson Red
ACCENT_AMBER = "#F59E0B"     # macOS Amber Orange
ACCENT_CYAN = "#0EA5E9"      # Cloud Sky Blue


class ActionRecorderBot:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.screen = get_full_screen_bounds()
        sw = self.screen["width"]
        sh = self.screen["height"]

        self.root.title(f"AutoFlow Studio — Signup & OTP Automation ({sw}×{sh})")
        self.root.geometry("1020x780")
        self.root.minsize(940, 700)
        self.root.configure(fg_color=BG_MAIN)
        apply_macos_dark_window_style(self.root)

        # Fonts (macOS / Modern Windows 11 Typography)
        self.font_title = ctk.CTkFont(family="Segoe UI Variable Display", size=18, weight="bold")
        self.font_subtitle = ctk.CTkFont(family="Segoe UI Variable Text", size=12)
        self.font_card_hdr = ctk.CTkFont(family="Segoe UI Variable Display", size=11, weight="bold")
        self.font_body = ctk.CTkFont(family="Segoe UI Variable Text", size=12, weight="bold")
        self.font_regular = ctk.CTkFont(family="Segoe UI Variable Text", size=12)
        self.font_small = ctk.CTkFont(family="Segoe UI Variable Text", size=11)
        self.font_btn = ctk.CTkFont(family="Segoe UI Variable Text", size=12, weight="bold")
        self.font_mono = ctk.CTkFont(family="Consolas", size=12)
        self.font_kbd = ctk.CTkFont(family="Consolas", size=11, weight="bold")

        # State
        self.is_recording = False
        self.is_paused = False
        self.pause_start_perf = 0.0
        self.is_playing = False
        self.is_busy_injecting = False
        self.stop_playback_flag = False
        self.playback_finished_time = 0.0
        self.bot_deiconified_time = 0.0
        self.events = []
        self.start_time = 0.0
        self.last_move_time = 0.0
        self.move_sample_interval = 0.015  # ~66 FPS smooth mouse tracking

        # Prevent Windows VM / PC from sleeping or turning off virtual display
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
        except Exception:
            pass

        # Signup & OTP State
        self.gmail_fetcher = GmailOTPFetcher(self.base_dir)
        self.current_test_email: Optional[str] = None
        self.email_typed_epoch_ms: int = 0
        self.custom_email_queue = []
        self._typed_buffer = ""
        self.auto_otp_session_id = 0
        self.clicks_since_email = 0
        self.last_click_perf = 0.0
        self.last_move_perf = 0.0

        # Controllers for playback
        self.mouse_ctrl = MouseController()
        self.kb_ctrl = KeyboardController()

        # Listeners
        self.mouse_listener = None
        self.kb_listener = None
        self.hotkey_listener = None
        self.custom_reference_template_b64 = ""

        # Browser-Safe OS-Suppressed Hotkeys
        # F2 = Random @nariwal.shop | F3 = Smart Visual/OCR Click | F4 = mobile.j3pro@gmail.com
        # F6 = Pause/Resume Rec     | F7 = Fetch OTP              | F8 = Record/Stop | F9 = Play | F10 = Stop
        self.control_keys = {Key.f2, Key.f3, Key.f4, Key.f6, Key.f7, Key.f8, Key.f9, Key.f10}

        self._build_ui()
        self._start_global_hotkey_listener()

        self.root.bind("<Map>", self._on_window_restore)

        self.default_file = os.path.join(self.base_dir, "recorded_actions.json")
        if os.path.exists(self.default_file):
            self._load_from_path(self.default_file, silent=True)

        # Silent Gmail OAuth connection on startup if token.json exists
        threading.Thread(target=self._auto_connect_gmail_startup, daemon=True).start()

    def _auto_connect_gmail_startup(self):
        if os.path.exists(self.gmail_fetcher.creds_path):
            self.log(f"✓ Found OAuth credentials ({os.path.basename(self.gmail_fetcher.creds_path)}).")
        if self.gmail_fetcher.try_silent_connect(log_fn=self.log):
            self.root.after(
                0,
                lambda: self.gmail_status_lbl.configure(
                    text=f"● Connected: {self.gmail_fetcher.connected_email}",
                    text_color=ACCENT_GREEN,
                ),
            )
        else:
            self.log(
                "ℹ Click 'Connect Gmail' once to authorize hussainnariwal@gmail.com for automatic OTP fetching."
            )

    def _on_window_restore(self, event=None):
        if event and event.widget == self.root:
            self.bot_deiconified_time = time.perf_counter()

    # ==================== macOS SONOMA MODERN UI BUILDER ====================
    def _build_ui(self):
        sw = self.screen["width"]
        sh = self.screen["height"]

        # -------------------- 1. TOP macOS HEADER BAR --------------------
        header_card = ctk.CTkFrame(
            self.root,
            fg_color=CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=CARD_BORDER,
        )
        header_card.pack(fill="x", padx=18, pady=(14, 10))

        header_top = ctk.CTkFrame(header_card, fg_color="transparent")
        header_top.pack(fill="x", padx=16, pady=(12, 12))

        # macOS Traffic Light Dots
        dots_frame = ctk.CTkFrame(header_top, fg_color="transparent")
        dots_frame.pack(side="left", padx=(0, 14))

        for color in ("#FF5F56", "#FFBD2E", "#27C93F"):
            dot = ctk.CTkLabel(
                dots_frame,
                text="●",
                font=ctk.CTkFont(size=16),
                text_color=color,
                width=16,
            )
            dot.pack(side="left", padx=2)

        # App Title & Subtitle
        title_stack = ctk.CTkFrame(header_top, fg_color="transparent")
        title_stack.pack(side="left")

        title_row = ctk.CTkFrame(title_stack, fg_color="transparent")
        title_row.pack(anchor="w")

        ctk.CTkLabel(
            title_row,
            text="AutoFlow Studio",
            font=self.font_title,
            text_color=TEXT_PRIMARY,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(
            title_row,
            text=f"{sw} × {sh} Dynamic Screen",
            font=self.font_small,
            text_color="#93C5FD",
            fg_color="#1E293B",
            corner_radius=6,
            padx=8,
            pady=2,
        ).pack(side="left")

        ctk.CTkLabel(
            title_stack,
            text="Full-Screen Browser Recorder · Multi-Email Forwarding (@nariwal.shop & mobile.j3pro) · Instant Gmail OTP",
            font=self.font_small,
            text_color=TEXT_SECONDARY,
        ).pack(anchor="w", pady=(2, 0))

        # Right Status Pills in Header
        status_Group = ctk.CTkFrame(header_top, fg_color="transparent")
        status_Group.pack(side="right")

        self.status_badge = ctk.CTkLabel(
            status_Group,
            text=f"● READY ({sw}×{sh})",
            font=self.font_body,
            text_color="#38BDF8",
            fg_color=CARD_INNER,
            corner_radius=8,
            padx=12,
            pady=6,
        )
        self.status_badge.pack(side="right", padx=(8, 0))

        self.stats_lbl = ctk.CTkLabel(
            status_Group,
            text="0 Actions · 0.0s",
            font=self.font_body,
            text_color=TEXT_PRIMARY,
            fg_color=CARD_INNER,
            corner_radius=8,
            padx=12,
            pady=6,
        )
        self.stats_lbl.pack(side="right", padx=(8, 0))

        self.current_email_lbl = ctk.CTkLabel(
            status_Group,
            text="Email: None",
            font=self.font_small,
            text_color="#A7F3D0",
            fg_color=CARD_INNER,
            corner_radius=8,
            padx=12,
            pady=6,
        )
        self.current_email_lbl.pack(side="right")

        # -------------------- 2. ACTION DOCK (TOOLBAR CARD) --------------------
        dock_card = ctk.CTkFrame(
            self.root,
            fg_color=CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=CARD_BORDER,
        )
        dock_card.pack(fill="x", padx=18, pady=(0, 10))

        dock_inner = ctk.CTkFrame(dock_card, fg_color="transparent")
        dock_inner.pack(fill="x", padx=14, pady=10)

        self.record_btn = ctk.CTkButton(
            dock_inner,
            text="● Start Rec (F8)",
            font=self.font_btn,
            fg_color="#E11D48",
            hover_color="#BE123C",
            text_color="white",
            corner_radius=9,
            height=36,
            width=142,
            command=lambda: self.toggle_recording(from_gui_button=True),
        )
        self.record_btn.pack(side="left", padx=(0, 8))

        self.pause_rec_btn = ctk.CTkButton(
            dock_inner,
            text="❚❚ Pause Rec (F6)",
            font=self.font_btn,
            fg_color="#272732",
            hover_color="#B45309",
            text_color="#9CA3AF",
            corner_radius=9,
            height=36,
            width=142,
            state="disabled",
            command=lambda: self.toggle_pause_recording(from_gui_button=True),
        )
        self.pause_rec_btn.pack(side="left", padx=(0, 8))

        self.play_btn = ctk.CTkButton(
            dock_inner,
            text="▶ Play Loop (F9)",
            font=self.font_btn,
            fg_color="#10B981",
            hover_color="#059669",
            text_color="white",
            corner_radius=9,
            height=36,
            width=142,
            command=lambda: self.toggle_playback(from_gui_button=True),
        )
        self.play_btn.pack(side="left", padx=(0, 12))

        # Divider
        ctk.CTkFrame(dock_inner, width=1, height=24, fg_color=CARD_BORDER).pack(
            side="left", padx=(0, 12)
        )

        sec_btn_cfg = {
            "font": self.font_btn,
            "fg_color": "#1E202B",
            "hover_color": "#2A2D3D",
            "border_width": 1,
            "border_color": "#2E3244",
            "text_color": TEXT_PRIMARY,
            "corner_radius": 9,
            "height": 36,
            "width": 84,
        }

        self.clear_btn = ctk.CTkButton(
            dock_inner, text="Clear", command=self.clear_actions, **sec_btn_cfg
        )
        self.clear_btn.pack(side="left", padx=(0, 6))

        self.save_btn = ctk.CTkButton(
            dock_inner, text="Save", command=self.save_recording, **sec_btn_cfg
        )
        self.save_btn.pack(side="left", padx=(0, 6))

        self.load_btn = ctk.CTkButton(
            dock_inner, text="Load", command=self.load_recording, **sec_btn_cfg
        )
        self.load_btn.pack(side="left")

        self.vm_detach_btn = ctk.CTkButton(
            dock_inner,
            text="☁ VM Keep-Alive (Close RDP)",
            font=self.font_btn,
            fg_color="#0284C7",
            hover_color="#0369A1",
            text_color="white",
            corner_radius=9,
            height=36,
            width=205,
            command=self.detach_rdp_keep_vm_alive,
        )
        self.vm_detach_btn.pack(side="right")

        # -------------------- 3. TWO-COLUMN BENTO SETTINGS GRID --------------------
        bento_row = ctk.CTkFrame(self.root, fg_color="transparent")
        bento_row.pack(fill="x", padx=18, pady=(0, 10))
        bento_row.grid_columnconfigure(0, weight=3)
        bento_row.grid_columnconfigure(1, weight=2)

        # === LEFT BENTO CARD: SIGNUP EMAILS & GMAIL OTP ===
        otp_card = ctk.CTkFrame(
            bento_row,
            fg_color=CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=CARD_BORDER,
        )
        otp_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        ctk.CTkLabel(
            otp_card,
            text="SIGNUP EMAIL ROUTING & CENTRAL GMAIL OTP",
            font=self.font_card_hdr,
            text_color="#60A5FA",
        ).pack(anchor="w", padx=16, pady=(12, 8))

        # Inputs Row
        inputs_row = ctk.CTkFrame(otp_card, fg_color="transparent")
        inputs_row.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(
            inputs_row, text="Domain [F2]", font=self.font_small, text_color=TEXT_SECONDARY
        ).pack(side="left", padx=(0, 6))

        self.domain_var = tk.StringVar(value="@nariwal.shop")
        self.domain_entry = ctk.CTkEntry(
            inputs_row,
            textvariable=self.domain_var,
            font=self.font_body,
            fg_color=CARD_INNER,
            border_color=CARD_BORDER,
            text_color="#38BDF8",
            width=125,
            height=32,
            corner_radius=8,
        )
        self.domain_entry.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(
            inputs_row, text="2nd Email [F4]", font=self.font_small, text_color=TEXT_SECONDARY
        ).pack(side="left", padx=(0, 6))

        self.secondary_email_var = tk.StringVar(value="mobile.j3pro@gmail.com")
        self.sec_entry = ctk.CTkEntry(
            inputs_row,
            textvariable=self.secondary_email_var,
            font=self.font_body,
            fg_color=CARD_INNER,
            border_color=CARD_BORDER,
            text_color="#F472B6",
            width=185,
            height=32,
            corner_radius=8,
        )
        self.sec_entry.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            inputs_row,
            text="Email Queue",
            font=self.font_small,
            fg_color="#1E202B",
            hover_color="#2A2D3D",
            border_width=1,
            border_color="#2E3244",
            text_color=TEXT_PRIMARY,
            width=92,
            height=32,
            corner_radius=8,
            command=self.open_email_list_dialog,
        ).pack(side="left")

        # Switches Row
        switches_row = ctk.CTkFrame(otp_card, fg_color="transparent")
        switches_row.pack(fill="x", padx=16, pady=(2, 10))

        ctk.CTkLabel(
            switches_row, text="OTP Timeout (s):", font=self.font_small, text_color=TEXT_SECONDARY
        ).pack(side="left", padx=(0, 6))

        self.otp_timeout_var = tk.StringVar(value="90")
        ctk.CTkEntry(
            switches_row,
            textvariable=self.otp_timeout_var,
            font=self.font_body,
            fg_color=CARD_INNER,
            border_color=CARD_BORDER,
            width=52,
            height=28,
            corner_radius=7,
            justify="center",
        ).pack(side="left", padx=(0, 16))

        self.auto_otp_after_email_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            switches_row,
            text="Auto-OTP after F2/F4",
            variable=self.auto_otp_after_email_var,
            font=self.font_small,
            text_color=TEXT_PRIMARY,
            progress_color=ACCENT_GREEN,
            button_color="#F8FAFC",
            height=22,
        ).pack(side="left", padx=(0, 16))

        self.press_enter_after_otp_var = tk.BooleanVar(value=False)
        ctk.CTkSwitch(
            switches_row,
            text="Press Enter after OTP",
            variable=self.press_enter_after_otp_var,
            font=self.font_small,
            text_color=TEXT_SECONDARY,
            progress_color=ACCENT_BLUE,
            button_color="#F8FAFC",
            height=22,
        ).pack(side="left")

        # OAuth Status Bar inside Left Bento Card
        oauth_bar = ctk.CTkFrame(
            otp_card,
            fg_color=CARD_INNER,
            corner_radius=10,
            border_width=1,
            border_color="#1C2030",
        )
        oauth_bar.pack(fill="x", padx=14, pady=(0, 12))

        self.gmail_status_lbl = ctk.CTkLabel(
            oauth_bar,
            text="● Gmail OAuth: Ready to connect",
            font=self.font_small,
            text_color=ACCENT_AMBER,
        )
        self.gmail_status_lbl.pack(side="left", padx=12, pady=8)

        ctk.CTkButton(
            oauth_bar,
            text="Test OTP Now",
            font=self.font_small,
            fg_color=ACCENT_INDIGO,
            hover_color="#4F46E5",
            text_color="white",
            height=28,
            width=104,
            corner_radius=7,
            command=self.test_otp_fetch_clicked,
        ).pack(side="right", padx=(4, 8), pady=6)

        ctk.CTkButton(
            oauth_bar,
            text="JSON File",
            font=self.font_small,
            fg_color="#1E202B",
            hover_color="#2A2D3D",
            text_color=TEXT_SECONDARY,
            height=28,
            width=76,
            corner_radius=7,
            command=self.select_credentials_file,
        ).pack(side="right", padx=4, pady=6)

        ctk.CTkButton(
            oauth_bar,
            text="Connect Gmail",
            font=self.font_small,
            fg_color="#0284C7",
            hover_color="#0369A1",
            text_color="white",
            height=28,
            width=104,
            corner_radius=7,
            command=self.connect_gmail_clicked,
        ).pack(side="right", padx=4, pady=6)

        # === RIGHT BENTO CARD: PLAYBACK & SMART VISUAL/OCR ENGINE ===
        play_card = ctk.CTkFrame(
            bento_row,
            fg_color=CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=CARD_BORDER,
        )
        play_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ctk.CTkLabel(
            play_card,
            text="PLAYBACK & SMART VISUAL / OCR TARGETING",
            font=self.font_card_hdr,
            text_color="#34D399",
        ).pack(anchor="w", padx=16, pady=(12, 8))

        speed_row = ctk.CTkFrame(play_card, fg_color="transparent")
        speed_row.pack(fill="x", padx=16, pady=(0, 6))

        ctk.CTkLabel(
            speed_row, text="Speed:", font=self.font_small, text_color=TEXT_SECONDARY
        ).pack(side="left", padx=(0, 6))

        self.speed_options = {
            "Exact Recording Time (1.0x Normal)": 1.0,
            "Slow Motion (0.5x Half Speed)": 0.5,
            "Slightly Slower (0.75x)": 0.75,
            "Fast (1.5x)": 1.5,
            "Double Speed (2.0x)": 2.0,
        }
        self.speed_label_var = tk.StringVar(value="Exact Recording Time (1.0x Normal)")
        self.speed_menu = ctk.CTkOptionMenu(
            speed_row,
            variable=self.speed_label_var,
            values=list(self.speed_options.keys()),
            font=self.font_small,
            fg_color=CARD_INNER,
            button_color="#252836",
            button_hover_color="#323648",
            dropdown_fg_color=CARD_BG,
            text_color=TEXT_PRIMARY,
            height=30,
            width=190,
            corner_radius=8,
        )
        self.speed_menu.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkLabel(
            speed_row,
            text="Loops:",
            font=self.font_small,
            text_color=TEXT_SECONDARY,
        ).pack(side="left", padx=(0, 4))

        self.loop_var = tk.StringVar(value="5")
        ctk.CTkEntry(
            speed_row,
            textvariable=self.loop_var,
            font=self.font_body,
            fg_color=CARD_INNER,
            border_color=CARD_BORDER,
            text_color="#38BDF8",
            width=50,
            height=30,
            corner_radius=8,
            justify="center",
        ).pack(side="left")

        # Smart Target Text / Reference Image Row [F3]
        target_row = ctk.CTkFrame(play_card, fg_color="transparent")
        target_row.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(
            target_row,
            text="Target [F3]:",
            font=self.font_small,
            text_color=TEXT_SECONDARY,
        ).pack(side="left", padx=(0, 6))

        self.smart_target_text_var = tk.StringVar(value="")
        self.smart_target_entry = ctk.CTkEntry(
            target_row,
            textvariable=self.smart_target_text_var,
            placeholder_text="Auto under cursor or type e.g. @nariwal.shop",
            font=self.font_small,
            fg_color=CARD_INNER,
            border_color=CARD_BORDER,
            text_color="#FBBF24",
            height=30,
            corner_radius=8,
        )
        self.smart_target_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.ref_img_btn = ctk.CTkButton(
            target_row,
            text="Ref Image",
            font=self.font_small,
            fg_color="#1E202B",
            hover_color="#2A2D3D",
            border_width=1,
            border_color="#2E3244",
            text_color=TEXT_PRIMARY,
            width=80,
            height=30,
            corner_radius=8,
            command=self.select_visual_reference_image,
        )
        self.ref_img_btn.pack(side="left")

        toggles_col = ctk.CTkFrame(play_card, fg_color="transparent")
        toggles_col.pack(fill="x", padx=16, pady=(0, 10))

        self.smart_target_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            toggles_col,
            text="Smart Visual & OCR Lock (Click Shifted Elements)",
            variable=self.smart_target_var,
            font=self.font_small,
            text_color="#FBBF24",
            progress_color="#8B5CF6",
            button_color="#F8FAFC",
            height=20,
        ).pack(anchor="w", pady=(0, 5))

        toggles_sub = ctk.CTkFrame(toggles_col, fg_color="transparent")
        toggles_sub.pack(fill="x")

        self.auto_min_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            toggles_sub,
            text="Auto-Minimize Bot",
            variable=self.auto_min_var,
            font=self.font_small,
            text_color=TEXT_PRIMARY,
            progress_color=ACCENT_AMBER,
            button_color="#F8FAFC",
            height=20,
        ).pack(side="left", padx=(0, 14))

        self.self_heal_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            toggles_sub,
            text="Auto-Fix Mouse Bump",
            variable=self.self_heal_var,
            font=self.font_small,
            text_color=TEXT_PRIMARY,
            progress_color=ACCENT_GREEN,
            button_color="#F8FAFC",
            height=20,
        ).pack(side="left")

        # -------------------- 4. macOS KEYCAP SHORTCUTS BAR --------------------
        kbd_bar = ctk.CTkFrame(
            self.root,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=CARD_BORDER,
        )
        kbd_bar.pack(fill="x", padx=18, pady=(0, 10))

        kbd_inner = ctk.CTkFrame(kbd_bar, fg_color="transparent")
        kbd_inner.pack(fill="x", padx=10, pady=8)

        shortcuts = [
            ("F2", "@nariwal.shop", "#38BDF8"),
            ("F3", "Smart Target Click", "#FBBF24"),
            ("F4", "mobile.j3pro", "#F472B6"),
            ("F6", "Pause / Resume", "#FB923C"),
            ("F7", "Fetch OTP", "#A78BFA"),
            ("F8", "Start / Stop Rec", "#F87171"),
            ("F9", "Play Loops", "#34D399"),
            ("F10", "Stop", "#FB7185"),
        ]

        for key_name, desc, kcolor in shortcuts:
            item = ctk.CTkFrame(kbd_inner, fg_color="transparent")
            item.pack(side="left", expand=True)

            ctk.CTkLabel(
                item,
                text=key_name,
                font=self.font_kbd,
                text_color=kcolor,
                fg_color=CARD_INNER,
                corner_radius=6,
                padx=7,
                pady=2,
            ).pack(side="left", padx=(0, 5))

            ctk.CTkLabel(
                item,
                text=desc,
                font=self.font_small,
                text_color=TEXT_SECONDARY,
            ).pack(side="left")

        # -------------------- 5. macOS TERMINAL CONSOLE LOG --------------------
        console_card = ctk.CTkFrame(
            self.root,
            fg_color=CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=CARD_BORDER,
        )
        console_card.pack(fill="both", expand=True, padx=18, pady=(0, 16))

        console_hdr = ctk.CTkFrame(console_card, fg_color="transparent")
        console_hdr.pack(fill="x", padx=16, pady=(10, 6))

        ctk.CTkLabel(
            console_hdr,
            text="LIVE TELEMETRY & GMAIL OTP CONSOLE",
            font=self.font_card_hdr,
            text_color=TEXT_SECONDARY,
        ).pack(side="left")

        ctk.CTkButton(
            console_hdr,
            text="Clear Console",
            font=ctk.CTkFont(family="Segoe UI Variable Text", size=11),
            fg_color="#1E202B",
            hover_color="#2A2D3D",
            text_color=TEXT_SECONDARY,
            height=24,
            width=90,
            corner_radius=6,
            command=lambda: self.log_box.delete("1.0", "end"),
        ).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            console_card,
            fg_color="#08090D",
            text_color="#E2E8F0",
            font=self.font_mono,
            corner_radius=10,
            border_width=1,
            border_color="#1A1D28",
            wrap="word",
        )
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.log(
            "✦ AutoFlow Studio Ready — Browser-Safe OS-Suppressed Shortcuts Active:\n"
            "  • [F2] Type random @nariwal.shop email  |  [F4] Type mobile.j3pro@gmail.com  |  [F6] Pause/Resume Recording\n"
            "  • Auto-OTP Watcher automatically fetches & types the 6-digit OTP from hussainnariwal@gmail.com in <0.8s!"
        )

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")

        def _append():
            self.log_box.insert("end", f"[{timestamp}]  {message}\n")
            self.log_box.see("end")

        self.root.after(0, _append)

    def _update_stats(self):
        count = len(self.events)
        duration = self.events[-1]["time"] if count > 0 else 0.0
        self.root.after(
            0,
            lambda: self.stats_lbl.configure(
                text=f"{count} Actions · {duration:.1f}s"
            ),
        )

    def _set_status(self, text: str, fg: str, bg: str = CARD_INNER):
        self.root.after(
            0, lambda: self.status_badge.configure(text=text, text_color=fg, fg_color=bg)
        )

    # -------------------- GMAIL & EMAIL CONFIGURATION --------------------
    def select_credentials_file(self):
        path = filedialog.askopenfilename(
            title="Select Google OAuth credentials.json",
            filetypes=[("JSON Files", "*.json")],
        )
        if path:
            self.gmail_fetcher.set_credentials_file(path)
            self.log(f"✓ Selected credentials file: {path}")
            self.connect_gmail_clicked()

    def connect_gmail_clicked(self):
        def _worker():
            self.log("⟳ Starting Gmail OAuth authentication...")
            ok = self.gmail_fetcher.authenticate(log_fn=self.log, force_new=False)
            if not ok:
                ok = self.gmail_fetcher.authenticate(log_fn=self.log, force_new=True)
            if ok:
                self.root.after(
                    0,
                    lambda: self.gmail_status_lbl.configure(
                        text=f"● Connected: {self.gmail_fetcher.connected_email}",
                        text_color=ACCENT_GREEN,
                    ),
                )
            else:
                self.root.after(
                    0,
                    lambda: self.gmail_status_lbl.configure(
                        text="● Connection Failed (Check Console)",
                        text_color=ACCENT_RED,
                    ),
                )

        threading.Thread(target=_worker, daemon=True).start()

    def test_otp_fetch_clicked(self):
        def _worker():
            self.log("⟳ Testing Gmail OTP fetch (checking recent verification emails in hussainnariwal@gmail.com)...")
            otp = self.gmail_fetcher.wait_for_otp(
                target_email=None,
                timeout_sec=10,
                poll_interval=1.0,
                trash_after_read=False,
                log_fn=self.log,
            )
            if otp:
                self.log(f"✓ Test Passed! Extracted OTP code: [{otp}]")
            else:
                self.log("ℹ No recent unconsumed OTP email found in the last 3 minutes (Connection is working!).")

        threading.Thread(target=_worker, daemon=True).start()

    def open_email_list_dialog(self):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Custom Email Queue")
        dlg.geometry("480x400")
        dlg.configure(fg_color=BG_MAIN)
        dlg.attributes("-topmost", True)

        ctk.CTkLabel(
            dlg,
            text="Paste specific emails (one per line) to test one-by-one.\nLeave empty to auto-generate random @nariwal.shop emails.",
            font=self.font_regular,
            text_color=TEXT_SECONDARY,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(16, 10))

        txt = ctk.CTkTextbox(
            dlg,
            fg_color=CARD_INNER,
            text_color="#38BDF8",
            font=self.font_mono,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        txt.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        if self.custom_email_queue:
            txt.insert("end", "\n".join(self.custom_email_queue))

        def _save_list():
            raw = txt.get("1.0", "end").strip()
            lines = [line.strip() for line in raw.splitlines() if line.strip() and "@" in line]
            self.custom_email_queue = lines
            if lines:
                self.log(f"✓ Loaded {len(lines)} custom email(s) into queue.")
            else:
                self.log("ℹ Custom email list cleared. Using random domain email generator.")
            dlg.destroy()

        ctk.CTkButton(
            dlg,
            text="Save Email Queue",
            font=self.font_btn,
            fg_color=ACCENT_GREEN,
            hover_color="#059669",
            corner_radius=9,
            height=36,
            command=_save_list,
        ).pack(pady=(0, 16))

    def _get_next_test_email(self) -> str:
        """Return next email from custom queue or generate a fresh random email on user's domain."""
        if self.custom_email_queue:
            email = self.custom_email_queue.pop(0)
        else:
            domain = self.domain_var.get().strip() or "nariwal.shop"
            email = generate_random_domain_email(domain=domain)
        self.current_test_email = email
        self.email_typed_epoch_ms = int(time.time() * 1000)
        self.root.after(
            0, lambda: self.current_email_lbl.configure(text=f"Email: {email}")
        )
        return email

    def _type_string_reliably(self, text: str, char_delay: float = 0.03):
        """Type a string character-by-character into the focused browser input field."""
        self.is_busy_injecting = True
        try:
            for ch in text:
                if self.stop_playback_flag:
                    break
                self.kb_ctrl.type(ch)
                time.sleep(char_delay)
        finally:
            time.sleep(0.05)
            self.is_busy_injecting = False

    def _log_signup_result_csv(self, email: str, otp: Optional[str], status: str):
        csv_path = os.path.join(self.base_dir, "signup_test_results.csv")
        file_exists = os.path.exists(csv_path)
        try:
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["Timestamp", "Test_Email", "OTP_Code", "Status"])
                writer.writerow([
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    email,
                    otp or "",
                    status,
                ])
        except Exception:
            pass

    # -------------------- DYNAMIC SCREEN & MOUSE LOCK --------------------
    def _clamp_to_full_screen(self, x: int, y: int):
        self.screen = get_full_screen_bounds()
        ox = self.screen["origin_x"]
        oy = self.screen["origin_y"]
        max_x = ox + self.screen["width"] - 1
        max_y = oy + self.screen["height"] - 1
        cx = max(ox, min(int(x), max_x))
        cy = max(oy, min(int(y), max_y))
        return cx, cy

    def _to_relative_coords(self, x: int, y: int):
        ox = self.screen["origin_x"]
        oy = self.screen["origin_y"]
        w = max(1, self.screen["width"])
        h = max(1, self.screen["height"])
        rx = round((x - ox) / w, 6)
        ry = round((y - oy) / h, 6)
        return rx, ry

    def _resolve_event_coords(self, event: dict):
        self.screen = get_full_screen_bounds()
        ox = self.screen["origin_x"]
        oy = self.screen["origin_y"]
        w = max(1, self.screen["width"])
        h = max(1, self.screen["height"])

        if "rx" in event and "ry" in event:
            tx = int(round(ox + (float(event["rx"]) * w)))
            ty = int(round(oy + (float(event["ry"]) * h)))
            return self._clamp_to_full_screen(tx, ty)
        return self._clamp_to_full_screen(event.get("x", 0), event.get("y", 0))

    def _force_move_and_verify(self, target_x: int, target_y: int, max_retries: int = 4) -> bool:
        tx, ty = self._clamp_to_full_screen(target_x, target_y)
        pw = max(1, self.screen["primary_width"])
        ph = max(1, self.screen["primary_height"])
        abs_x = int((tx * 65535) / pw)
        abs_y = int((ty * 65535) / ph)

        corrected = False
        for _ in range(max_retries):
            try:
                ctypes.windll.user32.SetCursorPos(tx, ty)
                ctypes.windll.user32.mouse_event(
                    MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, abs_x, abs_y, 0, 0
                )
            except Exception:
                pass
            self.mouse_ctrl.position = (tx, ty)

            cur_x, cur_y = self.mouse_ctrl.position
            if abs(cur_x - tx) <= 2 and abs(cur_y - ty) <= 2:
                break
            corrected = True
            time.sleep(0.005)

        try:
            ctypes.windll.user32.SetCursorPos(tx, ty)
        except Exception:
            pass
        self.mouse_ctrl.position = (tx, ty)
        return corrected

    # -------------------- GLOBAL HOTKEY LISTENER (OS-LEVEL BROWSER SUPPRESSION) --------------------
    def _start_global_hotkey_listener(self):
        bot_vk_actions = {
            0x71: self.hotkey_insert_dynamic_email,                            # F2
            0x72: self.hotkey_smart_target_click,                              # F3 -> Smart Visual/OCR Target Click
            0x73: self.hotkey_insert_secondary_email,                          # F4
            0x75: lambda: self.toggle_pause_recording(from_gui_button=False),  # F6
            0x76: self.hotkey_fetch_and_type_otp,                              # F7
            0x77: lambda: self.toggle_recording(from_gui_button=False),        # F8
            0x78: lambda: self.toggle_playback(from_gui_button=False),         # F9
            0x79: self.emergency_stop,                                         # F10
        }
        WM_KEYDOWN = 0x0100
        WM_SYSKEYDOWN = 0x0104

        def win32_event_filter(msg, data):
            if data.vkCode in bot_vk_actions:
                if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self.root.after(0, bot_vk_actions[data.vkCode])
                self.hotkey_listener.suppress_event()
                return False
            return True

        self.hotkey_listener = keyboard.Listener(win32_event_filter=win32_event_filter)
        self.hotkey_listener.daemon = True
        self.hotkey_listener.start()

    def emergency_stop(self):
        self.auto_otp_session_id += 1
        if self.is_recording:
            self.stop_recording(from_gui_button=False)
        if self.is_playing:
            self.stop_playback_flag = True
        self.log("■ Emergency Stop (F10) triggered!")

    # -------------------- SMART VISUAL & OCR TARGET CLICK [F3] --------------------
    def select_visual_reference_image(self):
        """Allow user to pick a cropped reference image (PNG/JPG) to match on screen."""
        path = filedialog.askopenfilename(
            title="Select Visual Reference Crop (PNG/JPG)",
            filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.bmp")],
        )
        if not path:
            return
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            self.custom_reference_template_b64 = pil_to_base64(img)
            self.ref_img_btn.configure(text="✓ Img Set", fg_color="#065F46", text_color="#A7F3D0")
            self.log(f"🎯 Loaded Visual Reference Image: {os.path.basename(path)} ({img.size[0]}×{img.size[1]}px)")
        except Exception as e:
            self.log(f"⚠ Failed to load reference image: {e}")

    def hotkey_smart_target_click(self):
        """
        Triggered when user presses [F3].
        - If 'Target [F3]' box has text (e.g. '@nariwal.shop' or 'Add new contact info') or a Ref Image,
          it immediately searches the screen for that element, moves the mouse there, clicks it,
          and records a 'smart_target_click' step!
        - If 'Target [F3]' box is empty, it inspects what is under the cursor right now (OCR + Visual Patch),
          locks onto that text/image as the target, clicks it, and records a 'smart_target_click' step!
        """
        if self.is_playing or self.is_busy_injecting:
            return

        def _worker():
            pause_start = time.perf_counter()
            self.is_busy_injecting = True
            try:
                self.screen = get_full_screen_bounds()
                cx, cy = self.mouse_ctrl.position
                rx, ry = self._to_relative_coords(cx, cy)

                custom_txt = self.smart_target_text_var.get().strip()
                custom_img_b64 = self.custom_reference_template_b64

                anchor_text = custom_txt
                template_b64 = custom_img_b64
                click_x, click_y = int(cx), int(cy)

                if custom_txt or custom_img_b64:
                    # Search the screen right now for the user's specified text or reference image
                    found = smart_locate_target_on_screen(
                        self.screen,
                        int(cx),
                        int(cy),
                        anchor_text=custom_txt,
                        template_b64=custom_img_b64,
                        current_test_email=self.current_test_email,
                        domain_hint=self.domain_var.get(),
                    )
                    if found:
                        click_x, click_y, reason = found
                        self.log(f"🎯 [F3] Found target [{reason}] at ({click_x}, {click_y}) & clicking!")
                    else:
                        self.log(
                            f"🎯 [F3] Recorded target rule ['{custom_txt or 'Visual Image'}'] & clicking at current cursor ({click_x}, {click_y})"
                        )
                else:
                    # Auto-detect text & visual template right under the cursor!
                    screen_img = grab_full_screen_pil(self.screen)
                    info = extract_anchor_info_at_cursor(
                        screen_img,
                        int(cx),
                        int(cy),
                        domain_hint=self.domain_var.get(),
                        secondary_email_hint=self.secondary_email_var.get(),
                        custom_target_hint=custom_txt,
                        allow_any_text=True,
                        origin_x=self.screen["origin_x"],
                        origin_y=self.screen["origin_y"],
                    )
                    anchor_text = info.get("anchor_text", "")
                    template_b64 = info.get("template_b64", "")
                    raw_txt = info.get("raw_text", "")
                    self.log(
                        f"🎯 [F3] Locked Smart Target under cursor: Text=['{anchor_text or raw_txt or 'Visual Patch'}'] at ({click_x}, {click_y})"
                    )

                if self.is_recording:
                    t = self._elapsed()
                    crx, cry = self._to_relative_coords(click_x, click_y)
                    self.events.append({
                        "type": "smart_target_click",
                        "x": click_x,
                        "y": click_y,
                        "rx": crx,
                        "ry": cry,
                        "anchor_text": anchor_text,
                        "template_b64": template_b64,
                        "button": "left",
                        "time": t,
                    })

                self._force_move_and_verify(click_x, click_y, max_retries=3)
                time.sleep(0.02)
                self.mouse_ctrl.press(Button.left)
                time.sleep(0.04)
                self.mouse_ctrl.release(Button.left)
                self.clicks_since_email += 1
                self.last_click_perf = time.perf_counter()
            finally:
                self.is_busy_injecting = False
                if self.is_recording:
                    self.start_time += (time.perf_counter() - pause_start)

        threading.Thread(target=_worker, daemon=True).start()

    # -------------------- F2, F4 & F7 + AUTO-OTP SMART SIGNUP ACTIONS --------------------
    def _start_auto_otp_watcher_after_email(self, target_email: str, min_ts_ms: int):
        if not self.auto_otp_after_email_var.get():
            return

        self.auto_otp_session_id += 1
        session_id = self.auto_otp_session_id
        self.clicks_since_email = 0
        email_done_perf = time.perf_counter()

        def _auto_watcher():
            try:
                timeout_s = int(self.otp_timeout_var.get())
            except ValueError:
                timeout_s = 90

            self.log(
                f"⚡ Auto-OTP Watcher active for [{target_email}] — click Continue & click the OTP input box..."
            )

            wait_click_start = time.perf_counter()
            while time.perf_counter() - wait_click_start < timeout_s:
                if self.auto_otp_session_id != session_id or self.is_playing:
                    return
                if self.clicks_since_email >= 1 or (time.perf_counter() - email_done_perf) > 2.5:
                    break
                time.sleep(0.1)

            if self.auto_otp_session_id != session_id or self.is_playing:
                return

            otp = self.gmail_fetcher.wait_for_otp(
                target_email=target_email,
                min_epoch_ms=min_ts_ms,
                timeout_sec=timeout_s,
                poll_interval=1.0,
                trash_after_read=False,
                log_fn=self.log,
                stop_check_fn=lambda: (self.auto_otp_session_id != session_id or self.is_playing),
            )

            if not otp or self.auto_otp_session_id != session_id or self.is_playing:
                return

            self.log(f"✓ OTP [{otp}] ready! Waiting for cursor inside OTP input box to auto-type...")
            focus_wait_start = time.perf_counter()
            while time.perf_counter() - focus_wait_start < 30.0:
                if self.auto_otp_session_id != session_id or self.is_playing:
                    return
                now_p = time.perf_counter()
                since_click = now_p - self.last_click_perf
                since_move = now_p - self.last_move_perf
                if self.clicks_since_email >= 2 and since_click >= 0.55 and since_move >= 0.35:
                    break
                if self.clicks_since_email >= 1 and since_click >= 3.2 and since_move >= 1.0:
                    break
                time.sleep(0.1)

            if self.auto_otp_session_id != session_id or self.is_playing or self.is_busy_injecting:
                return

            self.auto_otp_session_id += 1

            pause_start = time.perf_counter()
            self.is_busy_injecting = True
            try:
                if self.is_recording:
                    t = self._elapsed()
                    cx, cy = self.mouse_ctrl.position
                    rx, ry = self._to_relative_coords(cx, cy)
                    self.events.append({
                        "type": "fetch_and_type_otp",
                        "x": int(cx),
                        "y": int(cy),
                        "rx": rx,
                        "ry": ry,
                        "timeout": timeout_s,
                        "press_enter": bool(self.press_enter_after_otp_var.get()),
                        "time": t,
                    })
                    self.log(f"✦ [{t:.2f}s] Auto-Recorded [Fetch & Type OTP Step] at ({int(cx)}, {int(cy)})")

                self.log(f"⌨ Auto-Typing fetched OTP [{otp}] for [{target_email}]...")
                self._type_string_reliably(otp, char_delay=0.05)
                if self.press_enter_after_otp_var.get():
                    time.sleep(0.1)
                    self.kb_ctrl.press(Key.enter)
                    self.kb_ctrl.release(Key.enter)
                self._log_signup_result_csv(target_email, otp, "AUTO_OTP_TYPED")
            finally:
                self.is_busy_injecting = False
                if self.is_recording:
                    self.start_time += (time.perf_counter() - pause_start)

        threading.Thread(target=_auto_watcher, daemon=True).start()

    def hotkey_insert_secondary_email(self):
        if self.is_playing or self.is_busy_injecting:
            return

        def _worker():
            self.auto_otp_session_id += 1
            self.gmail_fetcher.snapshot_existing_messages()

            sec_email = self.secondary_email_var.get().strip() or "mobile.j3pro@gmail.com"
            self.current_test_email = sec_email
            self.email_typed_epoch_ms = int(time.time() * 1000)
            self.root.after(
                0, lambda: self.current_email_lbl.configure(text=f"Email: {sec_email}")
            )

            if self.is_recording:
                t = self._elapsed()
                cx, cy = self.mouse_ctrl.position
                rx, ry = self._to_relative_coords(cx, cy)
                self.events.append({
                    "type": "insert_secondary_email",
                    "x": int(cx),
                    "y": int(cy),
                    "rx": rx,
                    "ry": ry,
                    "email": sec_email,
                    "time": t,
                })
                self.log(f"✦ [{t:.2f}s] Recorded [F4 Secondary Email] & typing: {sec_email}")
            else:
                self.log(f"✦ [F4] Typing secondary forwarded email: {sec_email}")

            pause_start = time.perf_counter()
            self._type_string_reliably(sec_email)
            if self.is_recording:
                self.start_time += (time.perf_counter() - pause_start)

            self._start_auto_otp_watcher_after_email(sec_email, self.email_typed_epoch_ms)

        threading.Thread(target=_worker, daemon=True).start()

    def hotkey_insert_dynamic_email(self):
        if self.is_playing or self.is_busy_injecting:
            return

        def _worker():
            self.auto_otp_session_id += 1
            self.gmail_fetcher.snapshot_existing_messages()

            email = self._get_next_test_email()
            if self.is_recording:
                t = self._elapsed()
                cx, cy = self.mouse_ctrl.position
                rx, ry = self._to_relative_coords(cx, cy)
                self.events.append({
                    "type": "insert_dynamic_email",
                    "x": int(cx),
                    "y": int(cy),
                    "rx": rx,
                    "ry": ry,
                    "domain": self.domain_var.get().strip(),
                    "time": t,
                })
                self.log(f"✦ [{t:.2f}s] Recorded [F2 Domain Email] & typing: {email}")
            else:
                self.log(f"✦ [F2] Typing generated domain email: {email}")

            pause_start = time.perf_counter()
            self._type_string_reliably(email)
            if self.is_recording:
                self.start_time += (time.perf_counter() - pause_start)

            self._start_auto_otp_watcher_after_email(email, self.email_typed_epoch_ms)

        threading.Thread(target=_worker, daemon=True).start()

    def hotkey_fetch_and_type_otp(self):
        if self.is_playing or self.is_busy_injecting:
            return

        self.auto_otp_session_id += 1

        def _worker():
            try:
                timeout_s = int(self.otp_timeout_var.get())
            except ValueError:
                timeout_s = 90

            if self.is_recording:
                t = self._elapsed()
                cx, cy = self.mouse_ctrl.position
                rx, ry = self._to_relative_coords(cx, cy)
                self.events.append({
                    "type": "fetch_and_type_otp",
                    "x": int(cx),
                    "y": int(cy),
                    "rx": rx,
                    "ry": ry,
                    "timeout": timeout_s,
                    "press_enter": bool(self.press_enter_after_otp_var.get()),
                    "time": t,
                })
                self.log(
                    f"✦ [{t:.2f}s] Recorded [F7 Fetch OTP] for [{self.current_test_email or 'active email'}]..."
                )
            else:
                self.log(f"✦ [F7] Fetching fresh OTP for [{self.current_test_email or 'latest'}]...")

            pause_start = time.perf_counter()
            self.is_busy_injecting = True
            try:
                min_ts = self.email_typed_epoch_ms if self.email_typed_epoch_ms > 0 else 0
                otp = self.gmail_fetcher.wait_for_otp(
                    target_email=self.current_test_email,
                    min_epoch_ms=min_ts,
                    timeout_sec=timeout_s,
                    poll_interval=1.0,
                    trash_after_read=False,
                    log_fn=self.log,
                    stop_check_fn=lambda: False,
                )
                if otp:
                    self.log(f"⌨ Typing fetched OTP [{otp}] into active field...")
                    self._type_string_reliably(otp, char_delay=0.05)
                    if self.press_enter_after_otp_var.get():
                        time.sleep(0.1)
                        self.kb_ctrl.press(Key.enter)
                        self.kb_ctrl.release(Key.enter)
                    self._log_signup_result_csv(self.current_test_email or "manual", otp, "OTP_TYPED")
                else:
                    self.log("⚠ Could not fetch OTP during F7.")
            finally:
                self.is_busy_injecting = False
                if self.is_recording:
                    waited = time.perf_counter() - pause_start
                    self.start_time += waited
                    self.log("▶ Recording timer resumed! Continue your final clicks, then press [F8] to stop.")

        threading.Thread(target=_worker, daemon=True).start()

    # -------------------- AZURE / AWS EC2 WINDOWS VM KEEP-ALIVE (DETACH RDP) --------------------
    def detach_rdp_keep_vm_alive(self):
        confirm = messagebox.askyesno(
            "Azure / AWS EC2 VM Keep-Alive (Close RDP Safely)",
            "Jab aap Azure ya EC2 Windows VM ko normal [X] se band karte hain, toh Windows screen lock kar deta hai aur mouse/keyboard ruk jata hai.\n\n"
            "Yeh button aapke RDP session ko VM ke internal 'Console Screen' par shift kar dega (tscon /dest:console):\n"
            "  • Aapki RDP window band ho jayegi\n"
            "  • VM ke andar Screen 100% ON aur Unlocked rahegi\n"
            "  • Bot peeche 24/7 Browser clicks + OTP testing karta rahega!\n\n"
            "Kya aap abhi RDP safely detach karna chahte hain? (Run Bot as Administrator on VM)",
        )
        if not confirm:
            return

        bat_path = os.path.join(self.base_dir, "keep_vm_screen_alive.bat")
        self.log("☁ Detaching RDP session to Console so VM screen stays 100% active in background...")
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "cmd.exe", f'/c ""{bat_path}""', self.base_dir, 1
            )
        except Exception as e:
            self.log(f"⚠ Could not launch VM Keep-Alive script: {e}")

    # -------------------- RECORDING (START / PAUSE / RESUME / STOP) --------------------
    def toggle_recording(self, from_gui_button: bool = False):
        if self.is_playing or (time.perf_counter() - self.playback_finished_time < 0.8):
            return
        if not self.is_recording:
            self.start_recording(from_gui_button=from_gui_button)
        else:
            self.stop_recording(from_gui_button=from_gui_button)

    def toggle_pause_recording(self, from_gui_button: bool = False):
        if not self.is_recording or self.is_playing:
            return

        self.screen = get_full_screen_bounds()
        sw, sh = self.screen["width"], self.screen["height"]

        if not self.is_paused:
            self.is_paused = True
            self.pause_start_perf = time.perf_counter()

            if from_gui_button and self.events:
                now_perf = self.pause_start_perf
                stop_elapsed = self.events[-1]["time"]
                if self.bot_deiconified_time > 0 and (now_perf - self.bot_deiconified_time) < 2.2:
                    cutoff_window = (now_perf - self.bot_deiconified_time) + 0.35
                else:
                    cutoff_window = 0.45

                removed = 0
                while self.events and (stop_elapsed - self.events[-1]["time"]) <= cutoff_window:
                    if self.events[-1]["type"] in ("mouse_click", "mouse_move"):
                        self.events.pop()
                        removed += 1
                    else:
                        break
                if removed > 0:
                    self.log(f"✓ Trimmed 'Pause Recording' button click ({removed} trailing event(s)).")

            self.pause_rec_btn.configure(
                text="▶ Resume Rec (F6)",
                fg_color=ACCENT_GREEN,
                hover_color="#059669",
                text_color="white",
            )
            self._set_status(f"❚❚ PAUSED ({sw}×{sh})", "#FBBF24", "#451A03")
            self.log("❚❚ Recording PAUSED! Timer frozen & actions ignored until you press [F6] or Resume.")
        else:
            if from_gui_button and self.auto_min_var.get():
                self.root.iconify()
                time.sleep(0.15)

            paused_duration = time.perf_counter() - self.pause_start_perf
            self.start_time += paused_duration
            self.is_paused = False

            self.pause_rec_btn.configure(
                text="❚❚ Pause Rec (F6)",
                fg_color="#D97706",
                hover_color="#B45309",
                text_color="white",
            )
            self._set_status(f"● RECORDING ({sw}×{sh})", "#F87171", "#450A0A")
            self.log(f"▶ Recording RESUMED! (Skipped {paused_duration:.1f}s pause gap).")

    def start_recording(self, from_gui_button: bool = False):
        if self.is_playing:
            return

        self.screen = get_full_screen_bounds()
        sw, sh = self.screen["width"], self.screen["height"]

        if self.auto_min_var.get():
            self.root.iconify()
            time.sleep(0.15)

        self.events = []
        self._typed_buffer = ""
        self.clicks_since_email = 0
        self.is_recording = True
        self.is_paused = False
        self.pause_start_perf = 0.0
        self.start_time = time.perf_counter()
        self.last_move_time = 0.0

        self.record_btn.configure(text="■ Stop Rec (F8)", fg_color=ACCENT_AMBER, hover_color="#D97706")
        self.pause_rec_btn.configure(
            state="normal",
            text="❚❚ Pause Rec (F6)",
            fg_color="#D97706",
            hover_color="#B45309",
            text_color="white",
        )
        self._set_status(f"● RECORDING ({sw}×{sh})", "#F87171", "#450A0A")
        self.log(
            "● Recording started! Use [F6] to Pause/Resume, [F2] (@nariwal.shop) or [F4] (mobile.j3pro@gmail.com) for Email, and [F8] to Stop."
        )

        self.mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self.kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self.mouse_listener.start()
        self.kb_listener.start()
        self._tick_recording_timer()

    def _tick_recording_timer(self):
        if not self.is_recording:
            return
        if not self.is_paused and not self.is_busy_injecting:
            elapsed = time.perf_counter() - self.start_time
            self.stats_lbl.configure(
                text=f"{len(self.events)} Actions · {elapsed:.1f}s"
            )
        self.root.after(100, self._tick_recording_timer)

    def stop_recording(self, from_gui_button: bool = False):
        if not self.is_recording:
            return
        if self.is_paused:
            self.start_time += (time.perf_counter() - self.pause_start_perf)
            self.is_paused = False
        self.is_recording = False
        self.auto_otp_session_id += 1

        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        if self.kb_listener:
            self.kb_listener.stop()
            self.kb_listener = None

        if self.root.state() == "iconic":
            self.root.deiconify()

        if from_gui_button and self.events:
            now_perf = time.perf_counter()
            stop_elapsed = self.events[-1]["time"]
            if self.bot_deiconified_time > 0 and (now_perf - self.bot_deiconified_time) < 2.2:
                cutoff_window = (now_perf - self.bot_deiconified_time) + 0.35
            else:
                cutoff_window = 0.45

            removed = 0
            while self.events and (stop_elapsed - self.events[-1]["time"]) <= cutoff_window:
                if self.events[-1]["type"] in ("mouse_click", "mouse_move"):
                    self.events.pop()
                    removed += 1
                else:
                    break
            if removed > 0:
                self.log(f"✓ Trimmed final 'Stop Recording' click ({removed} trailing event(s)).")

        self.screen = get_full_screen_bounds()
        sw, sh = self.screen["width"], self.screen["height"]
        self.record_btn.configure(text="● Start Rec (F8)", fg_color="#E11D48", hover_color="#BE123C")
        self.pause_rec_btn.configure(
            state="disabled",
            text="❚❚ Pause Rec (F6)",
            fg_color="#272732",
            text_color="#9CA3AF",
        )
        self._set_status(f"● IDLE ({sw}×{sh})", "#38BDF8", CARD_INNER)
        self._update_stats()

        try:
            with open(self.default_file, "w", encoding="utf-8") as f:
                json.dump(self.events, f, indent=2)
            total_t = self.events[-1]["time"] if self.events else 0.0
            self.log(
                f"✓ Recording saved ({len(self.events)} actions, {total_t:.2f}s) → recorded_actions.json"
            )
        except Exception as e:
            self.log(f"⚠ Recording stopped, but auto-save failed: {e}")

    def _elapsed(self) -> float:
        if self.is_paused:
            return round(max(0.0, self.pause_start_perf - self.start_time), 4)
        return round(max(0.0, time.perf_counter() - self.start_time), 4)

    def _on_move(self, x, y):
        self.last_move_perf = time.perf_counter()
        if not self.is_recording or self.is_paused or self.is_busy_injecting:
            return
        now = self.last_move_perf
        if now - self.last_move_time >= self.move_sample_interval:
            self.last_move_time = now
            cx, cy = self._clamp_to_full_screen(x, y)
            rx, ry = self._to_relative_coords(cx, cy)
            self.events.append({
                "type": "mouse_move",
                "x": cx,
                "y": cy,
                "rx": rx,
                "ry": ry,
                "screen_w": self.screen["width"],
                "screen_h": self.screen["height"],
                "time": self._elapsed(),
            })

    def _on_click(self, x, y, button, pressed):
        if pressed and not self.is_busy_injecting and not self.is_paused:
            self.clicks_since_email += 1
            self.last_click_perf = time.perf_counter()
        if not self.is_recording or self.is_paused or self.is_busy_injecting:
            return
        t = self._elapsed()
        if t < 0.25 and not pressed:
            return

        cx, cy = self._clamp_to_full_screen(x, y)
        rx, ry = self._to_relative_coords(cx, cy)
        btn_name = serialize_button(button)
        ev_dict = {
            "type": "mouse_click",
            "x": cx,
            "y": cy,
            "rx": rx,
            "ry": ry,
            "screen_w": self.screen["width"],
            "screen_h": self.screen["height"],
            "button": btn_name,
            "pressed": bool(pressed),
            "time": t,
        }
        self.events.append(ev_dict)
        action_str = "Down" if pressed else "Up"
        self.log(f"Mouse {btn_name} {action_str} at ({cx}, {cy}) [{rx*100:.1f}%, {ry*100:.1f}%] @ {t:.2f}s")

        # Automatically capture OCR Anchor on Mouse Down ONLY for dynamic list targets (@nariwal.shop, mobile.j3pro, etc.)
        if pressed and self.smart_target_var.get():
            def _capture_click_anchor(target_ev, click_x, click_y):
                try:
                    scr_img = grab_full_screen_pil(self.screen)
                    info = extract_anchor_info_at_cursor(
                        scr_img,
                        click_x,
                        click_y,
                        domain_hint=self.domain_var.get(),
                        secondary_email_hint=self.secondary_email_var.get(),
                        custom_target_hint=self.smart_target_text_var.get(),
                        allow_any_text=False,
                        origin_x=self.screen["origin_x"],
                        origin_y=self.screen["origin_y"],
                    )
                    anc_txt = info.get("anchor_text", "")
                    if anc_txt:
                        target_ev["anchor_text"] = anc_txt
                        self.log(f"🎯 Auto-Anchored Dynamic List Click: ['{anc_txt}'] (Will track up/down!)")
                except Exception:
                    pass

            threading.Thread(
                target=_capture_click_anchor, args=(ev_dict, cx, cy), daemon=True
            ).start()

    def _on_scroll(self, x, y, dx, dy):
        if not self.is_recording or self.is_paused or self.is_busy_injecting:
            return
        t = self._elapsed()
        cx, cy = self._clamp_to_full_screen(x, y)
        rx, ry = self._to_relative_coords(cx, cy)
        self.events.append({
            "type": "mouse_scroll",
            "x": cx,
            "y": cy,
            "rx": rx,
            "ry": ry,
            "screen_w": self.screen["width"],
            "screen_h": self.screen["height"],
            "dx": int(dx),
            "dy": int(dy),
            "time": t,
        })
        self.log(f"Mouse Scroll ({dx}, {dy}) at ({cx}, {cy}) @ {t:.2f}s")

    def _on_key_press(self, key):
        if not self.is_recording or self.is_paused or self.is_busy_injecting or key in self.control_keys:
            return
        k_data = serialize_key(key)
        t = self._elapsed()
        self.events.append({
            "type": "key_press",
            "key": k_data,
            "time": t,
        })

        ch = k_data.get("char")
        val = k_data.get("value")
        if ch and len(ch) == 1:
            self._typed_buffer += ch
            if len(self._typed_buffer) > 80:
                self._typed_buffer = self._typed_buffer[-80:]
            m = re.search(r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)$", self._typed_buffer)
            if m:
                detected_email = m.group(1)
                self.current_test_email = detected_email
                self.email_typed_epoch_ms = int(time.time() * 1000)
                self.root.after(
                    0, lambda em=detected_email: self.current_email_lbl.configure(text=f"Email: {em}")
                )
        elif val == "backspace":
            self._typed_buffer = self._typed_buffer[:-1]
        elif val in ("enter", "tab", "space"):
            self._typed_buffer += " "

        label = ch or val or str(k_data.get("vk"))
        self.log(f"Key Down: [{label}] @ {t:.2f}s")

    def _on_key_release(self, key):
        if not self.is_recording or self.is_paused or self.is_busy_injecting or key in self.control_keys:
            return
        k_data = serialize_key(key)
        self.events.append({
            "type": "key_release",
            "key": k_data,
            "time": self._elapsed(),
        })

    # -------------------- PLAYBACK --------------------
    def toggle_playback(self, from_gui_button: bool = False):
        if self.is_recording:
            self.stop_recording(from_gui_button=False)
        if not self.is_playing:
            self.start_playback()
        else:
            self.stop_playback_flag = True
            self.log("■ Stopping playback...")

    def start_playback(self):
        if not self.events:
            messagebox.showinfo(
                "No Actions", "Please record some actions or load a JSON file first!"
            )
            return

        speed_label = self.speed_label_var.get()
        speed = self.speed_options.get(speed_label, 1.0)

        try:
            loops = int(self.loop_var.get())
        except ValueError:
            loops = 1

        self.screen = get_full_screen_bounds()
        sw, sh = self.screen["width"], self.screen["height"]

        if self.auto_min_var.get():
            self.root.iconify()

        self.is_playing = True
        self.stop_playback_flag = False
        self.record_btn.configure(state="disabled")
        self.play_btn.configure(text="■ Stop Loop (F9)", fg_color=ACCENT_AMBER, hover_color="#D97706")
        self._set_status(f"▶ PLAYING ({sw}×{sh})", "#34D399", "#064E3B")

        play_thread = threading.Thread(
            target=self._playback_worker,
            args=(speed, loops),
            daemon=True,
        )
        play_thread.start()

    def _is_dynamic_list_anchor(self, anc_txt: str) -> bool:
        if not anc_txt:
            return False
        low = anc_txt.strip().lower()
        clean_dom = self.domain_var.get().strip().lstrip("@").lower() or "nariwal.shop"
        clean_sec = self.secondary_email_var.get().strip().lower() or "mobile.j3pro@gmail.com"
        custom_t = self.smart_target_text_var.get().strip().lower()
        if clean_dom in low or clean_sec in low or "j3pro" in low:
            return True
        if "add new contact" in low or "new contact info" in low:
            return True
        if custom_t and custom_t in low:
            return True
        return False

    def _playback_worker(self, speed: float, loops: int):
        if self.auto_min_var.get():
            time.sleep(0.25)

        has_otp_step = any(ev.get("type") == "fetch_and_type_otp" for ev in self.events)
        if has_otp_step and not self.gmail_fetcher.is_connected():
            self.log("⟳ Macro contains Gmail OTP step — connecting to Gmail API first...")
            if not self.gmail_fetcher.authenticate(log_fn=self.log):
                self.log("✖ Cannot run OTP step without Gmail OAuth connection!")

        loop_num = 0
        pressed_keys = []
        pressed_buttons = []
        total_rec_time = self.events[-1]["time"] if self.events else 0.0
        expected_play_time = total_rec_time / speed
        self.screen = get_full_screen_bounds()
        sw, sh = self.screen["width"], self.screen["height"]

        self.log(
            f"▶ Playback started across {sw}×{sh} screen (Base duration: {expected_play_time:.2f}s @ {speed}x)"
        )

        try:
            while not self.stop_playback_flag:
                loop_num += 1
                if loops > 0 and loop_num > loops:
                    break

                self.log(f"⟳ Running Signup Loop #{loop_num}...")

                self.email_typed_epoch_ms = int(time.time() * 1000)
                loop_start_clock = time.perf_counter()
                expected_pos = None
                active_click_lock_pos = None

                for event in self.events:
                    if self.stop_playback_flag:
                        break

                    target_clock = loop_start_clock + (event["time"] / speed)

                    while True:
                        if self.stop_playback_flag:
                            break
                        now = time.perf_counter()
                        remaining = target_clock - now
                        if remaining <= 0:
                            break

                        if self.self_heal_var.get() and expected_pos is not None:
                            cur_x, cur_y = self.mouse_ctrl.position
                            if abs(cur_x - expected_pos[0]) > 6 or abs(cur_y - expected_pos[1]) > 6:
                                self._force_move_and_verify(expected_pos[0], expected_pos[1], max_retries=2)

                        if remaining > 0.015:
                            time.sleep(0.01)
                        elif remaining > 0.001:
                            time.sleep(0.001)

                    if self.stop_playback_flag:
                        break

                    elapsed_now = time.perf_counter() - loop_start_clock
                    self.root.after(
                        0,
                        lambda el=elapsed_now, tot=expected_play_time, ln=loop_num: self.stats_lbl.configure(
                            text=f"Loop #{ln} · {el:.1f}s / {tot:.1f}s"
                        ),
                    )

                    etype = event["type"]
                    if etype == "mouse_move":
                        # Do NOT allow mouse_move events between Mouse Down and Mouse Up to drag off the button!
                        if active_click_lock_pos is not None or pressed_buttons:
                            if active_click_lock_pos is not None:
                                self._force_move_and_verify(
                                    active_click_lock_pos[0], active_click_lock_pos[1], max_retries=1
                                )
                                expected_pos = active_click_lock_pos
                            continue

                        tx, ty = self._resolve_event_coords(event)
                        self._force_move_and_verify(tx, ty, max_retries=1)
                        expected_pos = (tx, ty)

                    elif etype == "mouse_click":
                        tx, ty = self._resolve_event_coords(event)

                        # Check physical mouse bump BEFORE any smart target shift
                        cur_x, cur_y = self.mouse_ctrl.position
                        check_ref_x, check_ref_y = expected_pos if expected_pos is not None else (tx, ty)
                        was_bumped = abs(cur_x - check_ref_x) > 8 or abs(cur_y - check_ref_y) > 8

                        # Smart Visual / OCR Target Resolution on Mouse Down (Only for dynamic list items)
                        if event["pressed"]:
                            anc_txt = event.get("anchor_text", "")
                            if self.smart_target_var.get() and self._is_dynamic_list_anchor(anc_txt):
                                pause_t = time.perf_counter()
                                found = smart_locate_target_on_screen(
                                    self.screen,
                                    tx,
                                    ty,
                                    anchor_text=anc_txt,
                                    template_b64="",
                                    current_test_email=self.current_test_email,
                                    domain_hint=self.domain_var.get(),
                                    vertical_list_mode=True,
                                )
                                loop_start_clock += (time.perf_counter() - pause_t)
                                if found:
                                    fx, fy, reason = found
                                    dy = fy - ty
                                    dx = fx - tx
                                    tx, ty = fx, fy
                                    if abs(dx) > 3 or abs(dy) > 3:
                                        self.log(
                                            f"🎯 Smart-Tracked [{reason}] to ({fx}, {fy}) [shifted ΔY={dy:+d}px]"
                                        )
                            active_click_lock_pos = (tx, ty)
                        else:
                            if active_click_lock_pos is not None:
                                tx, ty = active_click_lock_pos
                                active_click_lock_pos = None

                        self._force_move_and_verify(tx, ty, max_retries=4)
                        expected_pos = (tx, ty)

                        if was_bumped or event["pressed"]:
                            time.sleep(0.015)
                            self._force_move_and_verify(tx, ty, max_retries=3)

                        btn = deserialize_button(event["button"])
                        if event["pressed"]:
                            self.mouse_ctrl.press(btn)
                            pressed_buttons.append(btn)
                        else:
                            self.mouse_ctrl.release(btn)
                            if btn in pressed_buttons:
                                pressed_buttons.remove(btn)

                        self._force_move_and_verify(tx, ty, max_retries=2)
                        action_name = "Down" if event["pressed"] else "Up"
                        if was_bumped and self.self_heal_var.get():
                            self.log(f"✓ Auto-Fixed mouse bump & clicked ({tx}, {ty}) [{action_name}]")

                    elif etype == "smart_target_click":
                        pause_t = time.perf_counter()
                        tx, ty = self._resolve_event_coords(event)
                        anc_txt = event.get("anchor_text", "") or self.smart_target_text_var.get().strip()
                        tmpl_b64 = event.get("template_b64", "") or self.custom_reference_template_b64

                        found = None
                        search_start = time.perf_counter()
                        while time.perf_counter() - search_start < 5.0 and not self.stop_playback_flag:
                            found = smart_locate_target_on_screen(
                                self.screen,
                                tx,
                                ty,
                                anchor_text=anc_txt,
                                template_b64=tmpl_b64,
                                current_test_email=self.current_test_email,
                                domain_hint=self.domain_var.get(),
                            )
                            if found:
                                break
                            time.sleep(0.35)

                        if found:
                            fx, fy, reason = found
                            dy = fy - ty
                            tx, ty = fx, fy
                            self.log(
                                f"🎯 [Loop #{loop_num}] Smart Target Found [{reason}] at ({tx}, {ty}) [ΔY={dy:+d}px] — Clicking!"
                            )
                        else:
                            self.log(
                                f"⚠ [Loop #{loop_num}] Target ['{anc_txt or 'Visual'}'] not found via OCR/Vision, clicking fallback ({tx}, {ty})"
                            )

                        self._force_move_and_verify(tx, ty, max_retries=4)
                        expected_pos = (tx, ty)
                        time.sleep(0.02)
                        self.mouse_ctrl.press(Button.left)
                        time.sleep(0.04)
                        self.mouse_ctrl.release(Button.left)
                        loop_start_clock += (time.perf_counter() - pause_t)

                    elif etype == "mouse_scroll":
                        tx, ty = self._resolve_event_coords(event)
                        self._force_move_and_verify(tx, ty, max_retries=3)
                        expected_pos = (tx, ty)
                        time.sleep(0.01)
                        self.mouse_ctrl.scroll(event["dx"], event["dy"])

                    elif etype == "key_press":
                        k = deserialize_key(event["key"])
                        if k is not None:
                            self.kb_ctrl.press(k)
                            pressed_keys.append(k)

                    elif etype == "key_release":
                        k = deserialize_key(event["key"])
                        if k is not None:
                            self.kb_ctrl.release(k)
                            if k in pressed_keys:
                                pressed_keys.remove(k)

                    elif etype == "insert_dynamic_email":
                        pause_t = time.perf_counter()
                        if self.gmail_fetcher.is_connected():
                            self.gmail_fetcher.snapshot_existing_messages()
                        email = self._get_next_test_email()
                        self.log(f"✦ [Loop #{loop_num}] Typing new domain email: {email}")
                        self._type_string_reliably(email, char_delay=0.03)
                        loop_start_clock += (time.perf_counter() - pause_t)

                    elif etype == "insert_secondary_email":
                        pause_t = time.perf_counter()
                        if self.gmail_fetcher.is_connected():
                            self.gmail_fetcher.snapshot_existing_messages()
                        sec_email = self.secondary_email_var.get().strip() or event.get("email", "mobile.j3pro@gmail.com")
                        self.current_test_email = sec_email
                        self.email_typed_epoch_ms = int(time.time() * 1000)
                        self.root.after(
                            0, lambda em=sec_email: self.current_email_lbl.configure(text=f"Email: {em}")
                        )
                        self.log(f"✦ [Loop #{loop_num}] Typing 2nd forwarded email: {sec_email}")
                        self._type_string_reliably(sec_email, char_delay=0.03)
                        loop_start_clock += (time.perf_counter() - pause_t)

                    elif etype == "fetch_and_type_otp":
                        pause_t = time.perf_counter()
                        try:
                            timeout_s = int(self.otp_timeout_var.get())
                        except ValueError:
                            timeout_s = event.get("timeout", 90)

                        self.log(
                            f"⟳ [Loop #{loop_num}] Waiting for fresh OTP in hussainnariwal@gmail.com for [{self.current_test_email}]..."
                        )
                        otp = self.gmail_fetcher.wait_for_otp(
                            target_email=self.current_test_email,
                            min_epoch_ms=self.email_typed_epoch_ms,
                            timeout_sec=timeout_s,
                            poll_interval=1.0,
                            trash_after_read=False,
                            log_fn=self.log,
                            stop_check_fn=lambda: self.stop_playback_flag,
                        )
                        if otp and not self.stop_playback_flag:
                            if "x" in event and "y" in event:
                                tx, ty = self._resolve_event_coords(event)
                                self._force_move_and_verify(tx, ty, max_retries=3)
                                expected_pos = (tx, ty)
                            self.log(f"⌨ [Loop #{loop_num}] Typing fresh OTP [{otp}] for [{self.current_test_email}]...")
                            self._type_string_reliably(otp, char_delay=0.05)
                            if event.get("press_enter") or self.press_enter_after_otp_var.get():
                                time.sleep(0.1)
                                self.kb_ctrl.press(Key.enter)
                                self.kb_ctrl.release(Key.enter)
                            self._log_signup_result_csv(self.current_test_email or "unknown", otp, f"LOOP_{loop_num}_SUCCESS")
                        else:
                            self._log_signup_result_csv(self.current_test_email or "unknown", None, f"LOOP_{loop_num}_OTP_TIMEOUT")
                            self.log(f"✖ [Loop #{loop_num}] Fresh OTP did not arrive within {timeout_s}s.")

                        loop_start_clock += (time.perf_counter() - pause_t)

                actual_taken = time.perf_counter() - loop_start_clock
                self.log(f"✓ Signup Loop #{loop_num} completed ({actual_taken:.2f}s).")

        except Exception as e:
            self.log(f"✖ Error during playback: {e}")
        finally:
            for k in set(pressed_keys):
                try:
                    self.kb_ctrl.release(k)
                except Exception:
                    pass
            for b in set(pressed_buttons):
                try:
                    self.mouse_ctrl.release(b)
                except Exception:
                    pass

            self.playback_finished_time = time.perf_counter()
            self.is_playing = False
            self.stop_playback_flag = False

            def _restore_ui():
                if self.auto_min_var.get() and self.root.state() == "iconic":
                    self.root.deiconify()
                self.play_btn.configure(text="▶ Play Loop (F9)", fg_color=ACCENT_GREEN, hover_color="#059669")
                self.record_btn.configure(state="normal")

            self.root.after(0, _restore_ui)
            self._set_status(f"● READY ({sw}×{sh})", "#38BDF8", CARD_INNER)
            self._update_stats()
            self.log("✓ All Signup Loops finished! Results saved to signup_test_results.csv")

    # -------------------- FILE MANAGEMENT --------------------
    def clear_actions(self):
        if self.is_recording or self.is_playing:
            return
        self.events = []
        self._update_stats()
        self.log("✓ Cleared all recorded actions.")

    def save_recording(self):
        if not self.events:
            messagebox.showinfo("Empty", "Nothing to save yet!")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Macro Files", "*.json")],
            initialfile="recorded_actions.json",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.events, f, indent=2)
            self.log(f"✓ Saved {len(self.events)} actions to {os.path.basename(path)}")

    def load_recording(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON Macro Files", "*.json")],
        )
        if path:
            self._load_from_path(path)

    def _load_from_path(self, path: str, silent: bool = False):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.events = [ev for ev in data if isinstance(ev, dict) and "time" in ev]
                self._update_stats()
                total_t = self.events[-1]["time"] if self.events else 0.0
                self.log(
                    f"✓ Loaded {len(self.events)} actions ({total_t:.2f}s duration) from {os.path.basename(path)}"
                )
        except Exception as e:
            if not silent:
                messagebox.showerror("Load Error", f"Could not load file:\n{e}")


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    root = ctk.CTk()
    app = ActionRecorderBot(root)
    root.mainloop()
