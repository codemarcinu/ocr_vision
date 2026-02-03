# Szybki Start

> Zacznij korzystać ze Second Brain w 5 minut

---

## 1. Uruchomienie systemu

```bash
docker-compose up -d
```

Poczekaj około 2 minuty na uruchomienie wszystkich usług.

---

## 2. Sprawdź czy działa

Otwórz w przeglądarce: http://localhost:8000/health

Powinieneś zobaczyć:
```json
{
  "status": "healthy",
  "ollama": "connected",
  "database": "connected"
}
```

---

## 3. Połącz się z Telegram

1. Otwórz Telegram
2. Znajdź swojego bota (nazwa od administratora)
3. Kliknij **Start**
4. Wyślij `/help` aby zobaczyć dostępne komendy

---

## 4. Przetwórz pierwszy paragon

### Przez Telegram:
1. Zrób zdjęcie paragonu
2. Wyślij zdjęcie do bota
3. Poczekaj na odpowiedź (1-2 minuty)
4. Zatwierdź jeśli wszystko OK

### Przez folder:
1. Skopiuj zdjęcie do `paragony/inbox/`
2. System przetworzy automatycznie
3. Wynik w `vault/paragony/`

---

## 5. Podstawowe komendy

| Komenda | Opis |
|---------|------|
| `/recent` | Ostatnie paragony |
| `/stats` | Statystyki |
| `/pantry` | Spiżarnia |
| `/help` | Pomoc |

---

## Gotowe!

Więcej informacji: [USER_GUIDE.md](USER_GUIDE.md)
