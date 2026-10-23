#!/usr/bin/env python3
"""Orkestra: docs/TASKS.md'deki görevleri yerel Qwen ile tek tek uygular.

Kullanım (proje klasöründe):
  orkestra            bekleyen görevleri sırayla çalıştırır, biri başarısız olunca durur
  orkestra tek        yalnızca sıradaki görevi çalıştırır
  orkestra durum      görev listesini gösterir
  orkestra kontrol    kontrolleri (lint/test) şu anki koda karşı çalıştırır
  orkestra devam      NEEDS ile duran görevi, istenen komutlar çalıştırıldıktan sonra sürdürür

Her görev için:
  1. Qwen Code yeni bir oturumda, yalnızca o görevin metni ve ilgili skill'lerle çalışır.
  2. Kontroller (lint/test) ağsız, ev klasörünü görmeyen bir bubblewrap kutusunda çalışır.
  3. Geçerse commit atılır; geçmezse hata özeti Qwen'e verilip yeniden denenir.
  4. Deneme hakkı biterse değişiklikler bir yama dosyasına kaydedilip geri alınır.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

KALIP = Path(__file__).resolve().parent
RAPOR_SEMASI = KALIP / "rapor-semasi.json"
QWEN_AYAR = Path.home() / ".qwen" / "settings.json"
VENV_KOK = Path.home() / ".cache" / "qwen-kalip" / "venv"

# Qwen'in yazmaması gereken, kontrollerin de değiştirememesi gereken yollar
KORUNAN = [".git", ".qwen", ".kalip", "AGENTS.md", "CLAUDE.md", "GEMINI.md",
           "docs/TASKS.md", "docs/STATUS.md", "pyproject.toml"]

VARSAYILAN_SKILLS = {
    "kod": ["*-code", "*-test"],
    "test": ["*-test"],
    "dokuman": [],
    "duzeltme": ["fix-failing-checks"],
}

PYTHON_OTO_DUZELTME = "ruff format --no-cache --quiet . ; ruff check --no-cache --fix --quiet . ; true"

GEREKEN_GUVENLIK = ["executionSandbox", '"monitor"', '"run_shell_command"', "Edit(.git/**)",
                    "Edit(docs/TASKS.md)", "Edit(pyproject.toml)"]


# ----------------------------------------------------------------------------- çıktı

def renk(kod: str, metin: str) -> str:
    return f"\033[{kod}m{metin}\033[0m" if sys.stdout.isatty() else metin


def bilgi(metin: str) -> None:
    print(metin, flush=True)


def basari(metin: str) -> None:
    print(renk("32", "✔ " + metin), flush=True)


def uyari(metin: str) -> None:
    print(renk("33", "! " + metin), flush=True)


def hata(metin: str) -> None:
    print(renk("31", "✘ " + metin), file=sys.stderr, flush=True)


def sure_yaz(saniye: float) -> str:
    saniye = int(saniye)
    return f"{saniye // 60}dk {saniye % 60:02d}sn" if saniye >= 60 else f"{saniye}sn"


class Dur(Exception):
    """Kullanıcıya gösterilecek bir sebeple çalışmayı durdurur."""


# ----------------------------------------------------------------------------- git

def git(proje: Path, *args: str, kontrol: bool = True) -> str:
    sonuc = subprocess.run(["git", "-C", str(proje), *args], capture_output=True, text=True)
    if kontrol and sonuc.returncode != 0:
        raise Dur(f"git {' '.join(args)} başarısız:\n{sonuc.stderr.strip()}")
    return sonuc.stdout


def degisen_dosyalar(proje: Path) -> list[str]:
    cikti = git(proje, "status", "--porcelain", "-uall", "-z")
    dosyalar = []
    parcalar = cikti.split("\0")
    i = 0
    while i < len(parcalar):
        kayit = parcalar[i]
        if not kayit:
            i += 1
            continue
        durum, yol = kayit[:2], kayit[3:]
        dosyalar.append(yol)
        if "R" in durum or "C" in durum:  # yeniden adlandırma: bir sonraki parça eski ad
            i += 1
        i += 1
    return dosyalar


def calisma_imzasi(proje: Path) -> str:
    """Commit edilmemiş dosyaların içerik özeti (bir adımın dosya değiştirip değiştirmediğini anlamak için)."""
    h = hashlib.sha256()
    for d in sorted(degisen_dosyalar(proje)):
        h.update(d.encode())
        yol = proje / d
        if yol.is_file():
            h.update(yol.read_bytes())
    return h.hexdigest()


def git_ici_imza(proje: Path) -> str:
    """git'in kendi başına komut çalıştırabildiği dosyaların özeti (.git/config, hooks)."""
    gitdir = Path(git(proje, "rev-parse", "--absolute-git-dir").strip())
    h = hashlib.sha256()
    for yol in sorted([gitdir / "config", *(gitdir / "hooks").glob("*")]):
        if yol.is_file():
            h.update(str(yol).encode())
            h.update(yol.read_bytes())
    return h.hexdigest()


def korunanlari_geri_al(proje: Path, kaynak: str) -> None:
    bozulan = [d for d in degisen_dosyalar(proje)
               if any(d == k or d.startswith(k + "/") for k in KORUNAN)
               and not d.startswith(".kalip/calisma/")]
    if not bozulan:
        return
    uyari(f"{kaynak} korunan dosyaları değiştirdi, geri alınıyor: {', '.join(bozulan)}")
    for d in bozulan:
        izli = subprocess.run(["git", "-C", str(proje), "ls-files", "--error-unmatch", d],
                              capture_output=True).returncode == 0
        if izli:
            git(proje, "checkout", "--", d)
        else:
            (proje / d).unlink(missing_ok=True)


# ----------------------------------------------------------------------------- görevler

@dataclass
class Gorev:
    kimlik: str
    baslik: str
    baslik_satiri: int
    durum: str = "bekliyor"
    durum_satiri: int | None = None
    tip: str = "kod"
    dosyalar: list[str] = field(default_factory=list)
    gorev: str = ""
    kabul: list[str] = field(default_factory=list)


BASLIK = re.compile(r"^##\s+(T\d+)\s*[:.-]\s*(.+?)\s*$", re.I)
ALAN = re.compile(r"^(durum|tip|dosyalar|gorev|görev|kabul)\s*:\s*(.*)$", re.I)
DURUMLAR = {"bekliyor": "bekliyor", "tamam": "tamam", "basarisiz": "basarisiz",
            "başarısız": "basarisiz", "atla": "atla", "atlandi": "atla", "atlandı": "atla"}


def gorevleri_oku(yol: Path) -> list[Gorev]:
    metin = yol.read_text(encoding="utf-8")
    # HTML yorumlarını (şablondaki örnek dahil) satır numaralarını koruyarak sil
    temiz = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group().count("\n"), metin, flags=re.S)
    gorevler: list[Gorev] = []
    g: Gorev | None = None
    anahtar = None
    for no, satir in enumerate(temiz.splitlines()):
        b = BASLIK.match(satir)
        if b:
            g = Gorev(kimlik=b.group(1).upper(), baslik=b.group(2), baslik_satiri=no)
            gorevler.append(g)
            anahtar = None
            continue
        if g is None:
            continue
        a = ALAN.match(satir.strip())
        if a:
            anahtar = a.group(1).lower().replace("ö", "o")
            deger = a.group(2).strip()
            if anahtar == "durum":
                g.durum = DURUMLAR.get(deger.lower(), deger.lower())
                g.durum_satiri = no
            elif anahtar == "tip":
                g.tip = deger.lower().replace("ö", "o").replace("dokümantasyon", "dokuman")
            elif anahtar == "dosyalar":
                g.dosyalar += [d.strip() for d in deger.split(",") if d.strip()]
            elif anahtar == "gorev":
                g.gorev = deger
            elif anahtar == "kabul" and deger:
                g.kabul.append(deger)
            continue
        icerik = satir.strip()
        if not icerik:
            continue
        madde = re.match(r"^[-*]\s+(.*)$", icerik)
        if anahtar == "kabul" and madde:
            g.kabul.append(madde.group(1))
        elif anahtar == "dosyalar" and madde:
            g.dosyalar.append(madde.group(1).strip())
        elif anahtar == "gorev":
            g.gorev += "\n" + icerik
    return gorevler


def gorev_durumu_yaz(yol: Path, g: Gorev, durum: str) -> None:
    satirlar = yol.read_text(encoding="utf-8").splitlines(keepends=True)
    yeni = f"durum: {durum}\n"
    if g.durum_satiri is not None:
        satirlar[g.durum_satiri] = yeni
    else:
        satirlar.insert(g.baslik_satiri + 1, yeni)
    yol.write_text("".join(satirlar), encoding="utf-8")
    g.durum = durum


def gorev_hatalari(g: Gorev) -> list[str]:
    sorunlar = []
    if not g.gorev.strip():
        sorunlar.append("'gorev:' boş")
    if not g.kabul:
        sorunlar.append("'kabul:' maddesi yok")
    if g.tip not in ("kod", "test", "dokuman"):
        sorunlar.append(f"bilinmeyen tip '{g.tip}' (kod | test | dokuman)")
    return sorunlar


def status_satiri(proje: Path, g: Gorev, sonuc: str, deneme: int, not_: str) -> None:
    yol = proje / "docs" / "STATUS.md"
    if not yol.exists():
        yol.write_text("| Tarih | Görev | Sonuç | Deneme | Not |\n|---|---|---|---|---|\n",
                       encoding="utf-8")
    metin = yol.read_text(encoding="utf-8")
    if not metin.endswith("\n"):
        metin += "\n"
    not_ = not_.replace("|", "/").replace("\n", " ")
    metin += f"| {datetime.now():%Y-%m-%d %H:%M} | {g.kimlik} {g.baslik} | {sonuc} | {deneme} | {not_} |\n"
    yol.write_text(metin, encoding="utf-8")


# ----------------------------------------------------------------------------- ayarlar

def ayarlari_oku(proje: Path) -> dict:
    yol = proje / ".kalip" / "kontroller.toml"
    ayar = tomllib.loads(yol.read_text(encoding="utf-8")) if yol.exists() else {}
    ayar.setdefault("kontroller", {})
    ayar.setdefault("skills", {})
    for tip, desen in VARSAYILAN_SKILLS.items():
        ayar["skills"].setdefault(tip, desen)
    hazirlik = ayar.setdefault("hazirlik", {})
    hazirlik.setdefault("tur", "python-venv" if (proje / "pyproject.toml").exists() else "yok")
    if "oto_duzeltme" not in ayar and hazirlik["tur"] == "python-venv":
        ayar["oto_duzeltme"] = {"komut": PYTHON_OTO_DUZELTME}
    ork = ayar.setdefault("orkestra", {})
    ork.setdefault("max_deneme", 3)
    ork.setdefault("qwen_sure", "45m")
    ork.setdefault("max_arac", 80)
    ork.setdefault("kontrol_sure_sn", 600)
    return ayar


def guvenlik_on_kontrolu() -> None:
    if not shutil.which("bwrap"):
        raise Dur("bubblewrap yok. Kur:  sudo pacman -S bubblewrap")
    if not shutil.which("qwen"):
        raise Dur("qwen komutu bulunamadı (Qwen Code kurulu mu?)")
    try:
        ayar = QWEN_AYAR.read_text(encoding="utf-8")
    except FileNotFoundError:
        ayar = ""
    eksik = [k for k in GEREKEN_GUVENLIK if k not in ayar]
    if eksik:
        raise Dur("~/.qwen/settings.json içinde güvenlik ayarları eksik "
                  f"({', '.join(eksik)}).\nKalıp klasöründe tekrar çalıştır:  fish kur.fish")


def sunucu_saglik_adresi() -> str:
    try:
        ayar = json.loads(QWEN_AYAR.read_text(encoding="utf-8"))
        url = ayar["modelProviders"]["openai"][0]["baseUrl"]
    except (OSError, KeyError, IndexError, json.JSONDecodeError):
        url = "http://127.0.0.1:8091/v1"
    return re.sub(r"/v1/?$", "", url) + "/health"


def sunucu_hazir_mi() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(sunucu_saglik_adresi(), timeout=3) as yanit:
            return b"ok" in yanit.read()
    except OSError:
        return False


# ----------------------------------------------------------------------------- skills

def skill_metni(proje: Path, adlar_desenleri: list[str]) -> str:
    kok = proje / ".qwen" / "skills"
    if not kok.is_dir():
        return ""
    secilen: list[Path] = []
    for desen in adlar_desenleri:
        for d in sorted(kok.glob(desen)):
            if (d / "SKILL.md").is_file() and d not in secilen:
                secilen.append(d)
    parcalar = []
    for d in secilen:
        govde = (d / "SKILL.md").read_text(encoding="utf-8")
        govde = re.sub(r"^---\n.*?\n---\n", "", govde, count=1, flags=re.S).strip()
        parcalar.append(f"### Skill: {d.name}\n{govde}")
    return "\n\n".join(parcalar)


# ----------------------------------------------------------------------------- prompt

def gorev_bolumu(g: Gorev, proje: Path) -> str:
    def isaret(d: str) -> str:
        return "exists" if (proje / d).is_file() else "new, create it"

    dosyalar = ("\n".join(f"- {d} ({isaret(d)})" for d in g.dosyalar)
                or "- (not specified; decide from docs/ARCHITECTURE.md)")
    kabul = "\n".join(f"- {k}" for k in g.kabul)
    return (f"## Task {g.kimlik}: {g.baslik}\n{g.gorev.strip()}\n\n"
            f"## Files\n{dosyalar}\n\n"
            f"## Acceptance criteria\n{kabul}\n")


CALISMA_KURALLARI = """\
## How to work
1. Read the listed files marked (exists); files marked (new) do not exist yet, do not try to read them.
   Read docs/ARCHITECTURE.md only if you must create a file that is not listed.
2. Make the change. Stay inside the listed files.
   If another file must change, change it only if unavoidable and say so in "doubts".
3. You cannot run code, tests or linters. They run automatically when you finish.
   So re-read every file you changed once and check imports, names, indentation and syntax by eye.
4. If the task needs a shell command (install a package, a migration, a git operation), do not look for a workaround:
   put the exact command in "needs" and finish.
5. Finish by calling the structured_output tool:
   changed: files you created or edited
   done: one or two sentences
   needs: exact shell commands the user must run (empty list if none)
   doubts: anything uncertain, or "none"
"""


def ilk_prompt(g: Gorev, proje: Path, skills: str) -> str:
    p = gorev_bolumu(g, proje) + "\n" + CALISMA_KURALLARI
    if skills:
        p += "\n## Conventions to follow\n" + skills + "\n"
    return p


def duzeltme_promptu(g: Gorev, proje: Path, deneme: int, kontrol_ozeti: str, degisenler: list[str],
                     skills: str) -> str:
    liste = "\n".join(f"- {d}" for d in degisenler) or "- (none)"
    return (f"# Fix attempt {deneme} for task {g.kimlik}\n"
            "A previous attempt at this task is already on disk, but the automatic checks failed.\n"
            "Read the failing output, open the files it points to, and fix the cause.\n"
            "Import order and code formatting are fixed automatically; do not spend effort on them.\n\n"
            f"## Check output\n```\n{kontrol_ozeti}\n```\n\n"
            f"## Files changed so far\n{liste}\n\n"
            + gorev_bolumu(g, proje) + "\n" + CALISMA_KURALLARI
            + ("\n## Conventions to follow\n" + skills + "\n" if skills else ""))


BOS_DEGERLER = {"", "none", "yok", "-", "n/a", "na", "null", "nothing", "no", "[]", "['none']", '["none"]'}


def liste_temizle(deger) -> list[str]:
    """Modelin ["none"], "none", "[]" gibi 'boş' cevaplarını gerçekten boş listeye çevirir."""
    if deger is None:
        return []
    ogeler = deger if isinstance(deger, list) else [deger]
    temiz = []
    for o in ogeler:
        s = str(o).strip().strip("`").strip()
        if s.lower() not in BOS_DEGERLER:
            temiz.append(s)
    return temiz


# ----------------------------------------------------------------------------- qwen

@dataclass
class QwenSonucu:
    tamam: bool
    rapor: dict
    hata: str = ""
    sure: float = 0.0
    arac_sayisi: int = 0


def _yol_kisalt(proje: Path, yol: str) -> str:
    try:
        return str(Path(yol).resolve().relative_to(proje))
    except (ValueError, OSError):
        return yol


def _metin_raporu(metin: str) -> dict:
    """structured_output çağrılmadıysa düz metinden CHANGED/DONE/NEEDS/DOUBTS çıkar."""
    rapor: dict = {"changed": [], "done": "", "needs": [], "doubts": ""}
    anahtar = None
    for satir in metin.splitlines():
        m = re.match(r"^\s*\**(CHANGED|DONE|NEEDS|DOUBTS)\**\s*:\s*(.*)$", satir, re.I)
        if m:
            anahtar = m.group(1).lower()
            deger = m.group(2).strip()
        elif anahtar:
            deger = satir.strip()
        else:
            continue
        if not deger:
            continue
        if anahtar in ("changed", "needs"):
            if deger.lower() not in ("none", "-", "yok"):
                rapor[anahtar] += [x.strip(" -`") for x in deger.split(",") if x.strip(" -`")]
        else:
            rapor[anahtar] = (rapor[anahtar] + " " + deger).strip()
    rapor["done"] = rapor["done"] or metin.strip()[-300:]
    return rapor


def qwen_calistir(proje: Path, prompt: str, ayar: dict, log_yolu: Path) -> QwenSonucu:
    ork = ayar["orkestra"]
    komut = ["qwen", prompt,
             "--approval-mode", "auto-edit",
             "--output-format", "stream-json",
             "--json-schema", f"@{RAPOR_SEMASI}",
             "--max-wall-time", str(ork["qwen_sure"]),
             "--max-tool-calls", str(ork["max_arac"])]
    imza_once = git_ici_imza(proje)
    baslangic = time.monotonic()
    sonuc = QwenSonucu(tamam=False, rapor={})
    son_metin = ""
    log_yolu.parent.mkdir(parents=True, exist_ok=True)
    with open(log_yolu, "w", encoding="utf-8") as log:
        log.write(json.dumps({"prompt": prompt}, ensure_ascii=False) + "\n")
        surec = subprocess.Popen(komut, cwd=proje, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, start_new_session=True)
        try:
            assert surec.stdout is not None
            for satir in surec.stdout:
                log.write(satir)
                try:
                    olay = json.loads(satir)
                except json.JSONDecodeError:
                    continue
                gecen = sure_yaz(time.monotonic() - baslangic)
                if olay.get("type") == "assistant":
                    for parca in olay.get("message", {}).get("content", []):
                        if parca.get("type") == "tool_use":
                            sonuc.arac_sayisi += 1
                            girdi = parca.get("input", {})
                            hedef = girdi.get("file_path") or girdi.get("path") or girdi.get("pattern") or ""
                            if parca.get("name") != "structured_output":
                                bilgi(renk("2", f"   [{gecen}] {parca.get('name')} {_yol_kisalt(proje, hedef)}"))
                        elif parca.get("type") == "text" and parca.get("text", "").strip():
                            son_metin = parca["text"]
                elif olay.get("type") == "result":
                    if olay.get("structured_result"):
                        sonuc.rapor = olay["structured_result"]
                        sonuc.tamam = True
                    elif olay.get("subtype") == "success":
                        sonuc.rapor = _metin_raporu(olay.get("result") or son_metin)
                        sonuc.tamam = True
                    else:
                        sonuc.hata = (olay.get("error") or {}).get("message", olay.get("subtype", ""))
                        if son_metin and "structured_output" in sonuc.hata:
                            sonuc.rapor = _metin_raporu(son_metin)
                            sonuc.tamam = True
            surec.wait()
        except KeyboardInterrupt:
            os.killpg(surec.pid, signal.SIGTERM)
            surec.wait()
            raise
    sonuc.sure = time.monotonic() - baslangic
    if not sonuc.tamam and not sonuc.hata:
        sonuc.hata = f"qwen çıkış kodu {surec.returncode} (ayrıntı: {log_yolu})"
    if surec.returncode == 55:
        sonuc.hata = "süre ya da araç çağrısı sınırı aşıldı"
        sonuc.tamam = False

    if git_ici_imza(proje) != imza_once:
        raise Dur("GÜVENLİK: Qwen oturumu sırasında .git/config ya da .git/hooks değişti!\n"
                  "Hiçbir git komutu çalıştırmadan önce incele. Çalışma durduruldu.")
    korunanlari_geri_al(proje, "Qwen")
    return sonuc


# ----------------------------------------------------------------------------- kontroller

def venv_hazirla(proje: Path) -> Path:
    py = proje / "pyproject.toml"
    bagimliliklar: list[str] = []
    if py.exists():
        bagimliliklar = tomllib.loads(py.read_text(encoding="utf-8")).get("project", {}).get("dependencies", [])
    kimlik = hashlib.sha1(str(proje).encode()).hexdigest()[:8]
    venv = VENV_KOK / f"{proje.name}-{kimlik}"
    imza = hashlib.sha1(json.dumps([sorted(bagimliliklar), sys.version]).encode()).hexdigest()
    imza_dosyasi = venv / ".kalip-imza"
    if imza_dosyasi.exists() and imza_dosyasi.read_text() == imza:
        return venv
    bilgi("Test ortamı hazırlanıyor (pytest, ruff"
          + (", " + ", ".join(bagimliliklar) if bagimliliklar else "") + "); internet gerekir...")
    shutil.rmtree(venv, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    kurulum = subprocess.run([str(venv / "bin" / "pip"), "install", "-q", "--disable-pip-version-check",
                              "pytest", "ruff", *bagimliliklar])
    if kurulum.returncode != 0:
        raise Dur("Test ortamı kurulamadı (pip hatası, yukarıya bak).")
    imza_dosyasi.write_text(imza)
    basari("Test ortamı hazır: " + str(venv))
    return venv


def kutu_komutu(proje: Path, venv: Path | None, komut: str) -> list[str]:
    ev = Path.home()
    arg = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
    for gizli in ["/tmp", "/run", "/mnt", "/media", str(ev)]:
        if Path(gizli).is_dir():
            arg += ["--tmpfs", gizli]
    arg += ["--bind", str(proje), str(proje)]
    for k in KORUNAN:
        if (proje / k).exists():
            arg += ["--ro-bind", str(proje / k), str(proje / k)]
    yol = "/usr/local/bin:/usr/bin:/bin"
    if venv:
        arg += ["--ro-bind", str(venv), str(venv)]
        yol = f"{venv / 'bin'}:{yol}"
    arg += ["--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
            "--setenv", "PATH", yol, "--setenv", "HOME", str(ev), "--setenv", "LANG", "C.UTF-8",
            "--setenv", "TERM", "dumb", "--setenv", "NO_COLOR", "1",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--chdir", str(proje), "--", "bash", "-c", komut]
    return arg


def ozetle(cikti: str, en_fazla_satir: int = 80, en_fazla_karakter: int = 6000) -> str:
    satirlar = [s for s in cikti.splitlines() if s.strip()]
    if len(satirlar) > en_fazla_satir:
        satirlar = satirlar[:20] + ["... (kısaltıldı) ..."] + satirlar[-(en_fazla_satir - 21):]
    metin = "\n".join(satirlar)
    if len(metin) > en_fazla_karakter:
        metin = metin[:2000] + "\n... (kısaltıldı) ...\n" + metin[-(en_fazla_karakter - 2100):]
    return metin


@dataclass
class KontrolSonucu:
    gecti: bool
    ozet: str
    satirlar: list[str]


def kontrolleri_calistir(proje: Path, ayar: dict, log_yolu: Path | None = None) -> KontrolSonucu:
    kontroller = ayar["kontroller"]
    if not kontroller:
        uyari("Bu projede kontrol tanımlı değil (.kalip/kontroller.toml); görev kontrolsüz kabul edilecek.")
        return KontrolSonucu(True, "", ["kontrol yok"])
    venv = venv_hazirla(proje) if ayar["hazirlik"]["tur"] == "python-venv" else None
    sure_siniri = int(ayar["orkestra"]["kontrol_sure_sn"])
    satirlar, basarisiz_ozet, tam_log = [], [], []

    # Mekanik sorunları (import sırası, biçim) modele hiç göstermeden düzelt: deneme hakkı yemesin
    oto = ayar.get("oto_duzeltme", {}).get("komut", "")
    if oto:
        once = calisma_imzasi(proje)
        s = subprocess.run(kutu_komutu(proje, venv, oto), capture_output=True, text=True, timeout=sure_siniri)
        tam_log.append(f"===== otomatik düzeltme: {oto}  (çıkış {s.returncode})\n{s.stdout}{s.stderr}")
        if calisma_imzasi(proje) != once:
            bilgi(renk("2", "   ~ otomatik düzeltme uygulandı (biçim/import sırası)"))

    for ad, komut in kontroller.items():
        bas = time.monotonic()
        try:
            s = subprocess.run(kutu_komutu(proje, venv, komut), capture_output=True, text=True,
                               timeout=sure_siniri)
            kod, cikti = s.returncode, (s.stdout + s.stderr)
        except subprocess.TimeoutExpired as e:
            kod = -1
            cikti = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""))
            cikti += f"\n[zaman aşımı: {sure_siniri} sn]"
        gecen = sure_yaz(time.monotonic() - bas)
        tam_log.append(f"===== {ad}: {komut}  (çıkış {kod}, {gecen})\n{cikti}")
        if kod == 0:
            bilgi(renk("32", f"   ✔ {ad}") + renk("2", f" ({gecen})"))
            satirlar.append(f"{ad} geçti")
        else:
            bilgi(renk("31", f"   ✘ {ad}") + renk("2", f" ({gecen}, çıkış {kod})"))
            satirlar.append(f"{ad} başarısız")
            basarisiz_ozet.append(f"$ {komut}\n{ozetle(cikti)}")
            break  # ilk başarısız kontrolde dur: model tek bir soruna odaklansın
    if log_yolu:
        log_yolu.parent.mkdir(parents=True, exist_ok=True)
        log_yolu.write_text("\n".join(tam_log), encoding="utf-8")
    korunanlari_geri_al(proje, "Kontroller")
    return KontrolSonucu(not basarisiz_ozet, "\n\n".join(basarisiz_ozet), satirlar)


# ----------------------------------------------------------------------------- akış

class Orkestra:
    def __init__(self, proje: Path):
        self.proje = proje
        self.tasks = proje / "docs" / "TASKS.md"
        self.calisma = proje / ".kalip" / "calisma"
        self.yarim = self.calisma / "yarim.json"
        self.ayar = ayarlari_oku(proje)

    # --- yardımcılar
    def gorevler(self) -> list[Gorev]:
        if not self.tasks.exists():
            raise Dur("docs/TASKS.md yok. Bu bir kalıp projesi mi?")
        return gorevleri_oku(self.tasks)

    def skills(self, tip: str) -> str:
        return skill_metni(self.proje, list(self.ayar["skills"].get(tip, [])))

    def temiz_mi(self) -> bool:
        return not degisen_dosyalar(self.proje)

    def commit(self, mesaj: str, govde: str = "") -> None:
        git(self.proje, "add", "-A")
        argumanlar = ["commit", "-q", "-m", mesaj] + (["-m", govde] if govde else [])
        sonuc = subprocess.run(["git", "-C", str(self.proje), *argumanlar], capture_output=True, text=True)
        if sonuc.returncode != 0:
            raise Dur("Commit atılamadı. Git kimliğin ayarlı mı?\n"
                      "  git config --global user.name 'Adın'\n"
                      "  git config --global user.email 'e-postan'\n" + sonuc.stderr.strip())

    # --- komutlar
    def durum(self) -> None:
        gorevler = self.gorevler()
        if not gorevler:
            bilgi("docs/TASKS.md içinde görev yok (yorum içindeki örnek sayılmaz).")
            return
        simge = {"tamam": renk("32", "✔"), "basarisiz": renk("31", "✘"), "bekliyor": "·", "atla": "↷"}
        for g in gorevler:
            sorun = gorev_hatalari(g)
            ek = renk("33", "  ← " + "; ".join(sorun)) if sorun and g.durum == "bekliyor" else ""
            bilgi(f" {simge.get(g.durum, '?')} {g.kimlik:<4} {g.durum:<10} {g.tip:<8} {g.baslik}{ek}")
        if self.yarim.exists():
            uyari(f"Yarım kalan görev var: {json.loads(self.yarim.read_text())['gorev']}  →  orkestra devam")

    def kontrol(self) -> int:
        sonuc = kontrolleri_calistir(self.proje, self.ayar, self.calisma / "log" / "elle-kontrol.txt")
        if not sonuc.gecti:
            bilgi("\n" + sonuc.ozet)
        return 0 if sonuc.gecti else 1

    def calistir(self, tek: bool) -> int:
        if self.yarim.exists():
            raise Dur("Yarım kalmış bir görev var. Önce:  orkestra devam   "
                      f"(vazgeçmek için: git stash -u; rm {self.yarim})")
        if not self.temiz_mi():
            raise Dur("Commit edilmemiş değişiklikler var:\n  "
                      + "\n  ".join(degisen_dosyalar(self.proje)[:10])
                      + "\nÖnce commit at ya da kenara koy:  git add -A; and git commit -m 'kayıt'")
        islenen = 0
        while True:
            sirada = [g for g in self.gorevler() if g.durum not in ("tamam", "atla")]
            if not sirada:
                if islenen == 0:
                    bilgi("Bekleyen görev yok. Yeni görevleri docs/TASKS.md'ye 'durum: bekliyor' ile ekle.")
                else:
                    basari("Bekleyen görev kalmadı.")
                return 0
            g = sirada[0]
            if g.durum != "bekliyor":
                # Sonraki görevler çoğu zaman öncekine dayanır: sessizce atlamak yerine dur
                raise Dur(f"{g.kimlik} '{g.durum}' durumda; sıradaki görevler ona bağlı olabilir.\n"
                          "docs/TASKS.md içinde:\n"
                          f"  yeniden denemek için (görevi küçültüp/netleştirip):  durum: bekliyor\n"
                          f"  atlayıp devam etmek için:                            durum: atla\n"
                          "Değişikliği commit et, sonra tekrar: orkestra")
            sorun = gorev_hatalari(g)
            if sorun:
                raise Dur(f"{g.kimlik} eksik tanımlı: {'; '.join(sorun)}. docs/TASKS.md'yi düzelt.")
            sonuc = self.gorevi_yurut(g, ilk_deneme=1, qwen_atla=False)
            islenen += 1
            if sonuc != 0 or tek:
                return sonuc

    def devam(self) -> int:
        if not self.yarim.exists():
            raise Dur("Yarım kalmış görev yok.")
        bilgi_ = json.loads(self.yarim.read_text())
        g = next((x for x in self.gorevler() if x.kimlik == bilgi_["gorev"]), None)
        if g is None:
            raise Dur(f"{bilgi_['gorev']} artık docs/TASKS.md içinde yok.")
        self.yarim.unlink()
        sonuc = self.gorevi_yurut(g, ilk_deneme=bilgi_["deneme"], qwen_atla=True)
        if sonuc == 0:
            return self.calistir(tek=False)
        return sonuc

    def gorevi_yurut(self, g: Gorev, ilk_deneme: int, qwen_atla: bool) -> int:
        max_deneme = int(self.ayar["orkestra"]["max_deneme"])
        bilgi(renk("1", f"\n━━ {g.kimlik}: {g.baslik}") + renk("2", f"  (tip: {g.tip})"))
        toplam_bas = time.monotonic()
        kontrol: KontrolSonucu | None = None
        rapor: dict = {}
        deneme = ilk_deneme
        while deneme <= max_deneme:
            if not qwen_atla:
                if deneme == 1:
                    prompt = ilk_prompt(g, self.proje, self.skills(g.tip))
                    bilgi(f"── Deneme {deneme}/{max_deneme}: Qwen çalışıyor (her adım aşağıda görünür)")
                else:
                    assert kontrol is not None
                    skills = self.skills("duzeltme") + "\n\n" + self.skills(g.tip)
                    prompt = duzeltme_promptu(g, self.proje, deneme, kontrol.ozet,
                                              degisen_dosyalar(self.proje), skills.strip())
                    bilgi(f"── Deneme {deneme}/{max_deneme}: Qwen hatayı düzeltiyor")
                q = qwen_calistir(self.proje, prompt, self.ayar,
                                  self.calisma / "log" / f"{g.kimlik}-deneme{deneme}.jsonl")
                if not q.tamam:
                    uyari(f"Qwen oturumu düzgün bitmedi: {q.hata}")
                rapor = q.rapor or {}
                bilgi(renk("2", f"   Qwen bitti ({sure_yaz(q.sure)}, {q.arac_sayisi} araç çağrısı)"))
                if rapor.get("done"):
                    bilgi(f"   Rapor: {rapor['done']}")
                supheler = "; ".join(liste_temizle(rapor.get("doubts")))
                if supheler:
                    uyari(f"Şüpheler: {supheler}")

                ihtiyac = liste_temizle(rapor.get("needs"))
                if ihtiyac:
                    return self.ihtiyac_var(g, deneme, ihtiyac)
                if not degisen_dosyalar(self.proje):
                    return self.basarisiz(g, deneme, "Qwen hiçbir dosyayı değiştirmedi"
                                          + (f" (şüpheler: {supheler})" if supheler else ""),
                                          time.monotonic() - toplam_bas)
                disarida = sorted(set(degisen_dosyalar(self.proje)) - set(g.dosyalar)) if g.dosyalar else []
                if disarida:
                    uyari("Görevde listelenmeyen dosyalar da değişti: " + ", ".join(disarida))
            qwen_atla = False

            bilgi("── Kontroller (ağsız kutuda)")
            kontrol = kontrolleri_calistir(self.proje, self.ayar,
                                           self.calisma / "log" / f"{g.kimlik}-deneme{deneme}-kontrol.txt")
            if kontrol.gecti:
                return self.basarili(g, deneme, kontrol, time.monotonic() - toplam_bas)
            deneme += 1
        assert kontrol is not None
        return self.basarisiz(g, max_deneme, "; ".join(kontrol.satirlar), time.monotonic() - toplam_bas)

    # --- sonuçlar
    def basarili(self, g: Gorev, deneme: int, kontrol: KontrolSonucu, sure: float) -> int:
        dosyalar = degisen_dosyalar(self.proje)
        gorev_durumu_yaz(self.tasks, g, "tamam")
        status_satiri(self.proje, g, "tamam", deneme,
                      f"{sure_yaz(sure)}; {', '.join(kontrol.satirlar)}; {', '.join(dosyalar)}")
        self.commit(f"{g.kimlik}: {g.baslik}",
                    f"orkestra: {deneme}. denemede kontroller geçti ({sure_yaz(sure)})")
        basari(f"{g.kimlik} tamam ({deneme}. deneme, {sure_yaz(sure)}) ve commit atıldı.")
        return 0

    def basarisiz(self, g: Gorev, deneme: int, neden: str, sure: float) -> int:
        self.calisma.mkdir(parents=True, exist_ok=True)
        yama = self.calisma / f"{g.kimlik}-basarisiz-{datetime.now():%Y%m%d-%H%M%S}.patch"
        if degisen_dosyalar(self.proje):
            git(self.proje, "add", "-A")
            yama.write_text(git(self.proje, "diff", "--cached", "--binary"), encoding="utf-8")
            git(self.proje, "reset", "-q", "--hard")
        gorev_durumu_yaz(self.tasks, g, "basarisiz")
        status_satiri(self.proje, g, "başarısız", deneme, f"{neden}; yama: {yama.relative_to(self.proje)}")
        self.commit(f"{g.kimlik}: başarısız ({neden[:60]})")
        hata(f"{g.kimlik} başarısız: {neden}")
        bilgi(f"   Qwen'in son hali yamada: {yama.relative_to(self.proje)}\n"
              f"   İncelemek için:   git apply {yama.relative_to(self.proje)}\n"
              f"   Kontrol çıktıları: {(self.calisma / 'log').relative_to(self.proje)}/\n"
              "   Görevi küçültüp ya da netleştirip 'durum: bekliyor' yaparak yeniden deneyebilirsin.")
        return 1

    def ihtiyac_var(self, g: Gorev, deneme: int, komutlar: list[str]) -> int:
        self.calisma.mkdir(parents=True, exist_ok=True)
        self.yarim.write_text(json.dumps({"gorev": g.kimlik, "deneme": deneme}))
        uyari(f"{g.kimlik} için Qwen senin çalıştırman gereken komutlar istiyor:")
        for k in komutlar:
            bilgi("     " + renk("1", str(k)))
        bilgi("\n   Bu komutlar SENİN yetkilerinle, kutunun DIŞINDA çalışır: önce oku, anladıysan çalıştır.\n"
              "   Python paketi gerekiyorsa pip install yerine pyproject.toml'daki 'dependencies'\n"
              "   listesine ekle; orkestra test ortamına kendisi kurar.\n"
              "   Qwen'in değişiklikleri duruyor (git status). Hazır olunca:  orkestra devam\n"
              "   Vazgeçmek için:  git stash -u; and rm .kalip/calisma/yarim.json")
        return 2


# ----------------------------------------------------------------------------- giriş

def proje_kok() -> Path:
    s = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if s.returncode != 0:
        raise Dur("Bir git projesinin içinde değilsin.")
    return Path(s.stdout.strip())


def main(argv: list[str]) -> int:
    komut = argv[0] if argv else "calistir"
    if komut in ("-h", "--help", "yardim"):
        bilgi(__doc__ or "")
        return 0
    try:
        o = Orkestra(proje_kok())
        if komut == "durum":
            o.durum()
            return 0
        guvenlik_on_kontrolu()
        if komut == "kontrol":
            return o.kontrol()
        if not sunucu_hazir_mi():
            raise Dur(f"Model sunucusu hazır değil ({sunucu_saglik_adresi()}). Başlat:  qwen-sunucu")
        if komut in ("calistir", "çalıştır"):
            return o.calistir(tek=False)
        if komut == "tek":
            return o.calistir(tek=True)
        if komut == "devam":
            return o.devam()
        hata(f"Bilinmeyen komut: {komut}")
        bilgi(__doc__ or "")
        return 1
    except Dur as e:
        hata(str(e))
        return 1
    except KeyboardInterrupt:
        print()
        uyari("Durduruldu. Qwen'in yarım değişiklikleri duruyor olabilir:\n"
              "   bakmak için:        git status\n"
              "   kenara koymak için: git stash -u")
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
