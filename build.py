"""Construit data/ventes.json et data/quartiers.geojson pour Saint-Nazaire (DVF + IRIS).

Lancé chaque mois par .github/workflows/maj.yml. Stdlib uniquement.
"""
import csv, io, json, statistics, urllib.request, urllib.error, datetime, os, time
from collections import defaultdict

COMMUNE = "44184"  # Saint-Nazaire
DVF = "https://files.data.gouv.fr/geo-dvf/latest/csv/{y}/communes/44/{c}.csv"
IRIS = ("https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/georef-france-iris/exports/geojson"
        "?where=com_code%3D%22{c}%22&select=iris_code,iris_name,geo_shape")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MOIS_STATS = 24  # fenêtre des prix médians par quartier


def get(url):
    for essai in range(4):  # le serveur DVF coupe parfois la connexion
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError:
            raise
        except OSError:
            if essai == 3:
                raise
            time.sleep(5 * (essai + 1))


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def in_ring(x, y, ring):
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][:2]
        xj, yj = ring[j][:2]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_geom(x, y, g):
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    return any(in_ring(x, y, p[0]) and not any(in_ring(x, y, h) for h in p[1:]) for p in polys)


def quartiers():
    path = os.path.join(OUT, "quartiers.geojson")
    if os.path.exists(path):  # découpage IRIS stable : téléchargé une seule fois
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    gj = json.loads(get(IRIS.format(c=COMMUNE)))
    for ft in gj["features"]:
        p = ft["properties"]
        ft["properties"] = {"code": p["iris_code"][0] if isinstance(p["iris_code"], list) else p["iris_code"],
                            "nom": p["iris_name"][0] if isinstance(p["iris_name"], list) else p["iris_name"]}
    return gj


def ventes(annee):
    try:
        rows = list(csv.DictReader(io.StringIO(get(DVF.format(y=annee, c=COMMUNE)))))
    except Exception as e:  # année pas encore publiée
        print(f"{annee}: indisponible ({e})")
        return []
    muts = defaultdict(list)
    for r in rows:
        if r["nature_mutation"] in ("Vente", "Vente en l'état futur d'achèvement"):
            muts[r["id_mutation"]].append(r)
    out = []
    for mid, rs in muts.items():
        types = [r["type_local"] for r in rs]
        if "Maison" in types:
            continue  # maisons exclues (et ventes mixtes ambiguës)
        apparts = {}
        for r in rs:  # une ligne par lot x parcelle : dédoublonner par surface/pièces/coords
            if r["type_local"] == "Appartement" and num(r["surface_reelle_bati"]) > 0:
                apparts[(r["id_parcelle"], r["surface_reelle_bati"], r["nombre_pieces_principales"], r["lot1_numero"])] = r
        if not apparts:
            continue
        a = list(apparts.values())
        prix = num(rs[0]["valeur_fonciere"])
        surf = sum(num(r["surface_reelle_bati"]) for r in a)
        lon, lat = num(a[0]["longitude"]), num(a[0]["latitude"])
        if not prix or not surf or not lon:
            continue
        r0 = a[0]
        out.append({
            "d": r0["date_mutation"],
            "t": "I" if len(a) >= 2 else "A",  # I = immeuble / vente en bloc
            "n": len(a),
            "p": round(prix),
            "s": round(surf),
            "pc": int(num(r0["nombre_pieces_principales"])) if len(a) == 1 else None,
            "neuf": r0["nature_mutation"] != "Vente",
            "adr": f'{r0["adresse_numero"]} {r0["adresse_nom_voie"]}'.strip().title(),
            "x": round(lon, 6), "y": round(lat, 6),
        })
    print(f"{annee}: {len(out)} ventes")
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    gj = quartiers()
    an = datetime.date.today().year
    vs = [v for y in range(an - 5, an + 1) for v in ventes(y)]
    for v in vs:
        v["q"] = next((f["properties"]["code"] for f in gj["features"] if in_geom(v["x"], v["y"], f["geometry"])), None)

    fin = max(v["d"] for v in vs)
    debut = (datetime.date.fromisoformat(fin) - datetime.timedelta(days=30.4 * MOIS_STATS)).isoformat()
    for f in gj["features"]:
        pm2 = [v["p"] / v["s"] for v in vs if v["q"] == f["properties"]["code"] and v["t"] == "A"
               and v["d"] >= debut and 500 < v["p"] / v["s"] < 15000]  # écarte les valeurs aberrantes
        f["properties"]["nb"] = len(pm2)
        f["properties"]["med"] = round(statistics.median(pm2)) if len(pm2) >= 5 else None

    with open(os.path.join(OUT, "quartiers.geojson"), "w", encoding="utf-8") as fh:
        json.dump(gj, fh, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT, "ventes.json"), "w", encoding="utf-8") as fh:
        json.dump({"maj": datetime.date.today().isoformat(), "derniere_vente": fin, "debut_stats": debut,
                   "ventes": sorted(vs, key=lambda v: v["d"], reverse=True)}, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"total {len(vs)} ventes, dernière {fin}")


if __name__ == "__main__":
    assert in_ring(0.5, 0.5, [[0, 0], [1, 0], [1, 1], [0, 1]]) and not in_ring(2, 2, [[0, 0], [1, 0], [1, 1], [0, 1]])
    main()
