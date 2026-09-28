"""Janela do Leitor de Canhotos: escolhe as pastas, cola a lista de NFs e clica em Buscar."""
import os
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import motor


def pasta_desktop():
    for p in (Path.home() / "Desktop", Path.home() / "OneDrive" / "Desktop",
              Path.home() / "Área de Trabalho", Path.home() / "Documents"):
        if p.exists():
            return p
    return Path.home()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Leitor de Canhotos de NF")
        self.geometry("760x640")
        self.minsize(640, 540)
        self.cancelar = False
        pad = {"padx": 12, "pady": (10, 4)}

        # 1. Pastas
        ttk.Label(self, text="1. Pastas com as fotos dos canhotos", font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad)
        f = ttk.Frame(self)
        f.pack(fill="x", padx=12)
        self.pastas = tk.Listbox(f, height=4)
        self.pastas.pack(side="left", fill="x", expand=True)
        b = ttk.Frame(f)
        b.pack(side="left", padx=(8, 0))
        ttk.Button(b, text="Adicionar pasta...", command=self.add_pasta).pack(fill="x")
        ttk.Button(b, text="Remover", command=self.rem_pasta).pack(fill="x", pady=4)

        # 2. Lista
        ttk.Label(self, text="2. Cole aqui a lista de NFs (copie do Excel)", font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad)
        f2 = ttk.Frame(self)
        f2.pack(fill="x", padx=12)
        ttk.Label(f2, text="A NF está na coluna nº").pack(side="left")
        self.coluna = tk.IntVar(value=4)
        ttk.Spinbox(f2, from_=1, to=30, width=4, textvariable=self.coluna).pack(side="left", padx=6)
        ttk.Label(f2, text="(se colar só os números, um por linha, isso é ignorado)", foreground="gray").pack(side="left")
        self.lista = tk.Text(self, height=9, wrap="none", font=("Consolas", 9))
        self.lista.pack(fill="both", expand=True, padx=12, pady=4)

        # 3. Buscar
        ttk.Label(self, text="3. Buscar", font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad)
        f3 = ttk.Frame(self)
        f3.pack(fill="x", padx=12)
        self.btn = ttk.Button(f3, text="Buscar canhotos", command=self.iniciar)
        self.btn.pack(side="left")
        self.btn_cancelar = ttk.Button(f3, text="Cancelar", command=self.parar, state="disabled")
        self.btn_cancelar.pack(side="left", padx=6)
        self.barra = ttk.Progressbar(self, mode="determinate")
        self.barra.pack(fill="x", padx=12, pady=6)
        self.status = ttk.Label(self, text="Pronto.", foreground="gray")
        self.status.pack(anchor="w", padx=12, pady=(0, 10))

    def add_pasta(self):
        p = filedialog.askdirectory(title="Escolha a pasta com as fotos")
        if p and p not in self.pastas.get(0, "end"):
            self.pastas.insert("end", os.path.normpath(p))

    def rem_pasta(self):
        for i in reversed(self.pastas.curselection()):
            self.pastas.delete(i)

    def parar(self):
        self.cancelar = True
        self.status.config(text="Cancelando...")

    def iniciar(self):
        pastas = list(self.pastas.get(0, "end"))
        texto = self.lista.get("1.0", "end")
        if not pastas:
            return messagebox.showwarning("Falta a pasta", "Adicione pelo menos uma pasta com as fotos.")
        if not motor.ler_lista(texto, self.coluna.get()):
            return messagebox.showwarning("Falta a lista", "Cole a lista de NFs no campo 2.")
        saida = pasta_desktop() / f"Canhotos {datetime.now():%Y-%m-%d %Hh%M}"
        self.cancelar = False
        self.btn.config(state="disabled")
        self.btn_cancelar.config(state="normal")
        self.status.config(text="Preparando a leitura (a primeira vez demora um pouco)...")
        threading.Thread(target=self.rodar, args=(pastas, texto, self.coluna.get(), saida), daemon=True).start()

    def progresso(self, i, total, msg):
        def ui():
            self.barra.config(maximum=total, value=i)
            self.status.config(text=f"Lendo {i} de {total}  —  {msg}")
        self.after(0, ui)

    def rodar(self, pastas, texto, coluna, saida):
        try:
            r = motor.processar(pastas, texto, coluna, saida, self.progresso, lambda: self.cancelar)
            self.after(0, self.fim, r, None)
        except Exception as e:
            self.after(0, self.fim, None, e)

    def fim(self, r, erro):
        self.btn.config(state="normal")
        self.btn_cancelar.config(state="disabled")
        if erro:
            self.status.config(text="Erro.")
            return messagebox.showerror("Erro", f"Algo deu errado:\n\n{erro}")
        if r is None:
            self.status.config(text="Cancelado. O que já foi lido fica salvo, a próxima busca continua de onde parou.")
            return
        c = r["contagem"]
        self.status.config(text=f"Concluído: {c['ENCONTRADO']} de {r['total']} NFs encontradas em {r['arquivos']} arquivos.")
        messagebox.showinfo("Concluído",
                            f"De {r['total']} NFs da lista:\n\n"
                            f"   Encontradas: {c['ENCONTRADO']}\n"
                            f"   Conferir: {c['CONFERIR']}\n"
                            f"   Possíveis (foto da mesma carga): {c['POSSÍVEL']}\n"
                            f"   Não encontradas: {c['NÃO ENCONTRADO']}\n\n"
                            f"A pasta com a planilha e as fotos renomeadas vai abrir agora.")
        os.startfile(r["planilha"].parent)


def ja_esta_aberto():
    """Impede duas janelas do app ao mesmo tempo (mutex nomeado do Windows)."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, "Global\\LeitorCanhotosNF")
    return kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    import multiprocessing
    import sys
    # no .exe, um processo filho de alguma biblioteca reabriria o app inteiro sem isto
    multiprocessing.freeze_support()
    if len(sys.argv) == 4 and sys.argv[1] == "--teste":  # autoteste: LeitorCanhotos.exe --teste foto.jpg saida.json
        import json
        Path(sys.argv[3]).write_text(json.dumps(motor.analisar(Path(sys.argv[2])), ensure_ascii=False), encoding="utf-8")
    elif ja_esta_aberto():
        tk.Tk().withdraw()
        messagebox.showinfo("Leitor de Canhotos", "O programa já está aberto.")
    else:
        App().mainloop()
