"""Frameless always-on-top warning popups.

Shown by the daemon when a tracked metric exceeds its configured threshold;
hidden again when it drops back below threshold (with hysteresis to avoid
flicker). Draggable from anywhere on the window. Position is reported back to
the caller so it can be persisted to config.
"""

from typing import Callable, Optional

import customtkinter as ctk


class WarningOverlay(ctk.CTkToplevel):
    BG = "#1a0808"
    ACCENT = "#ff4422"
    TITLE_COLOR = "#ffffff"
    MSG_COLOR = "#cccccc"
    VALUE_COLOR = "#ff8844"
    ICON_COLOR = "#ffaa00"
    WIDTH = 320
    HEIGHT = 90

    def __init__(
        self,
        master,
        *,
        icon: str = "⚠",
        message: str = "Exceeding configured limits",
        on_position_change: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.93)
        self.configure(fg_color=self.BG)
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}")

        self._on_position_change = on_position_change
        self._drag_offset: Optional[tuple[int, int]] = None

        accent = ctk.CTkFrame(self, fg_color=self.ACCENT, width=4, corner_radius=0)
        accent.pack(side="left", fill="y")

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(side="left", fill="both", expand=True, padx=10, pady=8)

        top_row = ctk.CTkFrame(content, fg_color="transparent")
        top_row.pack(fill="x")
        ctk.CTkLabel(top_row, text=icon, font=ctk.CTkFont(size=22),
                     text_color=self.ICON_COLOR).pack(side="left", padx=(0, 8))
        self.title_label = ctk.CTkLabel(
            top_row, text="GPU", anchor="w",
            text_color=self.TITLE_COLOR,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.title_label.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            content, text=message,
            text_color=self.MSG_COLOR, font=ctk.CTkFont(size=11), anchor="w",
        ).pack(fill="x", anchor="w", pady=(1, 0))

        self.value_label = ctk.CTkLabel(
            content, text="—", text_color=self.VALUE_COLOR,
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        )
        self.value_label.pack(fill="x", anchor="w")

        for w in (self, accent, content, top_row, self.title_label, self.value_label):
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)

    def position_at(self, x: int, y: int) -> None:
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

    def update_content(self, gpu_name: str, value_str: str) -> None:
        self.title_label.configure(text=gpu_name)
        self.value_label.configure(text=f"Currently: {value_str}")

    def _start_drag(self, e) -> None:
        self._drag_offset = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _do_drag(self, e) -> None:
        if self._drag_offset is None:
            return
        x = e.x_root - self._drag_offset[0]
        y = e.y_root - self._drag_offset[1]
        self.geometry(f"+{x}+{y}")
        if self._on_position_change is not None:
            self._on_position_change(x, y)
