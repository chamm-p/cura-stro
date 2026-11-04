#!/usr/bin/env python3
"""Farb-Previews nachziehen, SOBALD CDS wieder online ist.

Katalog-Previews kommen aktuell als Graustufen von STScI, weil CDS (Farb-DSS2)
ausgefallen ist. Dieses Skript prueft, ob CDS wieder liefert, und NUR dann:
leert es den Preview-Cache und waermt alle Objekte neu vor (dann Farbe von CDS).
Ist CDS noch down, tut es nichts (idempotent, gefahrlos wiederholbar).

Im Backend-Container ausfuehren:
  cd /app && PYTHONPATH=/app python3 - < refresh_color_previews.py
oder via stdin-Pipe (siehe Chat).
"""
import asyncio, glob, os, time
import httpx
from sqlalchemy import select
from app.database import async_session
from app.models.catalog import CatalogObject

CACHE = "/app/outputs/sky"
CDS = "https://alasky.cds.unistra.fr/hips-image-services/hips2fits"

def fov_for(size):
    return min(max(size/60.0*2.0, 0.3), 3.0) if size else 0.5

def cds_online() -> bool:
    try:
        r = httpx.get(CDS, params={"hips":"CDS/P/DSS2/color","ra":10.68,"dec":41.27,
                      "fov":1.0,"width":64,"height":64,"projection":"TAN","format":"jpg"},
                      timeout=12.0, follow_redirects=True)
        return r.status_code == 200 and "image" in r.headers.get("content-type","") and bool(r.content)
    except Exception:
        return False

async def prewarm():
    async with async_session() as db:
        rows = (await db.scalars(select(CatalogObject))).all()
    coords = [(r.ra_deg, r.dec_deg, fov_for(r.size_major_arcmin)) for r in rows if r.ra_deg is not None]
    sem = asyncio.Semaphore(6); done=[0]; fail=[0]; t0=time.time()
    async def one(ra,dec,fov):
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=120) as c:
                    r = await c.get("http://127.0.0.1:8000/api/sky/preview?ra=%s&dec=%s&fov=%s&px=320"%(ra,dec,fov))
                    (done if r.status_code==200 else fail)[0]+=1
            except Exception:
                fail[0]+=1
    await asyncio.gather(*[one(*c) for c in coords])
    print("Neu vorgewaermt: ok=%d fail=%d in %ds"%(done[0],fail[0],int(time.time()-t0)), flush=True)

def main():
    if not cds_online():
        print("CDS noch offline — nichts getan (Cache bleibt, Graustufen).", flush=True)
        return
    n = len(glob.glob(CACHE+"/*.jpg"))
    for f in glob.glob(CACHE+"/*.jpg"):
        try: os.unlink(f)
        except OSError: pass
    print("CDS ONLINE — Cache geleert (%d Dateien), hole Farb-Previews …"%n, flush=True)
    asyncio.run(prewarm())

if __name__ == "__main__":
    main()
