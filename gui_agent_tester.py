"""
Tester local pour l'agent IA Groq (logique proche du nœud n8n « 14 — Agent IA Groq »).
Lancement : pip install -r requirements.txt puis python gui_agent_tester.py
Clé API : variable d'environnement GROQ_API_KEY ou Réglages dans l'interface.
"""

from __future__ import annotations

import json
import os
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"
MAX_TOKENS = 900
TEMPERATURE = 0.3

# Palette proche de WhatsApp Web
COLOR_HEADER = "#075E54"
COLOR_HEADER_LIGHT = "#128C7E"
COLOR_CHAT_BG = "#ECE5DD"
COLOR_BUBBLE_SENT = "#DCF8C6"
COLOR_BUBBLE_RECV = "#FFFFFF"
COLOR_FOOTER_BG = "#F0F2F5"
COLOR_SEND_BTN = "#25D366"
COLOR_SEND_BTN_ACTIVE = "#20BD5A"
COLOR_META = "#667781"
FONT_FAMILY = "Segoe UI"
FONT_CHAT = (FONT_FAMILY, 11)
FONT_SMALL = (FONT_FAMILY, 9)
BUBBLE_WRAP = 380


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def load_system_prompt() -> str:
    p = script_dir() / "prompt_system.txt"
    if not p.is_file():
        raise FileNotFoundError(f"Fichier prompt introuvable : {p}")
    return p.read_text(encoding="utf-8")


def split_agent_reply(raw: str) -> tuple[str, str, dict | None, bool]:
    """Découpe la réponse modèle comme le nœud n8n « 15 — Preparer Reponse »."""
    raw = (raw or "").strip()
    if not raw:
        return "", "RIEN", None, False

    sep = raw.rfind("|||")
    if sep >= 0:
        texte_client = raw[:sep].strip()
        tag = raw[sep + 3 :].strip()
    else:
        texte_client = raw.strip()
        tag = "RIEN"

    lead_data = None
    est_fin = False
    if tag == "FIN":
        est_fin = True
    elif tag.startswith("LEAD:"):
        lead_data = {}
        for part in tag.replace("LEAD:", "", 1).split("|"):
            i = part.find("=")
            if i > 0:
                k = part[:i].strip()
                v = part[i + 1 :].strip()
                if k and v and v not in ("X", "", "null", "undefined"):
                    lead_data[k] = v
        if not lead_data.get("prenom") or not lead_data.get("tel"):
            lead_data = None

    texte_client = (
        re.sub(r"\|\|\|[\s\S]*", "", texte_client)
        .replace("|||", "")
        .strip()
    )
    texte_client = re.sub(r"LEAD:[\w=|.\s\u0600-\u06FF]*", "", texte_client).strip()
    texte_client = re.sub(r"\bFIN\b", "", texte_client).strip()
    texte_client = re.sub(r"\bRIEN\b", "", texte_client).strip()

    return texte_client, tag, lead_data, est_fin


class AgentTesterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Top Auto — WhatsApp (test)")
        self.minsize(420, 560)
        self.geometry("520x720")
        self.configure(bg=COLOR_FOOTER_BG)

        self._chat_outer: tk.Frame | None = None

        try:
            self._system_prompt = load_system_prompt()
        except FileNotFoundError as e:
            messagebox.showerror("Prompt manquant", str(e))
            self._system_prompt = ""

        self._history: list[dict] = []
        self._busy = False

        self.var_api_key = tk.StringVar(value=os.environ.get("GROQ_API_KEY", ""))
        self.var_lang = tk.StringVar(value="FR")
        self.var_history = tk.BooleanVar(value=True)

        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True)

        tab_chat = tk.Frame(nb, bg=COLOR_FOOTER_BG)
        tab_tech = tk.Frame(nb, bg=COLOR_FOOTER_BG)
        nb.add(tab_chat, text="  Discussion  ")
        nb.add(tab_tech, text="  Technique  ")

        self._build_whatsapp_tab(tab_chat)
        self._build_technique_tab(tab_tech)

        def _wheel(event: tk.Event) -> None:
            if self._chat_outer is None or not self._is_under_chat_area(event.widget):
                return
            if event.delta:
                self._canvas.yview_scroll(int(-event.delta / 120), "units")
            elif getattr(event, "num", None) == 4:
                self._canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                self._canvas.yview_scroll(3, "units")

        self.bind_all("<MouseWheel>", _wheel)
        self.bind_all("<Button-4>", _wheel)
        self.bind_all("<Button-5>", _wheel)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _is_under_chat_area(self, widget: tk.Misc | None) -> bool:
        top = self._chat_outer
        if top is None or widget is None:
            return False
        w: tk.Misc | None = widget
        while w is not None:
            if w is top:
                return True
            try:
                w = w.master  # type: ignore[assignment]
            except tk.TclError:
                break
        return False

    def _build_whatsapp_tab(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=COLOR_HEADER, height=56)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        hdr_inner = tk.Frame(header, bg=COLOR_HEADER)
        hdr_inner.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        avatar = tk.Label(
            hdr_inner,
            text="TA",
            fg="white",
            bg=COLOR_HEADER_LIGHT,
            font=(FONT_FAMILY, 12, "bold"),
            width=3,
            height=1,
        )
        avatar.pack(side=tk.LEFT, padx=(0, 10))

        titles = tk.Frame(hdr_inner, bg=COLOR_HEADER)
        titles.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(
            titles,
            text="Top Auto Mohammedia",
            fg="white",
            bg=COLOR_HEADER,
            font=(FONT_FAMILY, 13, "bold"),
        ).pack(anchor=tk.W)
        tk.Label(
            titles,
            text="Assistant Renault · Dacia (test Groq)",
            fg="#BBDEFB",
            bg=COLOR_HEADER,
            font=FONT_SMALL,
        ).pack(anchor=tk.W)

        tk.Button(
            hdr_inner,
            text="Réglages",
            fg="white",
            bg=COLOR_HEADER_LIGHT,
            activebackground="#1FA394",
            activeforeground="white",
            relief=tk.FLAT,
            cursor="hand2",
            command=self._open_settings,
            padx=12,
            pady=6,
            font=FONT_SMALL,
        ).pack(side=tk.RIGHT)

        chat_outer = tk.Frame(parent, bg=COLOR_CHAT_BG)
        chat_outer.pack(fill=tk.BOTH, expand=True)
        self._chat_outer = chat_outer

        self._canvas = tk.Canvas(
            chat_outer,
            bg=COLOR_CHAT_BG,
            highlightthickness=0,
            borderwidth=0,
        )
        scroll = ttk.Scrollbar(chat_outer, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._bubble_container = tk.Frame(self._canvas, bg=COLOR_CHAT_BG)
        self._canvas_window = self._canvas.create_window(
            (0, 0),
            window=self._bubble_container,
            anchor=tk.NW,
        )

        def _on_inner_configure(_event=None) -> None:
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
            self._canvas.yview_moveto(1.0)

        def _on_canvas_configure(e: tk.Event) -> None:
            self._canvas.itemconfigure(self._canvas_window, width=e.width)

        self._bubble_container.bind("<Configure>", _on_inner_configure)
        self._canvas.bind("<Configure>", _on_canvas_configure)

        footer = tk.Frame(parent, bg=COLOR_FOOTER_BG)
        footer.pack(fill=tk.X, padx=0, pady=0)

        input_row = tk.Frame(footer, bg=COLOR_FOOTER_BG)
        input_row.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.input = tk.Text(
            input_row,
            height=3,
            wrap=tk.WORD,
            font=FONT_CHAT,
            relief=tk.FLAT,
            bg="white",
            padx=12,
            pady=10,
            highlightthickness=1,
            highlightbackground="#CED7D6",
            highlightcolor=COLOR_HEADER_LIGHT,
        )
        self.input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self.input.bind("<Control-Return>", self._send_shortcut)

        self.btn_send = tk.Button(
            input_row,
            text="Envoyer",
            fg="white",
            bg=COLOR_SEND_BTN,
            activebackground=COLOR_SEND_BTN_ACTIVE,
            activeforeground="white",
            relief=tk.FLAT,
            cursor="hand2",
            command=self._on_send,
            padx=18,
            pady=12,
            font=(FONT_FAMILY, 11, "bold"),
        )
        self.btn_send.pack(side=tk.RIGHT)

        hint_row = tk.Frame(footer, bg=COLOR_FOOTER_BG)
        hint_row.pack(fill=tk.X, padx=12, pady=(0, 8))
        self.lbl_status = tk.Label(
            hint_row,
            text="Prêt · Ctrl+Entrée pour envoyer",
            fg=COLOR_META,
            bg=COLOR_FOOTER_BG,
            font=FONT_SMALL,
        )
        self.lbl_status.pack(side=tk.LEFT)

        tk.Button(
            hint_row,
            text="Effacer la discussion",
            fg=COLOR_META,
            bg=COLOR_FOOTER_BG,
            activeforeground=COLOR_HEADER,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._clear_chat,
            font=FONT_SMALL,
        ).pack(side=tk.RIGHT)

    def _build_technique_tab(self, parent: tk.Frame) -> None:
        pad = tk.Frame(parent, bg=COLOR_FOOTER_BG)
        pad.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(pad, text="Réponse brute (tag inclus)").pack(anchor=tk.W)
        self.raw_out = ScrolledText(pad, wrap=tk.WORD, state=tk.DISABLED, height=14, font=FONT_SMALL)
        self.raw_out.pack(fill=tk.BOTH, expand=True, pady=(4, 10))

        ttk.Label(pad, text="Tag interne / Lead").pack(anchor=tk.W)
        self.tag_out = ScrolledText(pad, wrap=tk.WORD, state=tk.DISABLED, height=10, font=FONT_SMALL)
        self.tag_out.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        ttk.Label(
            pad,
            text="Clé API et options : bouton « Réglages » dans l’onglet Discussion.",
            font=FONT_SMALL,
        ).pack(anchor=tk.W, pady=(12, 0))

    def _open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("Réglages")
        win.configure(bg=COLOR_FOOTER_BG)
        win.transient(self)
        win.grab_set()
        win.geometry("440x280")
        win.minsize(400, 260)

        f = tk.Frame(win, bg=COLOR_FOOTER_BG, padx=16, pady=16)
        f.pack(fill=tk.BOTH, expand=True)

        tk.Label(f, text="Clé API Groq", bg=COLOR_FOOTER_BG, font=FONT_CHAT).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(f, textvariable=self.var_api_key, width=46, show="•").grid(
            row=1, column=0, columnspan=2, sticky=tk.EW, pady=(4, 12)
        )

        tk.Label(f, text="Langue session", bg=COLOR_FOOTER_BG, font=FONT_CHAT).grid(row=2, column=0, sticky=tk.W)
        ttk.Combobox(
            f,
            textvariable=self.var_lang,
            values=("FR", "AR"),
            state="readonly",
            width=8,
        ).grid(row=2, column=1, sticky=tk.E, pady=(0, 12))

        ttk.Checkbutton(
            f,
            text="Garder l'historique (multi-tours)",
            variable=self.var_history,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(0, 16))

        ttk.Button(f, text="Fermer", command=win.destroy).grid(row=4, column=1, sticky=tk.E)
        f.columnconfigure(0, weight=1)

    def _send_shortcut(self, event=None):
        self._on_send()
        return "break"

    def _append_bubble(self, text: str, *, is_user: bool) -> None:
        row = tk.Frame(self._bubble_container, bg=COLOR_CHAT_BG)
        row.pack(fill=tk.X, padx=10, pady=(8, 4))

        align = tk.Frame(row, bg=COLOR_CHAT_BG)
        align.pack(side=tk.RIGHT if is_user else tk.LEFT)

        bg = COLOR_BUBBLE_SENT if is_user else COLOR_BUBBLE_RECV
        bubble = tk.Frame(align, bg=bg)
        bubble.pack(anchor=tk.E if is_user else tk.W)

        tk.Label(
            bubble,
            text=text,
            bg=bg,
            fg="#111111",
            justify=tk.LEFT,
            wraplength=BUBBLE_WRAP,
            font=FONT_CHAT,
            padx=12,
            pady=8,
        ).pack()

        tk.Label(
            align,
            text="Vous" if is_user else "Assistant",
            fg=COLOR_META,
            bg=COLOR_CHAT_BG,
            font=FONT_SMALL,
        ).pack(anchor=tk.E if is_user else tk.W, pady=(2, 0))

        self.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._canvas.yview_moveto(1.0)

    def _set_side_panel(self, raw_full: str, tag_line: str, lead: dict | None, est_fin: bool) -> None:
        self.raw_out.configure(state=tk.NORMAL)
        self.raw_out.delete("1.0", tk.END)
        self.raw_out.insert(tk.END, raw_full)
        self.raw_out.configure(state=tk.DISABLED)

        self.tag_out.configure(state=tk.NORMAL)
        self.tag_out.delete("1.0", tk.END)
        extras = []
        if est_fin:
            extras.append("FIN de conversation (tag FIN)")
        if lead:
            extras.append("Lead détecté :\n" + json.dumps(lead, ensure_ascii=False, indent=2))
        body = tag_line if tag_line else "RIEN"
        self.tag_out.insert(tk.END, body + ("\n\n" + "\n".join(extras) if extras else ""))
        self.tag_out.configure(state=tk.DISABLED)

    def _clear_chat(self) -> None:
        if self._busy:
            return
        self._history.clear()
        for w in self._bubble_container.winfo_children():
            w.destroy()
        self.raw_out.configure(state=tk.NORMAL)
        self.raw_out.delete("1.0", tk.END)
        self.raw_out.configure(state=tk.DISABLED)
        self.tag_out.configure(state=tk.NORMAL)
        self.tag_out.delete("1.0", tk.END)
        self.tag_out.configure(state=tk.DISABLED)
        self.lbl_status.configure(text="Discussion effacée.")

    def _build_messages(self, lang_prefix_user: str) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": self._system_prompt}]
        if self.var_history.get():
            msgs.extend(self._history)
        msgs.append({"role": "user", "content": lang_prefix_user})
        return msgs

    def _on_send(self, event=None) -> None:
        del event
        if self._busy or not self._system_prompt:
            return

        key = (self.var_api_key.get() or "").strip()
        if not key:
            messagebox.showwarning(
                "Clé API",
                "Ouvre « Réglages » dans le bandeau vert et ajoute ta clé Groq "
                "(ou la variable GROQ_API_KEY).",
            )
            return

        user_text = self.input.get("1.0", tk.END).strip()
        if not user_text:
            return

        lang = self.var_lang.get().strip().upper()
        if lang not in ("FR", "AR"):
            lang = "FR"

        prefixed = f"[Langue: {lang}] {user_text}"

        if not self.var_history.get():
            self._history.clear()

        self._append_bubble(user_text, is_user=True)
        self.input.delete("1.0", tk.END)
        self._busy = True
        self.btn_send.configure(state=tk.DISABLED)
        self.lbl_status.configure(text="Écriture…")

        def worker() -> None:
            try:
                payload = {
                    "model": MODEL,
                    "max_tokens": MAX_TOKENS,
                    "temperature": TEMPERATURE,
                    "messages": self._build_messages(prefixed),
                }
                r = requests.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=120,
                )
                data = r.json()
                if r.status_code >= 400:
                    err = data.get("error", {}).get("message") or data.get("message") or r.text
                    self.after(0, lambda: self._on_error(f"HTTP {r.status_code} : {err}"))
                    return

                raw = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                visible, tag, lead, est_fin = split_agent_reply(raw)

                def finish_ok() -> None:
                    self._append_bubble(visible or "(réponse vide)", is_user=False)
                    self._set_side_panel(raw, tag, lead, est_fin)
                    self._history.append({"role": "user", "content": prefixed})
                    self._history.append(
                        {"role": "assistant", "content": visible or "(vide)"}
                    )
                    self.lbl_status.configure(text="Prêt · Ctrl+Entrée pour envoyer")
                    self._busy = False
                    self.btn_send.configure(state=tk.NORMAL)

                self.after(0, finish_ok)

            except requests.RequestException as e:
                self.after(0, lambda: self._on_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_error(self, msg: str) -> None:
        self._busy = False
        self.btn_send.configure(state=tk.NORMAL)
        self.lbl_status.configure(text="Erreur.")
        messagebox.showerror("Erreur Groq", msg)

    def _on_close(self) -> None:
        try:
            self.unbind_all("<MouseWheel>")
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")
        except tk.TclError:
            pass
        self.destroy()


def main() -> None:
    app = AgentTesterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
