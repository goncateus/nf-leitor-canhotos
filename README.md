# Leitor de Canhotos de NF

Aplicativo desktop (Windows) que encontra, no meio de centenas de fotos e PDFs com nomes aleatórios (como os que chegam pelo WhatsApp), **os canhotos das Notas Fiscais que você procura**, e gera uma planilha dizendo onde está cada um.

Roda 100% offline, no próprio computador: sem API, sem internet, sem custo por imagem.

## O problema

Uma lista com dezenas de NFs cujos canhotos precisam ser devolvidos, e pastas com centenas de fotos misturadas (`5206848bc0ca4a9d...jpg`). Achar cada uma à mão significa abrir imagem por imagem.

## Como funciona

1. **OCR local** ([RapidOCR](https://github.com/RapidAI/RapidOCR) + ONNX Runtime) lê o texto de cada foto ou página de PDF. Fotos deitadas são giradas automaticamente.
2. **Classificação:** a imagem é considerada canhoto quando tem marcas típicas ("NOTA FISCAL", "NF-e", "RECEBEDOR", "SÉRIE"...).
3. **Extração:** o número da NF é lido do campo `Nº`, tolerando erros comuns do OCR (`N°`, `No.`, `N2.`).
4. **Conferência com a lista**, do resultado mais certo para o menos certo:

| Status | Significado |
|---|---|
| ENCONTRADO (verde) | O número da NF foi lido no campo `Nº` do canhoto |
| CONFERIR (amarelo) | O número aparece no canhoto, mas fora do campo `Nº` |
| POSSÍVEL (laranja) | O número não foi lido (borrado/cortado), mas a foto é da **mesma carga** ou a faixa `Nº X ATÉ Nº Y` do cabeçalho inclui a NF |
| NÃO ENCONTRADO (vermelho) | Nenhuma pista |

5. **Saída:** `resultado.xlsx` + as imagens encontradas copiadas e renomeadas (`NF_544203.jpg`).

Detalhes que fazem diferença no uso real:
- **Cache:** imagens já lidas não são processadas de novo, então a segunda busca é quase instantânea.
- **Arquivos duplicados** (reenvios) são ignorados, com base no hash do conteúdo.
- **PDFs** com vários canhotos por página são suportados.

Num teste real com 229 arquivos e 29 NFs solicitadas, 22 foram encontradas automaticamente e as outras 7 ficaram com a foto certa indicada para conferência.

## Uso

**Usuário final:** baixe o `.zip` em *Releases*, descompacte e abra `LeitorCanhotos.exe`.
1. Adicione as pastas com as fotos.
2. Cole a lista de NFs copiada do Excel (informe a coluna da NF) ou só os números.
3. Clique em **Buscar canhotos**.

**A partir do código:**

```bash
pip install -r requirements.txt
python app.py
```

## Gerar o executável

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --windowed --onedir --name LeitorCanhotos --collect-all rapidocr --collect-all onnxruntime --collect-all pypdfium2 --collect-all pypdfium2_raw app.py
```

O resultado fica em `dist/LeitorCanhotos/`. Os modelos de OCR (`.onnx`) ficam na pasta `rapidocr/models` do pacote e são embutidos pelo `--collect-all rapidocr`. Se a pasta estiver vazia, faça uma leitura com `python app.py` antes do build para o RapidOCR baixá-los.

## Estrutura

- `motor.py`: OCR, classificação, extração e conferência com a lista
- `app.py`: interface (Tkinter)
- `lista_exemplo.txt`: formato da lista (dados fictícios)

## Stack

Python · RapidOCR (PP-OCR em ONNX) · ONNX Runtime · pypdfium2 · Pillow · openpyxl · Tkinter · PyInstaller
