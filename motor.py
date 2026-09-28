"""Leitura dos canhotos (OCR) e conferência com a lista de NFs."""
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from PIL import Image, ImageOps

EXTENSOES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}
# Palavras que só aparecem em canhoto de NF
MARCAS_CANHOTO = ["NOTA FISCAL", "NF-E", "RECEBEDOR", "RECEBEMOS", "CANHOTO", "SERIE", "SÉRIE"]
# "Nº 544241", "N° 544241", "No. 544241", e "N2. 36839" (OCR confunde º com 2)
RE_NF = re.compile(r"N\s*[º°oO02\.]\s*\.?\s*:?\s*(\d[\d\.\s]{3,11}\d)")
# Cabeçalho do controle de canhotos: "Nº 5862679 ATÉ Nº 5862705"
RE_FAIXA = re.compile(r"N\S{0,3}\s*(\d{4,10})\s*(?:\|\s*)?AT[ÉE]\s*(?:\|\s*)?N\S{0,3}\s*(\d{4,10})", re.I)
RE_CARGA = re.compile(r"CARGA\s*[:.]?\s*(\d{6,10})", re.I)

PASTA_DADOS = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LeitorCanhotos"
CACHE = PASTA_DADOS / "cache_ocr.json"  # não relê imagens já processadas

_ocr = None


def ocr_engine():
    global _ocr
    if _ocr is None:
        from rapidocr import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def ler_lista(texto, coluna_nf=4):
    """Aceita linhas coladas do Excel (várias colunas) ou só os números, um por linha."""
    linhas = []
    for linha in texto.splitlines():
        if not linha.strip():
            continue
        cols = [c.strip() for c in linha.split("\t")]
        valor = cols[coluna_nf - 1] if len(cols) >= coluna_nf else cols[0]
        nf = re.sub(r"\D", "", valor)
        if nf:
            linhas.append((nf, cols))
    return linhas


def paginas(caminho):
    """Imagens de um arquivo: a própria foto, ou cada página de um PDF."""
    if caminho.suffix.lower() == ".pdf":
        pdf = pdfium.PdfDocument(str(caminho))
        for pagina in pdf:
            yield pagina.render(scale=200 / 72).to_pil().convert("RGB")
    else:
        yield ImageOps.exif_transpose(Image.open(caminho)).convert("RGB")


def ocr_texto(img, rotacao=0):
    img = img.copy()
    # fotos muito grandes deixam o OCR lento sem ganhar precisão
    img.thumbnail((2400, 2400))
    if rotacao:
        img = img.rotate(rotacao, expand=True)
    res = ocr_engine()(np.array(img)[:, :, ::-1])  # RGB -> BGR
    return list(res.txts or [])


def analisar_pagina(img):
    melhor = None
    for rot in (0, 90, 270, 180):  # foto de celular pode vir deitada
        linhas = ocr_texto(img, rot)
        texto = " | ".join(linhas).upper()
        pontos = sum(m in texto for m in MARCAS_CANHOTO)
        if melhor is None or pontos > melhor[0]:
            melhor = (pontos, linhas)
        if pontos >= 2:
            break
    return melhor


def analisar(caminho):
    """OCR do arquivo (parte lenta, vai para o cache): texto lido e se é canhoto."""
    pontos, linhas = 0, []
    for img in paginas(caminho):
        p, l = analisar_pagina(img)
        pontos, linhas = max(pontos, p), linhas + l
    return {"canhoto": pontos >= 2, "texto": " | ".join(linhas)}


def extrair(texto):
    """Do texto lido: NFs (campo Nº), faixas do cabeçalho, cargas e todos os números."""
    so_digitos = lambda s: re.sub(r"\D", "", s).lstrip("0")
    faixas = [(int(a), int(b)) for a, b in RE_FAIXA.findall(texto) if int(a) <= int(b)]
    sem_faixa = RE_FAIXA.sub(" ", texto)  # o "Nº ... ATÉ Nº ..." não é NF de canhoto
    return {
        "nfs": sorted({so_digitos(m) for m in RE_NF.findall(sem_faixa)}),
        "faixas": faixas,
        "cargas": sorted(set(RE_CARGA.findall(texto))),
        "numeros": {so_digitos(n) for n in re.findall(r"\d[\d\.]{3,}\d", texto)},
    }


def listar_arquivos(pastas):
    """Arquivos de imagem/PDF das pastas, sem repetir arquivos idênticos (reenvios no WhatsApp)."""
    vistos, arquivos = set(), []
    for pasta in pastas:
        for p in sorted(Path(pasta).rglob("*")):
            if p.is_file() and p.suffix.lower() in EXTENSOES:
                h = hashlib.md5(p.read_bytes()).hexdigest()
                if h not in vistos:
                    vistos.add(h)
                    arquivos.append(p)
    return arquivos


def processar(pastas, texto_lista, coluna_nf, pasta_saida, progresso=print, parar=lambda: False):
    """Lê todas as imagens, confere com a lista e gera a planilha + cópias.
    progresso(i, total, mensagem) é chamado a cada arquivo."""
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}

    lista = ler_lista(texto_lista, coluna_nf)
    arquivos = listar_arquivos(pastas)
    resultados = {}
    for i, arq in enumerate(arquivos, 1):
        if parar():
            return None
        chave = f"{arq.resolve()}|{arq.stat().st_size}|{arq.stat().st_mtime}"
        if chave not in cache:
            try:
                cache[chave] = analisar(arq)
            except Exception as e:  # arquivo corrompido não derruba o resto
                cache[chave] = {"canhoto": False, "texto": f"ERRO: {e}"}
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        resultados[arq] = r = {**cache[chave], **extrair(cache[chave]["texto"])}
        progresso(i, len(arquivos), f"{arq.name}: {'canhoto ' + ', '.join(r['nfs']) if r['canhoto'] else 'não é canhoto'}")

    def procurar(nf, cols):
        """Retorna (arquivos, status, explicação), do mais certo para o menos certo."""
        nf = nf.lstrip("0")
        exatos = [p for p, r in resultados.items() if nf in r["nfs"]]
        if exatos:
            return exatos, "ENCONTRADO", "Nº da NF lido no canhoto"
        soltos = [p for p, r in resultados.items() if r["canhoto"] and nf in r["numeros"]]
        if soltos:
            return soltos, "CONFERIR", "O número aparece no canhoto, mas fora do campo Nº"
        # O número não foi lido (borrado/cortado): aponta a folha da mesma carga ou cuja faixa inclui a NF
        valores_linha = {re.sub(r"\D", "", c) for c in cols}
        possiveis = [p for p, r in resultados.items()
                     if any(a <= int(nf) <= b and b - a < 500 for a, b in r["faixas"])
                     or valores_linha & set(r["cargas"])]
        if possiveis:
            return possiveis, "POSSÍVEL", "Foto da mesma carga / faixa de NFs, mas o número não foi lido - conferir a foto"
        return [], "NÃO ENCONTRADO", ""

    pasta_saida = Path(pasta_saida)
    pasta_copias = pasta_saida / "canhotos_encontrados"
    pasta_copias.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Solicitadas"
    n_cols = max((len(c) for _, c in lista), default=1)
    cab_lista = [f"Coluna {i}" for i in range(1, n_cols + 1)] if n_cols > 1 else ["NF"]
    ws.append(["NF", "Status", "Como achou", "Arquivo(s)"] + (cab_lista if n_cols > 1 else []))
    cores = {"ENCONTRADO": "C6EFCE", "CONFERIR": "FFEB9C", "POSSÍVEL": "F8CBAD", "NÃO ENCONTRADO": "FFC7CE"}
    contagem = dict.fromkeys(cores, 0)
    copiados = set()
    for nf, cols in lista:
        encontrados, status, como = procurar(nf, cols)
        contagem[status] += 1
        ws.append([nf, status, como, "\n".join(str(a) for a in encontrados)] + (cols if n_cols > 1 else []))
        ws.cell(ws.max_row, 2).fill = PatternFill("solid", fgColor=cores[status])
        ws.cell(ws.max_row, 4).alignment = Alignment(wrap_text=True, vertical="top")
        sufixo = "" if status == "ENCONTRADO" else f"_{status.lower().replace('í', 'i')}"
        for n, a in enumerate(encontrados, 1):
            destino = pasta_copias / f"NF_{nf}{sufixo}{'_' + str(n) if n > 1 else ''}{a.suffix.lower()}"
            if destino not in copiados:
                shutil.copy2(a, destino)
                copiados.add(destino)

    ws2 = wb.create_sheet("Todas as imagens")
    ws2.append(["Arquivo", "É canhoto?", "NFs lidas (Nº)", "Texto lido"])
    for p, r in resultados.items():
        ws2.append([str(p), "SIM" if r["canhoto"] else "não", ", ".join(r["nfs"]), r["texto"][:32000]])

    for planilha in (ws, ws2):
        for c in planilha[1]:
            c.font = Font(bold=True)
        planilha.freeze_panes = "A2"
        for col in planilha.columns:
            planilha.column_dimensions[col[0].column_letter].width = min(
                60, max(len(str(c.value or "").split("\n")[0]) for c in col) + 2)

    planilha = pasta_saida / "resultado.xlsx"
    wb.save(planilha)
    return {"contagem": contagem, "total": len(lista), "arquivos": len(arquivos), "planilha": planilha}
