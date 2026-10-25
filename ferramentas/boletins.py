# -*- coding: utf-8 -*-
"""Lê os boletins de urna (bu.dat, ASN.1/BER) publicados pelo TSE para uma UF
do 2º turno (pleito 3221) e soma por município. Uso: python boletins.py zz"""
import gzip, json, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

UF = (sys.argv[1] if len(sys.argv) > 1 else "zz").lower()
B = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221/"
AQUI = os.path.dirname(os.path.abspath(__file__))


def get(url, js=True):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "apuracao-2026"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw) if js else raw


def tlv(b, i):
    t = b[i]; i += 1
    tag = t & 0x1f
    if tag == 0x1f:
        tag = 0
        while True:
            x = b[i]; i += 1; tag = (tag << 7) | (x & 0x7f)
            if not x & 0x80:
                break
    l = b[i]; i += 1
    if l & 0x80:
        n = l & 0x7f; l = int.from_bytes(b[i:i + n], "big"); i += n
    return t, tag, l, i


def arvore(b, i=0, fim=None):
    """Árvore BER genérica: lista de (classe, tag, valor ou filhos). Desce em OCTET STRING que contém DER."""
    fim = len(b) if fim is None else fim
    out = []
    while i < fim:
        t, tag, l, j = tlv(b, i)
        v = b[j:j + l]
        if t & 0x20:
            out.append((t >> 6, tag, arvore(b, j, j + l)))
        elif tag == 4 and t >> 6 == 0 and v[:1] == b"\x30":
            out.append((0, 4, arvore(v)))
        else:
            out.append((t >> 6, tag, v))
        i = j + l
    return out


def votos_do_bu(b):
    """Procura o bloco da eleição 6258: SEQUENCE(idEleicao, aptos, ..., votos)."""
    achou = {}

    def inteiro(v):
        return int.from_bytes(v, "big") if isinstance(v, bytes) else None

    def visita(nos):
        for i, (c, tag, v) in enumerate(nos):
            if isinstance(v, list):
                filhos = v
                if len(filhos) >= 2 and filhos[0][1] == 2 and isinstance(filhos[0][2], bytes) and inteiro(filhos[0][2]) == 6258:
                    achou["aptos"] = inteiro(filhos[1][2])
                    achou["votos"] = coleta_votos(filhos)
                visita(filhos)

    def coleta_votos(nos):
        res = {"13": 0, "22": 0, "branco": 0, "nulo": 0}

        def rec(ns):
            for c, tag, v in ns:
                if isinstance(v, list):
                    campos = {(cc, tt): vv for cc, tt, vv in v}
                    if (2, 1) in campos and (2, 2) in campos and not isinstance(campos[(2, 1)], list):
                        tipo, qtd = inteiro(campos[(2, 1)]), inteiro(campos[(2, 2)])
                        if tipo == 1 and (2, 3) in campos:
                            cod = str(inteiro(campos[(2, 3)][0][2]))
                            res[cod] = res.get(cod, 0) + qtd
                        elif tipo == 2:
                            res["branco"] += qtd
                        elif tipo == 3:
                            res["nulo"] += qtd
                    else:
                        rec(v)
        rec(nos)
        return res
    visita(arvore(b))
    return achou


def secao(args):
    mun, zona, ns = args
    base = f"{B}dados/{UF}/{mun}/{zona}/{ns}/"
    try:
        aux = get(f"{base}p003221-{UF}-m{mun}-z{zona}-s{ns}-aux.json")
        h = aux["hashes"][-1]
        arq = next(a["nm"] for a in h["arq"] if a["tp"] == "bu")
        r = votos_do_bu(get(f"{base}{h['hash']}/{arq}", js=False))
        return mun, ns, r
    except Exception as e:
        return mun, ns, {"erro": str(e)[:80]}


if __name__ == "__main__":
    cs = get(f"{B}config/{UF}/{UF}-p003221-cs.json")
    secs, nomes = [], {}
    for a in cs["abr"]:
        for m in a["mu"]:
            nomes[m["cd"]] = m["nm"]
            for z in m["zon"]:
                for s in z["sec"]:
                    if s.get("da") and not s.get("nsp"):  # tem boletim e não é seção agregada a outra
                        secs.append((m["cd"], z["cd"], s["ns"]))
    print(len(secs), "seções com boletim", flush=True)
    por_mun, erros = {}, 0
    with ThreadPoolExecutor(16) as ex:
        for mun, ns, r in ex.map(secao, secs):
            if "erro" in r or "votos" not in r:
                erros += 1; continue
            a = por_mun.setdefault(mun, {"nome": nomes[mun], "secoes": 0, "aptos": 0, "13": 0, "22": 0, "branco": 0, "nulo": 0})
            a["secoes"] += 1; a["aptos"] += r["aptos"] or 0
            for k in ("13", "22", "branco", "nulo"):
                a[k] += r["votos"].get(k, 0)
    json.dump(por_mun, open(os.path.join(AQUI, f"bu-{UF}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("municípios", len(por_mun), "erros", erros)
    jp = [v for v in por_mun.values() if v["nome"] in ("TÓQUIO", "NAGOIA", "HAMAMATSU")]
    print("Japão:", {k: sum(v[k] for v in jp) for k in ("secoes", "13", "22", "branco", "nulo")})
    tot = {k: sum(v[k] for v in por_mun.values()) for k in ("secoes", "aptos", "13", "22", "branco", "nulo")}
    print("Exterior até agora:", tot)
