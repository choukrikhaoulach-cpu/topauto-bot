from __future__ import annotations

import threading
import tkinter.messagebox as msg

import customtkinter as ctk

from agent_session import ConversationAgent
from config import leads_path


class ChatWindow(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Top Auto Mohammedia — Assistant Groq")
        self.geometry("780x640")
        self.minsize(520, 440)

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("green")

        try:
            self._agent = ConversationAgent(leads_path())
        except RuntimeError as e:
            msg.showerror("Configuration", str(e))
            self._agent = None

        self._thinking = False

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 6))

        self._status = ctk.CTkLabel(top, text="Prêt.", anchor="w")
        self._status.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(top, text="Nouvelle conversation", width=160, command=self._reset_chat).pack(
            side="right"
        )

        self._log = ctk.CTkTextbox(self, wrap="word", font=("Segoe UI", 13))
        self._log.pack(fill="both", expand=True, padx=12, pady=6)
        self._log.configure(state="disabled")

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(6, 12))

        self._entry = ctk.CTkEntry(bottom, placeholder_text="Écrivez votre message…", height=40)
        self._entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._entry.bind("<Return>", lambda e: self._submit())

        self._btn = ctk.CTkButton(bottom, text="Envoyer", width=110, command=self._submit)
        self._btn.pack(side="right")

        if self._agent is None:
            self._btn.configure(state="disabled")
            self._entry.configure(state="disabled")

    def _append_block(self, title: str, body: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", title + "\n", ())
        self._log.insert("end", body.strip() + "\n\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_thinking(self, active: bool) -> None:
        self._thinking = active
        self._status.configure(text="L'IA réfléchit…" if active else "Prêt.")
        state = "disabled" if active else "normal"
        self._btn.configure(state=state)
        self._entry.configure(state=state if self._agent else "disabled")

    def _reset_chat(self) -> None:
        if self._agent is None or self._thinking:
            return
        self._agent.reset()
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        self._status.configure(text="Conversation effacée.")

    def _submit(self) -> None:
        if self._agent is None or self._thinking:
            return
        user_text = self._entry.get().strip()
        if not user_text:
            return
        self._entry.delete(0, "end")
        self._append_block("Vous", user_text)
        self._set_thinking(True)

        def task() -> None:
            try:
                visible, tag, saved = self._agent.send_user_message(user_text)

                def done() -> None:
                    self._append_block("Assistant", visible or "(vide)")
                    if saved:
                        self._status.configure(text="Lead enregistré dans leads.csv.")
                    elif tag.strip().upper() not in ("RIEN", ""):
                        self._status.configure(text=f"Dernière balise : {tag}")
                    else:
                        self._status.configure(text="Prêt.")
                    self._set_thinking(False)

                self.after(0, done)
            except Exception as e:

                def err() -> None:
                    self._set_thinking(False)
                    msg.showerror("Groq", str(e))

                self.after(0, err)

        threading.Thread(target=task, daemon=True).start()


def run_app() -> None:
    app = ChatWindow()
    app.mainloop()
