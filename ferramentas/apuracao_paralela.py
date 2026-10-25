# -*- coding: utf-8 -*-
"""Apuração paralela: soma os boletins de urna publicados pelo TSE (bu.dat)
de todas as UFs e imprime, lado a lado, a totalização oficial e a soma dos
boletins. Retomável: guarda em bu-apurados.json as seções já lidas.
Uso: python apuracao_paralela.py [segundos] [máximo de boletins por rodada]"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import boletins as bl

AQUI = os.path.dirname(os.path.abspath(__file__))
INTERVALO = int(sys.argv[1]) if len(sys.argv) > 1 else 60
POR_RODADA = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
TSE = "https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json"
ESTADO = os.path.join(AQUI, "bu-apurados.json")
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa", "pb", "pe", "pi", "pr", "rj", "rn",
       "ro", "rr", "rs", "sc", "se", "sp", "to", "zz"]
lidos = json.load(open(ESTADO, encoding="utf-8")) if os.path.exists(ESTADO) else {}
NOMES = {k: l[1] for k, l in json.load(open(os.path.join(AQUI, "..", "primeiro-turno-municipios.json"), encoding="utf-8"))["mun"].items()}


def secao(args):
    uf, mun, zona, ns = args
    bl.UF = uf
    base = f"{bl.B}dados/{uf}/{mun}/{zona}/{ns}/"
    try:
        aux = bl.get(f"{base}p003221-{uf}-m{mun}-z{zona}-s{ns}-aux.json")
        h = aux["hashes"][-1]
        arq = next(a["nm"] for a in h["arq"] if a["tp"] == "bu")
        r = bl.votos_do_bu(bl.get(f"{base}{h['hash']}/{arq}", js=False))
        if "votos" not in r:
            return args, None
        v = r["votos"]
        return args, [r["aptos"] or 0, v.get("13", 0), v.get("22", 0), v.get("branco", 0), v.get("nulo", 0)]
    except Exception:
        return args, None


def rodada():
    with ThreadPoolExecutor(12) as ex:
        cs = dict(zip(UFS, ex.map(lambda u: _try(lambda: bl.get(f"{bl.B}config/{u}/{u}-p003221-cs.json")), UFS)))
    pendentes, publicados = [], 0
    for uf, c in cs.items():
        for a in (c or {}).get("abr", []):
            for m in a["mu"]:
                for z in m["zon"]:
                    for s in z["sec"]:
                        if s.get("da") and not s.get("nsp"):
                            publicados += 1
                            k = f"{uf}-{m['cd']}-{z['cd']}-{s['ns']}"
                            if k not in lidos:
                                pendentes.append((uf, m["cd"], z["cd"], s["ns"]))
    falhas = 0
    with ThreadPoolExecutor(24) as ex:
        for args, r in ex.map(secao, pendentes[:POR_RODADA]):
            if r is None:
                falhas += 1
            else:
                lidos["-".join(args)] = r
    json.dump(lidos, open(ESTADO, "w", encoding="utf-8"))
    tse = _try(lambda: bl.get(TSE))
    return tse, publicados, len(pendentes) - min(len(pendentes), POR_RODADA) + falhas, falhas


def _try(f):
    try:
        return f()
    except Exception:
        return None


def pct(a, b):
    return a / b * 100 if b else 0


def linha(tse, publicados, faltam, falhas):
    s = f"[{datetime.now():%H:%M:%S}] "
    if tse:
        v = {k["n"]: float(k["vap"]) for a in tse["carg"][0]["agr"] for p in a["par"] for k in p["cand"]}
        vv = v.get("13", 0) + v.get("22", 0)
        s += f"TSE {tse['s']['pst']}% seções: " + (f"Lula {pct(v['13'], vv):.2f}% × Flávio {pct(v['22'], vv):.2f}% ({vv:,.0f} válidos)" if vv else "sem votos")
    tot = [0] * 5
    br = [0] * 5
    for k, r in lidos.items():
        for i in range(5):
            tot[i] += r[i]
            if not k.startswith("zz"):
                br[i] += r[i]
    vv = tot[1] + tot[2]
    s += f"  ||  BOLETINS {len(lidos):,} lidos de {publicados:,} publicados: "
    s += f"Lula {pct(tot[1], vv):.2f}% × Flávio {pct(tot[2], vv):.2f}% ({vv:,.0f} válidos; brancos {tot[3]:,}, nulos {tot[4]:,})" if vv else "sem votos"
    vb = br[1] + br[2]
    if vb and vb != vv:
        s += f" | só Brasil: Lula {pct(br[1], vb):.2f}% × Flávio {pct(br[2], vb):.2f}%"
    if faltam:
        s += f" | na fila {faltam:,}"
    return s.replace(",", ".")


def salvar(tse, publicados, faltam, falhas):
    """Grava painel-estado.json e acrescenta um ponto em painel-historico.json."""
    def soma(filtro):
        t = [0] * 5
        n = 0
        for k, r in lidos.items():
            if filtro(k):
                n += 1
                for i in range(5):
                    t[i] += r[i]
        return {"secoes": n, "aptos": t[0], "lula": t[1], "flavio": t[2], "brancos": t[3], "nulos": t[4]}
    ufs = sorted({k[:2] for k in lidos})
    est = {"hora": datetime.now().strftime("%H:%M:%S"), "publicados": publicados, "lidos": len(lidos), "fila": faltam,
           "bu": {"global": soma(lambda k: True), "brasil": soma(lambda k: not k.startswith("zz")),
                  "exterior": soma(lambda k: k.startswith("zz")), "ufs": {u: soma(lambda k, u=u: k.startswith(u + "-")) for u in ufs}}}
    por_mun = {}
    for k, r in lidos.items():
        uf, mun = k.split("-")[:2]
        a = por_mun.setdefault(uf + mun, {"uf": uf, "nome": NOMES.get(uf + mun, mun), "secoes": 0, "lula": 0, "flavio": 0})
        a["secoes"] += 1; a["lula"] += r[1]; a["flavio"] += r[2]
    est["bu"]["municipios"] = sorted(por_mun.values(), key=lambda a: -a["secoes"])[:25]
    est["bu"]["n_municipios"] = len(por_mun)
    est["bu"]["exterior_cidades"] = {k[2:]: [a["lula"], a["flavio"], a["secoes"]] for k, a in por_mun.items() if k.startswith("zz")}
    est["recentes"] = [{"uf": k.split("-")[0], "nome": NOMES.get("".join(k.split("-")[:2]), k.split("-")[1]), "zona": k.split("-")[2],
                        "secao": k.split("-")[3], "aptos": r[0], "lula": r[1], "flavio": r[2], "brancos": r[3], "nulos": r[4]}
                       for k, r in list(lidos.items())[-12:]][::-1]
    if tse:
        v = {k["n"]: float(k["vap"]) for a in tse["carg"][0]["agr"] for p in a["par"] for k in p["cand"]}
        est["tse"] = {"pst": float(tse["s"]["pst"].replace(",", ".")), "secoes": int(tse["s"]["st"]), "total_secoes": int(tse["s"]["ts"]),
                      "lula": v.get("13", 0), "flavio": v.get("22", 0), "brancos": float(tse["v"]["vb"]),
                      "nulos": float(tse["v"]["vn"]) + float(tse["v"].get("vnt") or 0), "comparecimento": float(tse["e"]["c"]),
                      "eleito": [k["nmu"] for a in tse["carg"][0]["agr"] for p in a["par"] for k in p["cand"] if str(k.get("st", "")).lower().startswith("eleit")],
                      "totalizado": f"{tse.get('dt', '')} {tse.get('ht', '')}".strip(), "gerado": f"{tse.get('dg', '')} {tse.get('hg', '')}"}
    json.dump(est, open(os.path.join(AQUI, "painel-estado.json"), "w", encoding="utf-8"), ensure_ascii=False)
    hist_arq = os.path.join(AQUI, "painel-historico.json")
    hist = json.load(open(hist_arq, encoding="utf-8")) if os.path.exists(hist_arq) else []
    pt = {"hora": est["hora"], "bu_n": len(lidos)}
    g, b = est["bu"]["global"], est["bu"]["brasil"]
    if g["lula"] + g["flavio"]:
        pt["bu_lula"] = round(g["lula"] / (g["lula"] + g["flavio"]) * 100, 3)
    if b["lula"] + b["flavio"]:
        pt["bu_br_lula"] = round(b["lula"] / (b["lula"] + b["flavio"]) * 100, 3)
    if tse and est["tse"]["lula"] + est["tse"]["flavio"]:
        pt["tse_lula"] = round(est["tse"]["lula"] / (est["tse"]["lula"] + est["tse"]["flavio"]) * 100, 3)
        pt["tse_pst"] = est["tse"]["pst"]
    mon = _try(lambda: json.load(open(os.path.join(AQUI, "monitor-estado.json"), encoding="utf-8")))
    if mon and "proj_lula" in mon:
        pt["proj_lula"] = round(mon["proj_lula"], 2); pt["proj_erro"] = round(mon["erro"], 2)
    hist.append(pt)
    json.dump(hist, open(hist_arq, "w", encoding="utf-8"))


if __name__ == "__main__":
    while True:
        t0 = time.time()
        try:
            res = rodada()
            print(linha(*res), flush=True)
            salvar(*res)
        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] falha na rodada: {e}", flush=True)
        time.sleep(max(5, INTERVALO - (time.time() - t0)))
