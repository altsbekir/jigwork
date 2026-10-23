# Tasks: {{PROJE_ADI}}

<!--
Görevleri bu yorumun ALTINA yaz (ya da Claude/GPT'ye yazdır). Kurallar:
- Her görev tek, küçük, tek başına test edilebilir bir iş olsun (ideal: 1-3 dosya).
- "dosyalar": modelin okuyacağı/değiştireceği dosyalar.
- "kabul": test edilebilir, ölçülebilir maddeler.
- "tip": kod | test | dokuman  (orkestratör hangi skill'leri ekleyeceğine buna göre karar verir)
- "durum": bekliyor | tamam | basarisiz  (orkestratör günceller, sen "bekliyor" yaz)

Örnek:

## T1: Add a function that parses a todo line
durum: bekliyor
tip: kod
dosyalar: src/todo/parser.py, tests/test_parser.py
gorev: Write parse_line(text) that turns "[x] buy milk" into a Todo(done=True, title="buy milk").
kabul:
- "[ ] a" gives done=False, title="a"
- "[x] a" gives done=True
- any other format raises ValueError
- tests for all three cases exist and pass
-->
