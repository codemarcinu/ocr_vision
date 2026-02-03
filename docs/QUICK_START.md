# Szybki Start

> Zacznij korzystać ze Second Brain w 5 minut

---

## 1. Uruchomienie systemu

```bash
docker-compose up -d
```

Poczekaj na uruchomienie wszystkich usług.

---

## 2. Pobierz modele AI

```bash
# Na hoście (Ollama musi być zainstalowane)
ollama pull qwen2.5:7b           # Kategoryzacja + strukturyzacja
ollama pull deepseek-ocr          # OCR (lub qwen2.5vl:7b jako alternatywa)
ollama pull nomic-embed-text      # Embeddingi dla bazy wiedzy (RAG)
```

---

## 3. Uruchom migrację bazy danych

```bash
docker exec -it pantry-api alembic upgrade head
```

---

## 4. Sprawdź czy działa

Otwórz w przeglądarce: http://localhost:8000/health

Powinieneś zobaczyć:
```json
{
  "status": "healthy",
  "ollama_available": true,
  "ocr_model_loaded": true,
  "classifier_model_loaded": true
}
```

---

## 5. Połącz się z Telegram

1. Otwórz Telegram
2. Znajdź swojego bota (nazwa od administratora)
3. Kliknij **Start**
4. Wyślij `/help` aby zobaczyć dostępne komendy

---

## 6. Przetwórz pierwszy paragon

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

## 7. Zapytaj bazę wiedzy

Po przetworzeniu kilku paragonów lub artykułów, możesz zadawać pytania:

```
/ask ile wydałem w Biedronce?
/ask co wiem o mleku?
```

---

## 8. Podstawowe komendy

| Komenda | Opis |
|---------|------|
| `/recent` | Ostatnie paragony |
| `/stats` | Statystyki wydatków |
| `/pantry` | Spiżarnia |
| `/ask <pytanie>` | Zapytaj bazę wiedzy |
| `/feeds` | Kanały RSS |
| `/subscribe <URL>` | Dodaj kanał RSS |
| `/transcribe <URL>` | Transkrybuj YouTube |
| `/help` | Pomoc |

---

## Gotowe!

Więcej informacji: [USER_GUIDE.md](USER_GUIDE.md)
