"""Kalıbın Qwen Code ayarlarını mevcut ~/.qwen/settings.json ile birleştirir.

Kalıbın değerleri önceliklidir; kalıpta olmayan mevcut ayarlar korunur.
modelProviders listelerinde aynı "id"li girdi güncellenir, diğerleri korunur.
Kullanım: python3 birlestir.py <mevcut.json> <kalip.json>
"""
import json
import sys


def birlestir(mevcut, yeni):
    for anahtar, deger in yeni.items():
        eski = mevcut.get(anahtar)
        if isinstance(deger, dict) and isinstance(eski, dict):
            birlestir(eski, deger)
        elif isinstance(deger, list) and isinstance(eski, list) and all(
            isinstance(x, dict) and "id" in x for x in deger + eski
        ):
            yeni_idler = {x["id"] for x in deger}
            mevcut[anahtar] = [x for x in eski if x["id"] not in yeni_idler] + deger
        elif isinstance(deger, list) and isinstance(eski, list) and all(
            isinstance(x, str) for x in deger + eski
        ):
            # izin/araç listeleri: kullanıcının kendi eklediklerini koru, kalıbınkileri ekle
            mevcut[anahtar] = eski + [x for x in deger if x not in eski]
        else:
            mevcut[anahtar] = deger
    return mevcut


def main() -> int:
    hedef, kaynak = sys.argv[1], sys.argv[2]
    try:
        with open(hedef, encoding="utf-8") as f:
            mevcut = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Mevcut ayar dosyası okunamadı ({e}); dokunmadım.", file=sys.stderr)
        return 1
    with open(kaynak, encoding="utf-8") as f:
        yeni = json.load(f)
    with open(hedef, "w", encoding="utf-8") as f:
        json.dump(birlestir(mevcut, yeni), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
