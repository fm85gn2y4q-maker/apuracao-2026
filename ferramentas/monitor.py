# -*- coding: utf-8 -*-
"""Monitor da apuração do 2º turno: lê a totalização do TSE, as cidades que
fecham e a contagem de boletins de urna publicados; reestima a transferência de
votos do 1º turno (Goodman com simplex) e projeta o resultado final. Imprime uma
linha por rodada e grava monitor-estado.json. Uso: python monitor.py [segundos]"""
import gzip, json, math, os, random, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
B = "https://resultados.tse.jus.br/oficial/ele2026/6258/"
BU = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221/"
INTERVALO = int(sys.argv[1]) if len(sys.argv) > 1 else 60
T1 = json.load(open(os.path.join(AQUI, "..", "primeiro-turno-municipios.json"), encoding="utf-8"))["mun"]
UFS = sorted({k[:2] for k in T1})
ORIG = list(range(3, 13))
NOMES = ["Abstenção", "Brancos", "Nulos", "Lula", "Flávio", "Cury", "Renan", "Caiado", "Zema", "Outros"]
CACHE = os.path.join(AQUI, "monitor-municipios.json")
t2 = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}


def get(url):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "apuracao-2026"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def n(s):
    return float(str(s or 0).replace(",", "."))


def ler(j):
    v = {}
    for a in j["carg"][0]["agr"]:
        for p in a["par"]:
            for c in p["cand"]:
                v[c["n"]] = n(c["vap"])
    return {"te": n(j["e"]["te"]), "y": [v.get("13", 0), v.get("22", 0), n(j["v"]["vb"]), n(j["v"]["vn"]) + n(j["v"].get("vnt")), n(j["e"]["a"])],
            "pst": n(j["s"]["pst"]), "st": n(j["s"]["st"]), "ts": n(j["s"]["ts"]), "dt": j.get("dt"), "ht": j.get("ht"), "tf": j.get("tf"),
            "eleito": [c for c, x in v.items()] if False else [k["n"] for a in j["carg"][0]["agr"] for p in a["par"] for k in p["cand"] if str(k.get("st", "")).lower().startswith("eleit")]}


def proj_simplex(v):
    u = sorted(v, reverse=True); css = th = 0
    for j, x in enumerate(u):
        css += x; t = (css - 1) / (j + 1)
        if x - t > 0:
            th = t
    return [max(0.0, x - th) for x in v]


def ajustar(linhas, iters=4000):
    J, D = 10, 5
    G = [[0.0] * J for _ in range(J)]; H = [[0.0] * D for _ in range(J)]
    for x, y, w in linhas:
        for a in range(J):
            wa = w * x[a]
            if wa:
                Ga, Ha = G[a], H[a]
                for b in range(J):
                    Ga[b] += wa * x[b]
                for d in range(D):
                    Ha[d] += wa * y[d]
    lam = max(sum(abs(v) for v in r) for r in G) or 1
    Bm = [[1.0 if (a == 3 and d == 0) or (a == 4 and d == 1) or (a == 0 and d == 4) else 1 / D for d in range(D)] for a in range(J)]
    Bm = [proj_simplex(r) for r in Bm]
    for _ in range(iters):
        GB = [[sum(G[a][k] * Bm[k][d] for k in range(J)) for d in range(D)] for a in range(J)]
        Bm = [proj_simplex([Bm[a][d] - (GB[a][d] - H[a][d]) / lam for d in range(D)]) for a in range(J)]
    return Bm


def x_de(l):
    return [l[i] / l[2] for i in ORIG]


def prever(x, Bm):
    return [sum(x[a] * Bm[a][d] for a in range(10)) for d in range(5)]


def rodada():
    with ThreadPoolExecutor(12) as ex:
        br = ler(get(f"{B}dados/br/br-c0001-e006258-u.json"))
        ufs = dict(zip(UFS, ex.map(lambda u: _try(lambda: ler(get(f"{B}dados/{u}/{u}-c0001-e006258-u.json"))), UFS)))
        abs_ = dict(zip(UFS, ex.map(lambda u: _try(lambda: get(f"{B}dados/{u}/{u}-e006258-ab.json")), UFS)))
        novas = []
        for u, ab in abs_.items():
            for m in (ab or {}).get("abr", []):
                k = u + m["cdabr"]
                if n(m["s"]["pst"]) >= 100 and k in T1 and not (t2.get(k, {}).get("pst", 0) >= 100):
                    novas.append((u, m["cdabr"], k))
        for (u, cd, k), r in zip(novas, ex.map(lambda t: _try(lambda: ler(get(f"{B}dados/{t[0]}/{t[0]}{t[1]}-c0001-e006258-u.json"))), novas)):
            if r:
                t2[k] = {"te": r["te"], "y": r["y"], "pst": r["pst"]}
        cs = list(ex.map(lambda u: _try(lambda: get(f"{BU}config/{u}/{u}-p003221-cs.json")), UFS))
        zz = [k[2:] for k in T1 if k.startswith("zz")]
        ext = dict(zip(zz, ex.map(lambda cd: _try(lambda: ler(get(f"{B}dados/zz/zz{cd}-c0001-e006258-u.json"))), zz)))
    bus = sum(1 for c in cs if c for a in c["abr"] for m in a["mu"] for z in m["zon"] for s in z["sec"] if s.get("da"))
    secs = sum(1 for c in cs if c for a in c["abr"] for m in a["mu"] for z in m["zon"] for s in z["sec"] if not s.get("nsp"))
    json.dump(t2, open(CACHE, "w", encoding="utf-8"))

    linhas = [(x_de(T1[k]), [v / r["te"] for v in r["y"]], r["te"]) for k, r in t2.items() if r["pst"] >= 100 and r["te"] and T1[k][2]]
    te_tot = sum(l[2] for l in T1.values())
    te_feito = sum(w for _, _, w in linhas)
    out = {"hora": datetime.now().strftime("%H:%M:%S"), "br": br, "cidades": len(linhas), "frac_eleit": te_feito / te_tot * 100,
           "boletins": bus, "secoes": secs}
    if len(linhas) >= 150:
        Bm = ajustar(linhas)
        L = F = 0.0
        for k, l in T1.items():
            if not l[2]:
                continue
            r = t2.get(k)
            if r and r["pst"] >= 100:
                L += r["y"][0]; F += r["y"][1]
            else:
                p = prever(x_de(l), Bm); L += p[0] * l[2]; F += p[1] * l[2]
        erros = []
        for _ in range(6):
            a = [l for l in linhas if random.random() < 0.5]; b = [l for l in linhas if l not in a] if len(linhas) < 2000 else None
            if b is None:
                ids = set(map(id, a)); b = [l for l in linhas if id(l) not in ids]
            Ba = ajustar(a, 1500)
            pl = sum(prever(x, Ba)[0] * w for x, _, w in b); pf = sum(prever(x, Ba)[1] * w for x, _, w in b)
            rl = sum(y[0] * w for _, y, w in b); rf = sum(y[1] * w for _, y, w in b)
            erros.append(pl / (pl + pf) * 100 - rl / (rl + rf) * 100)
        out["proj_lula"] = L / (L + F) * 100
        out["erro"] = math.sqrt(sum(e * e for e in erros) / len(erros))
        out["matriz"] = {NOMES[a]: [round(v * 100, 1) for v in Bm[a]] for a in range(10)}
    out["ufs"] = {u: {"pst": r["pst"], "y": r["y"], "te": r["te"]} for u, r in ufs.items() if r}
    out["exterior_tse"] = {cd: [r["y"][0], r["y"][1], r["pst"]] for cd, r in ext.items() if r}
    json.dump(out, open(os.path.join(AQUI, "monitor-estado.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def _try(f):
    try:
        return f()
    except Exception:
        return None


def linha(o):
    br = o["br"]; vv = br["y"][0] + br["y"][1]
    s = f"[{o['hora']}] seções {br['pst']:.2f}%"
    if vv:
        s += f" | TSE: Lula {br['y'][0] / vv * 100:.2f}% × Flávio {br['y'][1] / vv * 100:.2f}% (dif {abs(br['y'][0] - br['y'][1]):,.0f})".replace(",", ".")
    s += f" | cidades fechadas {o['cidades']} ({o['frac_eleit']:.1f}% eleit.) | boletins {o['boletins']:,}/{o['secoes']:,}".replace(",", ".")
    if "proj_lula" in o:
        p, e = o["proj_lula"], o["erro"]
        m = o["matriz"]
        s += f" | PROJEÇÃO Lula {p:.1f}% (±{1.96 * e:.1f}) × Flávio {100 - p:.1f}%"
        s += f" | transf. p/ Lula/Flávio: Cury {m['Cury'][0]:.0f}/{m['Cury'][1]:.0f}, Renan {m['Renan'][0]:.0f}/{m['Renan'][1]:.0f}, Caiado {m['Caiado'][0]:.0f}/{m['Caiado'][1]:.0f}, Zema {m['Zema'][0]:.0f}/{m['Zema'][1]:.0f}"
    if br.get("eleito"):
        s += f" | TSE MARCOU ELEITO: {br['eleito']}"
    if br.get("tf") == "s":
        s += " | TOTALIZAÇÃO ENCERRADA"
    return s


if __name__ == "__main__":
    while True:
        t0 = time.time()
        try:
            print(linha(rodada()), flush=True)
        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] falha na rodada: {e}", flush=True)
        time.sleep(max(5, INTERVALO - (time.time() - t0)))
