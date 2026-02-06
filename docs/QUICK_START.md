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
ollama pull qwen2.5vl:7b         # Vision OCR + fallback
ollama pull nomic-embed-text     # Embeddingi dla bazy wiedzy (RAG)

# Opcjonalnie (dla polskich treści - Chat AI, podsumowania)
ollama pull SpeakLeash/bielik-11b-v3.0-instruct:Q5_K_M
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

## 5. Otwórz interfejs

- **Desktop:** http://localhost:8000/app/ - pełny Web UI
- **Telefon:** http://localhost:8000/m/ - Mobile PWA (można zainstalować)
- **API docs:** http://localhost:8000/docs - Swagger UI

---

## 6. Przetwórz pierwszy paragon

### Przez Web UI:
1. Otwórz dashboard (`/app/`)
2. Kliknij "Dodaj paragon"
3. Wybierz zdjęcie lub PDF
4. Poczekaj na przetworzenie (30s-2min)
5. Zatwierdź jeśli wymagana weryfikacja

### Przez folder:
1. Skopiuj zdjęcie do `paragony/inbox/`
2. System przetworzy automatycznie
3. Wynik w `vault/paragony/`

---

## 7. Zapytaj bazę wiedzy

Po przetworzeniu kilku paragonów lub artykułów, otwórz Chat (`/app/chat`) i zadaj pytanie:

```
"Ile wydałem w Biedronce?"
"Co wiem o mleku?"
```

---

## 8. Chat AI i Agent - po prostu pisz!

W Chat możesz nie tylko pytać, ale też wykonywać akcje:

```
"Ile wydałem w Biedronce?"
→ Odpowiedź z danych

"Zanotuj: spotkanie jutro o 10"
→ Tworzy notatkę automatycznie

"Co mam w lodówce?"
→ Pokazuje spiżarnię
```

---

## Gotowe!

Więcej informacji: [USER_GUIDE.md](USER_GUIDE.md)
