"""A translucent Windows wallet and API usage monitor.

The bundled ``fetch_snapshot`` implementation targets BUZZ. The UI consumes a
small normalized snapshot, so other billing and quota APIs can be adapted there.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
VENDOR_DIR = APP_DIR / ".vendor"
sys.path.insert(0, str(VENDOR_DIR / "python"))
sys.path.insert(0, str(VENDOR_DIR / "CustomTkinter"))
sys.path.insert(0, str(VENDOR_DIR / "py-window-styles"))

import customtkinter as ctk  # noqa: E402
import pywinstyles  # noqa: E402


ENV_PATH = APP_DIR / ".env"
HISTORY_PATH = APP_DIR / ".wallet-monitor-history.json"
SETTINGS_PATH = APP_DIR / ".wallet-monitor-settings.json"
LEGACY_SETTINGS_PATH = APP_DIR / ".buzz-widget-settings.json"

MIN_WINDOW_WIDTH = 275
MAX_WINDOW_WIDTH = 720
WINDOW_HEIGHT = 220
DOCK_THRESHOLD_PX = 24
DOCK_HANDLE_LOGICAL_PX = 14
GLASS_BASE = "#000000"
TEXT = "#f5f7fb"
MUTED = "#a8afbd"
SUBTLE = "#747c8d"
LINE = "#333945"
TRACK = "#383f4b"
MINT = "#6fe1c5"
AMBER = "#ffc66d"


class NativePoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class NativeRect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class NativeMonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint),
        ("monitor", NativeRect),
        ("work", NativeRect),
        ("flags", ctypes.c_uint),
    ]


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name.strip()] = value
    return values


def load_config() -> dict[str, Any]:
    env = read_dotenv(ENV_PATH)
    api_key = env.get("BUZZ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("BUZZ_API_KEY was not found in .env")
    try:
        refresh_seconds = max(60, min(3600, int(env.get("BUZZ_REFRESH_SECONDS", "300"))))
    except ValueError:
        refresh_seconds = 300
    return {
        "api_key": api_key,
        "base_url": env.get("BUZZ_BASE_URL", "https://buzzai.cc").strip().rstrip("/"),
        "refresh_seconds": refresh_seconds,
        "symbol": env.get("BUZZ_CURRENCY_SYMBOL", "$").strip() or "$",
    }


def get_json(url: str, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "wallet-monitor/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=18) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(config["base_url"])
    api_key = str(config["api_key"])
    subscription = get_json(f"{base_url}/v1/dashboard/billing/subscription", api_key)
    time.sleep(0.2)
    usage = get_json(f"{base_url}/v1/dashboard/billing/usage", api_key)
    time.sleep(0.2)
    models = get_json(f"{base_url}/v1/models", api_key)
    granted = float(subscription["soft_limit_usd"])
    used = float(usage["total_usage"]) / 100.0
    model_items = models.get("data")
    model_count = len(model_items) if isinstance(model_items, list) else 0
    if not all(math.isfinite(value) for value in (granted, used)):
        raise RuntimeError("BUZZ returned an invalid billing number")
    return {
        "granted": granted,
        "used": used,
        "balance": max(0.0, granted - used),
        "model_count": model_count,
    }


def flatten_history(value: Any) -> list[dict[str, Any]]:
    source = value if isinstance(value, list) else [value]
    flattened: list[dict[str, Any]] = []
    for item in source:
        if not isinstance(item, dict):
            continue
        if all(name in item for name in ("timestamp", "used", "balance")):
            flattened.append(item)
        elif isinstance(item.get("value"), list):
            flattened.extend(flatten_history(item["value"]))
    return flattened


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        raw = json.loads(HISTORY_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    points: list[dict[str, Any]] = []
    for item in flatten_history(raw):
        try:
            stamp = datetime.fromisoformat(str(item["timestamp"])).astimezone()
            points.append(
                {
                    "timestamp": stamp.isoformat(),
                    "used": float(item["used"]),
                    "balance": float(item["balance"]),
                }
            )
        except (TypeError, ValueError, OverflowError):
            continue
    points.sort(key=lambda point: str(point["timestamp"]))
    return points[-6000:]


def save_history(points: list[dict[str, Any]]) -> None:
    temporary = HISTORY_PATH.with_suffix(HISTORY_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(points, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, HISTORY_PATH)


def add_history_point(used: float, balance: float) -> list[dict[str, Any]]:
    points = load_history()
    now = datetime.now().astimezone()
    point = {"timestamp": now.isoformat(), "used": used, "balance": balance}
    if points and (now - datetime.fromisoformat(str(points[-1]["timestamp"]))).total_seconds() < 240:
        points[-1] = point
    else:
        points.append(point)
    cutoff = now - timedelta(days=90)
    points = [
        item
        for item in points
        if datetime.fromisoformat(str(item["timestamp"])) >= cutoff
    ][-6000:]
    save_history(points)
    return points


def usage_delta(points: list[dict[str, Any]], start: datetime, current_used: float) -> float:
    eligible = [
        point
        for point in points
        if datetime.fromisoformat(str(point["timestamp"])) >= start
    ]
    if not eligible:
        return 0.0
    return max(0.0, current_used - float(eligible[0]["used"]))


class WalletMonitorWidget(ctk.CTk):
    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(fg_color=GLASS_BASE)
        self.config_data = config
        self.results: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.busy = False
        self.last_completed = 0.0
        self.refresh_after_id: str | None = None
        self.dock_after_id: str | None = None
        self.drag_origin: tuple[int, int, int, int] | None = None
        self.drag_position: tuple[int, int] | None = None
        self.collapsed = False
        self.docked = False
        self.dock_x = 0
        self.dock_top = 0
        self.hwnd = 0
        self.window_width = self._target_window_width()
        self.data = {
            "balance": 0.0,
            "used": 0.0,
            "granted": 0.0,
            "today": 0.0,
            "week": 0.0,
            "model_count": 0,
            "status": "Syncing",
            "status_color": AMBER,
        }
        self._seed_from_history()
        self._configure_window()
        self._build_layout()
        self._apply_acrylic()
        self._bind_interactions()
        self.render()
        self.after(300, self.refresh)
        self.after(100, self.poll_results)
        if self.docked:
            self.after(700, lambda: self.collapse_dock(force=True))

    def _seed_from_history(self) -> None:
        points = load_history()
        if not points:
            return
        latest = points[-1]
        used = float(latest["used"])
        balance = float(latest["balance"])
        now = datetime.now().astimezone()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        self.data.update(
            balance=balance,
            used=used,
            granted=used + balance,
            today=usage_delta(points, midnight, used),
            week=usage_delta(points, now - timedelta(days=7), used),
        )

    def _target_window_width(self) -> int:
        scaling = max(1.0, float(self._get_window_scaling()))
        logical_screen_width = self.winfo_screenwidth() / scaling
        return max(MIN_WINDOW_WIDTH, min(MAX_WINDOW_WIDTH, round(logical_screen_width / 3 * 1.10)))

    def _configure_window(self) -> None:
        self.title("Wallet Monitor")
        self.overrideredirect(True)
        self.resizable(False, False)
        x, y, self.docked = self._load_position()
        self.dock_x = x
        self.dock_top = y if self.docked else 0
        self.geometry(f"{self.window_width}x{WINDOW_HEIGHT}+{x}+{y}")
        self.wm_attributes("-topmost", True)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

    def _build_layout(self) -> None:
        self.surface = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.surface.grid(row=0, column=0, padx=16, pady=(12, 11), sticky="nsew")
        self.surface.grid_columnconfigure(0, weight=1)
        self.surface.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.surface, fg_color="transparent", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        left = ctk.CTkFrame(header, fg_color="transparent", corner_radius=0)
        left.grid(row=0, column=0, sticky="nw")
        self.balance_caption = ctk.CTkLabel(left, text="当前余额", height=22, text_color=MUTED, font=ctk.CTkFont("Microsoft YaHei UI", 15), anchor="w")
        self.balance_caption.pack(anchor="w")
        self.balance_value = ctk.CTkLabel(left, text="$0.00", height=50, text_color=TEXT, font=ctk.CTkFont("Segoe UI Variable Display", 38), anchor="w")
        self.balance_value.pack(anchor="w", pady=(0, 1))

        right = ctk.CTkFrame(header, fg_color="transparent", corner_radius=0)
        right.grid(row=0, column=1, sticky="se", pady=(14, 2))
        self.used_value = ctk.CTkLabel(right, text="Cumulative  $0.00", height=22, text_color="#d7d3ff", font=ctk.CTkFont("Segoe UI", 14), anchor="e")
        self.used_value.pack(anchor="e")
        self.grant_value = ctk.CTkLabel(right, text="Granted  $0.00", height=22, text_color=MUTED, font=ctk.CTkFont("Segoe UI", 14), anchor="e")
        self.grant_value.pack(anchor="e", pady=(2, 0))

        self.progress = ctk.CTkFrame(self.surface, height=5, corner_radius=3, fg_color=TRACK)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.progress.grid_propagate(False)
        self.progress_fill = ctk.CTkFrame(self.progress, corner_radius=3, fg_color=MINT)
        self.progress_fill.place(x=0, y=0, relheight=1.0, relwidth=0.0)

        meta = ctk.CTkFrame(self.surface, fg_color="transparent", corner_radius=0)
        meta.grid(row=2, column=0, sticky="ew", pady=(4, 6))
        meta.grid_columnconfigure(0, weight=1)
        self.usage_text = ctk.CTkLabel(meta, text="Used 0.0%", height=22, text_color=MUTED, font=ctk.CTkFont("Segoe UI", 14), anchor="w")
        self.usage_text.grid(row=0, column=0, sticky="w")
        self.status_text = ctk.CTkLabel(meta, text="Syncing  |  0 models", height=22, text_color=AMBER, font=ctk.CTkFont("Segoe UI", 14), anchor="e")
        self.status_text.grid(row=0, column=1, sticky="e")

        separator = ctk.CTkFrame(self.surface, height=1, fg_color=LINE, corner_radius=0)
        separator.grid(row=3, column=0, sticky="ew")

        metrics = ctk.CTkFrame(self.surface, fg_color="transparent", corner_radius=0)
        metrics.grid(row=4, column=0, sticky="nsew", pady=(7, 0))
        metrics.grid_columnconfigure(0, weight=1, uniform="metric")
        metrics.grid_columnconfigure(2, weight=1, uniform="metric")

        today = ctk.CTkFrame(metrics, fg_color="transparent", corner_radius=0)
        today.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(today, text="今日增量", height=22, text_color=MUTED, font=ctk.CTkFont("Microsoft YaHei UI", 15), anchor="w").pack(anchor="w")
        self.today_value = ctk.CTkLabel(today, text="$0.0000", height=38, text_color=TEXT, font=ctk.CTkFont("Segoe UI Variable Display", 24, weight="bold"), anchor="w")
        self.today_value.pack(anchor="w", pady=(3, 0))

        vertical = ctk.CTkFrame(metrics, width=1, height=1, fg_color=LINE, corner_radius=0)
        vertical.grid(row=0, column=1, sticky="ns", padx=12)

        week = ctk.CTkFrame(metrics, fg_color="transparent", corner_radius=0)
        week.grid(row=0, column=2, sticky="nsew")
        ctk.CTkLabel(week, text="近 7 日", height=22, text_color=MUTED, font=ctk.CTkFont("Microsoft YaHei UI", 15), anchor="w").pack(anchor="w")
        self.week_value = ctk.CTkLabel(week, text="$0.0000", height=38, text_color=TEXT, font=ctk.CTkFont("Segoe UI Variable Display", 24, weight="bold"), anchor="w")
        self.week_value.pack(anchor="w", pady=(3, 0))

        self.menu = tk.Menu(self, tearoff=False, font=("Segoe UI", 15))
        self.menu.add_command(label="立即刷新", command=lambda: self.refresh(manual=True))
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.close)

        self.dock_grip = ctk.CTkFrame(self, width=40, height=3, corner_radius=2, fg_color=MINT)
        self.dock_grip.place(relx=0.5, rely=1.0, y=-3, anchor="s")

    def _window_handle(self) -> int:
        self.update_idletasks()
        return int(ctypes.windll.user32.GetParent(self.winfo_id()))

    def _native_rect(self) -> tuple[int, int, int, int]:
        rect = NativeRect()
        ctypes.windll.user32.GetWindowRect(self.hwnd or self._window_handle(), ctypes.byref(rect))
        return rect.left, rect.top, rect.right, rect.bottom

    @staticmethod
    def _native_cursor() -> tuple[int, int]:
        point = NativePoint()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    @staticmethod
    def _monitor_work_area(x: int, y: int) -> tuple[int, int, int, int]:
        monitor_from_point = ctypes.windll.user32.MonitorFromPoint
        monitor_from_point.argtypes = [NativePoint, ctypes.c_uint]
        monitor_from_point.restype = ctypes.c_void_p
        monitor = monitor_from_point(NativePoint(x, y), 2)
        info = NativeMonitorInfo()
        info.size = ctypes.sizeof(info)
        ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info))
        return info.work.left, info.work.top, info.work.right, info.work.bottom

    def _set_native_position(self, x: int, y: int) -> None:
        ctypes.windll.user32.SetWindowPos(
            self.hwnd or self._window_handle(),
            ctypes.c_void_p(-1),
            int(x),
            int(y),
            0,
            0,
            0x0211,
        )

    def _apply_acrylic(self) -> None:
        self.update()
        hwnd = self._window_handle()
        self.hwnd = hwnd

        class AccentPolicy(ctypes.Structure):
            _fields_ = [
                ("state", ctypes.c_int),
                ("flags", ctypes.c_uint),
                ("gradient_color", ctypes.c_uint),
                ("animation_id", ctypes.c_int),
            ]

        class CompositionAttributeData(ctypes.Structure):
            _fields_ = [
                ("attribute", ctypes.c_int),
                ("data", ctypes.c_void_p),
                ("size", ctypes.c_size_t),
            ]

        # Fluent Acrylic: about 9.5% navy tint after a further 50% opacity reduction.
        policy = AccentPolicy(4, 2, 0x18241712, 0)
        attribute = CompositionAttributeData(
            19,
            ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p),
            ctypes.sizeof(policy),
        )
        set_composition = ctypes.windll.user32.SetWindowCompositionAttribute
        set_composition.argtypes = [ctypes.c_void_p, ctypes.POINTER(CompositionAttributeData)]
        set_composition.restype = ctypes.c_int

        # Windows 11 system Acrylic first, then the accent recipe for compatibility.
        backdrop = ctypes.c_int(3)  # DWMSBT_TRANSIENTWINDOW / Acrylic
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))
        composition_ok = bool(set_composition(hwnd, ctypes.byref(attribute)))
        if not composition_ok:
            pywinstyles.apply_style(hwnd, "acrylic")

        corner = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
        no_border = ctypes.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(no_border), ctypes.sizeof(no_border))

        # A layered-window alpha weakens native blur, so only use it as a fallback.
        self.wm_attributes("-alpha", 1.0 if composition_ok else 0.328125)

    def _bind_interactions(self) -> None:
        self.bind_all("<ButtonPress-1>", self.start_drag, add="+")
        self.bind_all("<B1-Motion>", self.drag, add="+")
        self.bind_all("<ButtonRelease-1>", self.end_drag, add="+")
        self.bind_all("<Double-Button-1>", lambda _event: self.refresh(manual=True), add="+")
        self.bind_all("<Button-3>", self.show_menu, add="+")
        self.bind("<Enter>", self.expand_dock, add="+")
        self.bind("<Leave>", self.schedule_collapse, add="+")

    def _screen_bounds(self) -> tuple[int, int]:
        width = round(self.window_width * self._get_window_scaling())
        height = round(WINDOW_HEIGHT * self._get_window_scaling())
        return max(0, self.winfo_screenwidth() - width), max(0, self.winfo_screenheight() - height)

    def _load_position(self) -> tuple[int, int, bool]:
        max_x, max_y = self._screen_bounds()
        default_x = max(20, max_x - 40)
        default_y = max(20, max_y - 80)
        for path in (SETTINGS_PATH, LEGACY_SETTINGS_PATH):
            try:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                x = int(float(value.get("x", value.get("left", default_x))))
                y = int(float(value.get("y", value.get("top", default_y))))
                docked = bool(value.get("docked", False))
                dock_top = int(float(value.get("dock_top", y if docked else 0)))
                return x, dock_top if docked else y, docked
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return default_x, default_y, False

    def save_position(self) -> None:
        left, top, _right, _bottom = self._native_rect()
        value = {
            "x": self.dock_x if self.docked else left,
            "y": self.dock_top if self.docked else top,
            "dock_top": self.dock_top,
            "topmost": True,
            "docked": self.docked,
        }
        SETTINGS_PATH.write_text(json.dumps(value, indent=2), encoding="utf-8")

    def money(self, value: float, precise: bool = False) -> str:
        decimals = 4 if precise or abs(value) < 1 else 2
        return f"{self.config_data['symbol']}{value:,.{decimals}f}"

    def render(self) -> None:
        granted = float(self.data["granted"])
        used = float(self.data["used"])
        ratio = max(0.0, min(1.0, used / granted)) if granted > 0 else 0.0
        self.balance_value.configure(text=self.money(float(self.data["balance"])))
        self.used_value.configure(text=f"Cumulative  {self.money(used)}")
        self.grant_value.configure(text=f"Granted  {self.money(granted)}")
        self.progress_fill.place_configure(relwidth=ratio)
        self.usage_text.configure(text=f"Used {ratio * 100:.1f}%")
        self.status_text.configure(
            text=f"{self.data['status']}  |  {self.data['model_count']} models",
            text_color=str(self.data["status_color"]),
        )
        self.today_value.configure(text=self.money(float(self.data["today"]), precise=True))
        self.week_value.configure(text=self.money(float(self.data["week"]), precise=True))

    def refresh(self, manual: bool = False) -> None:
        if self.busy:
            return
        now = time.monotonic()
        if manual and now - self.last_completed < 60:
            self.data.update(status="Just synced", status_color=MINT)
            self.render()
            return
        self.busy = True
        self.data.update(status="Syncing", status_color=AMBER)
        self.render()

        def worker() -> None:
            try:
                self.results.put(("ok", fetch_snapshot(self.config_data)))
            except urllib.error.HTTPError as error:
                self.results.put(("rate" if error.code == 429 else "error", error.code))
            except Exception as error:
                self.results.put(("error", type(error).__name__))

        threading.Thread(target=worker, daemon=True, name="wallet-monitor-refresh").start()

    def poll_results(self) -> None:
        try:
            kind, payload = self.results.get_nowait()
        except queue.Empty:
            self.after(100, self.poll_results)
            return
        self.busy = False
        self.last_completed = time.monotonic()
        if kind == "ok":
            snapshot = dict(payload)
            points = add_history_point(float(snapshot["used"]), float(snapshot["balance"]))
            now = datetime.now().astimezone()
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            self.data.update(
                **snapshot,
                today=usage_delta(points, midnight, float(snapshot["used"])),
                week=usage_delta(points, now - timedelta(days=7), float(snapshot["used"])),
                status="Connected",
                status_color=MINT,
            )
            delay = int(self.config_data["refresh_seconds"] * 1000)
        elif kind == "rate":
            self.data.update(status="Cooling down", status_color=AMBER)
            delay = 120_000
        else:
            self.data.update(status="Sync pending", status_color=AMBER)
            delay = 120_000
        self.render()
        if self.refresh_after_id is not None:
            self.after_cancel(self.refresh_after_id)
        self.refresh_after_id = self.after(delay, self.refresh)
        self.after(100, self.poll_results)

    def _cancel_dock_timer(self) -> None:
        if self.dock_after_id is not None:
            self.after_cancel(self.dock_after_id)
            self.dock_after_id = None

    def start_drag(self, _event: tk.Event[Any]) -> None:
        self._cancel_dock_timer()
        if self.collapsed:
            self.expand_dock()
            self.update_idletasks()
        self.docked = False
        self.collapsed = False
        cursor_x, cursor_y = self._native_cursor()
        window_x, window_y, _right, _bottom = self._native_rect()
        self.drag_origin = (cursor_x, cursor_y, window_x, window_y)
        self.drag_position = (window_x, window_y)

    def drag(self, _event: tk.Event[Any]) -> None:
        if self.drag_origin is None:
            return
        cursor_x, cursor_y = self._native_cursor()
        start_x, start_y, window_x, window_y = self.drag_origin
        x = window_x + cursor_x - start_x
        y = window_y + cursor_y - start_y
        self.drag_position = (x, y)
        self._set_native_position(x, y)

    def end_drag(self, _event: tk.Event[Any]) -> None:
        cursor_x, cursor_y = self._native_cursor()
        work_left, work_top, work_right, work_bottom = self._monitor_work_area(cursor_x, cursor_y)
        left, top, right, bottom = self._native_rect()
        width, height = right - left, bottom - top
        if self.drag_origin is not None:
            start_x, start_y, window_x, window_y = self.drag_origin
            x = window_x + cursor_x - start_x
            y = window_y + cursor_y - start_y
        else:
            x, y = self.drag_position or (left, top)
        x = max(work_left, min(work_right - width, x))
        self.drag_origin = None
        self.drag_position = None
        if y <= work_top + DOCK_THRESHOLD_PX:
            self.docked = True
            self.collapsed = False
            self.dock_x = x
            self.dock_top = work_top
            self._set_native_position(self.dock_x, self.dock_top)
            self.save_position()
            self.after(450, lambda: self.collapse_dock(force=True))
        else:
            self.docked = False
            self.collapsed = False
            y = max(work_top, min(work_bottom - height, y))
            self._set_native_position(x, y)
            self.save_position()
        self.wm_attributes("-topmost", True)

    def collapse_dock(self, force: bool = False) -> None:
        self.dock_after_id = None
        if not self.docked or self.collapsed or (self.drag_origin is not None and not force):
            return
        handle = round(DOCK_HANDLE_LOGICAL_PX * self._get_window_scaling())
        _left, _top, _right, bottom = self._native_rect()
        height = bottom - _top
        self._set_native_position(self.dock_x, self.dock_top - height + handle)
        self.collapsed = True
        self.wm_attributes("-topmost", True)

    def expand_dock(self, _event: tk.Event[Any] | None = None) -> None:
        if not self.docked:
            return
        self._cancel_dock_timer()
        if self.collapsed:
            self._set_native_position(self.dock_x, self.dock_top)
            self.collapsed = False
        self.wm_attributes("-topmost", True)

    def schedule_collapse(self, _event: tk.Event[Any] | None = None) -> None:
        if not self.docked or self.collapsed or self.drag_origin is not None:
            return
        self._cancel_dock_timer()
        self.dock_after_id = self.after(500, self._collapse_if_pointer_outside)

    def _collapse_if_pointer_outside(self) -> None:
        self.dock_after_id = None
        pointer_x, pointer_y = self._native_cursor()
        left, top, right, bottom = self._native_rect()
        inside = left <= pointer_x < right and top <= pointer_y < bottom
        if not inside:
            self.collapse_dock()

    def show_menu(self, event: tk.Event[Any]) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def close(self) -> None:
        self.save_position()
        self.destroy()


def acquire_single_instance() -> int | None:
    if os.name != "nt":
        return None
    create_mutex = ctypes.windll.kernel32.CreateMutexW
    create_mutex.restype = ctypes.c_void_p
    handle = create_mutex(None, False, "Local\\WalletMonitorAcrylicWidget")
    if not handle or ctypes.windll.kernel32.GetLastError() == 183:
        raise SystemExit(0)
    return int(handle)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test", action="store_true")
    arguments, _unknown = parser.parse_known_args()
    config = load_config()
    if arguments.self_test:
        snapshot = fetch_snapshot(config)
        print(f"SELF_TEST_OK models={snapshot['model_count']}")
        return 0

    _mutex = acquire_single_instance()
    ctk.set_appearance_mode("dark")
    app = WalletMonitorWidget(config)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
