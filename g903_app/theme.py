"""G903 GUI 共享主题：瑞士国际主义纸白、黑字与红色强调。"""

C = {
    "bg": "#F5F5F0", "panel": "#FFFFFF", "raised": "#E8E8E2",
    "line": "#C4C4BC", "text": "#000000", "muted": "#62625C",
    "accent": "#D52B1E", "warn": "#982018",
}


def apply_base_style(style):
    style.theme_use("clam")
    style.configure(".", font=("Microsoft YaHei UI", 10),
                    background=C["bg"], foreground=C["text"],
                    bordercolor=C["line"], lightcolor=C["line"],
                    darkcolor=C["line"], troughcolor=C["raised"])
    style.configure("TFrame", background=C["bg"])
    style.configure("TLabel", background=C["bg"], foreground=C["text"])
    style.configure("TSeparator", background=C["line"])
    style.configure("TButton", padding=(20, 10), background=C["bg"],
                    foreground=C["text"], relief="flat", borderwidth=1,
                    focusthickness=2, focuscolor=C["accent"])
    style.map("TButton",
              background=[("disabled", C["raised"]),
                          ("pressed", C["line"]), ("active", C["raised"])],
              foreground=[("disabled", C["muted"])],
              bordercolor=[("disabled", C["line"]), ("focus", C["accent"]),
                           ("active", C["text"])],
              lightcolor=[("disabled", C["line"]), ("focus", C["accent"])],
              darkcolor=[("disabled", C["line"]), ("focus", C["accent"])])
    style.configure("Accent.TButton", background=C["accent"], foreground="#FFFFFF",
                    bordercolor=C["accent"], lightcolor=C["accent"],
                    darkcolor=C["accent"], focuscolor=C["text"])
    style.map("Accent.TButton",
              background=[("disabled", C["raised"]),
                          ("pressed", "#7C1A13"), ("active", C["warn"])],
              foreground=[("disabled", C["muted"])],
              bordercolor=[("disabled", C["line"]), ("focus", C["text"])],
              lightcolor=[("disabled", C["line"]), ("focus", C["text"])],
              darkcolor=[("disabled", C["line"]), ("focus", C["text"])])
    style.configure("TCombobox", padding=(10, 8), relief="flat", borderwidth=1,
                    fieldbackground=C["panel"], background=C["bg"],
                    foreground=C["text"], arrowcolor=C["muted"],
                    selectbackground=C["text"], selectforeground="#FFFFFF")
    style.map("TCombobox",
              fieldbackground=[("disabled", C["raised"]), ("readonly", C["panel"])],
              foreground=[("disabled", C["muted"]), ("readonly", C["text"])],
              background=[("disabled", C["raised"]), ("active", C["raised"])],
              arrowcolor=[("disabled", C["muted"]), ("active", C["text"])],
              bordercolor=[("disabled", C["line"]), ("focus", C["accent"]),
                           ("active", C["text"])],
              lightcolor=[("focus", C["accent"])],
              darkcolor=[("focus", C["accent"])])
    style.configure("TNotebook", background=C["bg"], borderwidth=0,
                    bordercolor=C["bg"], lightcolor=C["bg"], darkcolor=C["bg"],
                    tabmargins=(0, 0, 0, 12))
    style.configure("TNotebook.Tab", background=C["bg"], foreground=C["muted"],
                    padding=(24, 10), borderwidth=0, relief="flat",
                    bordercolor=C["bg"], lightcolor=C["bg"], darkcolor=C["bg"],
                    focuscolor=C["accent"], focusthickness=2)
    style.map("TNotebook.Tab",
              background=[("disabled", C["bg"]), ("selected", C["text"]),
                          ("active", C["raised"])],
               foreground=[("disabled", C["muted"]), ("selected", "#FFFFFF"),
                           ("active", C["text"])],
              bordercolor=[("selected", C["text"])],
              lightcolor=[("selected", C["text"])],
              darkcolor=[("selected", C["text"])])
