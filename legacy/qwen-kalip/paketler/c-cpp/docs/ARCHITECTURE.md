# Architecture: {{PROJE_ADI}}

<!-- Bu dosyayı projeye başlarken doldur (ya da Claude/GPT'ye doldurt).
     Kısa tut: model bunu sık okuyacak. Her bölüm birkaç satırı geçmesin. -->

## Goal
<!-- 2-3 cümle: program ne yapıyor, kim kullanıyor -->

## Folder layout
```
include/    public headers (.h / .hpp)
src/        sources; built as library "core" plus the app executable
tests/      one test executable per file, registered in CMakeLists.txt with add_test
docs/       project docs (this file, tasks, status)
```

## Components
<!-- Her modül için tek satır: dosya: sorumluluğu -->

## Decisions
<!-- Önemli kararlar ve nedeni, tek satır. Örn: "C only, no C++; no external libraries" -->

## Out of scope
<!-- Şimdilik bilerek yapılmayanlar -->
