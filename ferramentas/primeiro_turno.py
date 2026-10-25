# -*- coding: utf-8 -*-
"""Baixa o resultado de presidente do 1º turno (eleição 6257) de todos os
municípios e grava ../primeiro-turno-municipios.json, compacto, para a página
de análise usar como base da transferência de votos."""
import gzip, json, os, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://resultados.tse.jus.br/oficial/ele2026/6257/"
AQUI = os.path.dirname(os.path.abspath(__file__))
PRINCIPAIS = ["13", "22", "70", "14", "55", "30"]  # Lula, Flávio, Cury, Renan, Caiado, Zema; o resto vira "outros"


def get(url):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "apuracao-2026"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw)


def n(s):
    return int(s or 0)


def linha(j):
    votos = {}
    for a in j["carg"][0]["agr"]:
        for p in a["par"]:
            for c in p["cand"]:
                votos[c["n"]] = n(c["vap"])
    e, v = j["e"], j["v"]
    outros = sum(x for k, x in votos.items() if k not in PRINCIPAIS)
    # te, abstenção, brancos, nulos (inclui nulo técnico), principais..., outros
    return [n(e["te"]), n(e["a"]), n(v["vb"]), n(v["vn"]) + n(v.get("vnt")), *[votos.get(k, 0) for k in PRINCIPAIS], outros]


def baixar(item):
    uf, cd, ibge, nome = item
    for _ in range(4):
        try:
            return item, linha(get(f"{BASE}dados/{uf}/{uf}{cd}-c0001-e006257-u.json"))
        except Exception as ex:
            err = ex
    return item, None


if __name__ == "__main__":
    cfg = get(BASE + "config/mun-e006257-cm.json")
    itens = [(a["cd"], m["cd"], m.get("cdi", ""), m["nm"]) for a in cfg["abr"] for m in a["mu"]]
    print(len(itens), "municípios", flush=True)
    out, falhas = {}, []
    with ThreadPoolExecutor(16) as ex:
        for i, (item, l) in enumerate(ex.map(baixar, itens), 1):
            if l is None:
                falhas.append(item)
            else:
                out[item[0] + item[1]] = [item[2], item[3]] + l
            if i % 500 == 0:
                print(i, flush=True)
    meta = {"eleicao": "6257", "colunas": ["ibge", "nome", "eleitorado", "abstencao", "brancos", "nulos"] + PRINCIPAIS + ["outros"]}
    json.dump({"meta": meta, "mun": out}, open(os.path.join(AQUI, "..", "primeiro-turno-municipios.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print("ok", len(out), "falhas", len(falhas), falhas[:5])
