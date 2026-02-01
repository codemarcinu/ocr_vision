# 📄 Brief Techniczny: Smart Pantry Tracker

## 1. O produkcie

**Nazwa produktu:** Smart Pantry Tracker

**Hasło przewodnie:** Automatyczne zarządzanie domową spiżarnią przez OCR paragonów – koniec z marnowaniem jedzenia i chaotycznymi zakupami.

**Jaki problem rozwiązuje:**
Brak kontroli nad zakupami spożywczymi prowadzi do marnowania żywności i chaotycznego planowania. Paragony z aplikacji sklepowych (Biedronka, Lidl, Kaufland) są zapisane jako pliki PNG/PDF, ale nie ma z nich żadnej strukturalnej wiedzy o tym co faktycznie znajduje się w domu, co się kończy i co trzeba kupić.

**Dla kogo jest przeznaczony:**
Osoby zarządzające domowymi zakupami spożywczymi, które:
- Regularnie kupują produkty (codziennie lub co kilka dni)
- Otrzymują cyfrowe paragony z aplikacji sklepowych
- Chcą ograniczyć marnowanie żywności
- Potrzebują lepszego planowania zakupów
- Są średnio-zaawansowane technicznie (ogarniają Dockera, n8n, Obsidian)

---

## 2. Historyjki użytkownika

**P0 (Must Have w MVP):**

1. **Jako użytkownik, chcę wrzucić plik paragonu do folderu, żeby system automatycznie wyekstrahował listę produktów**
   - Priorytet: P0

2. **Jako użytkownik, chcę zobaczyć przetworzony paragon jako plik markdown w Obsidian, żeby mieć historię moich zakupów**
   - Priorytet: P0

3. **Jako użytkownik, chcę mieć zagregowany widok wszystkich produktów w jednym pliku (spiżarnia.md), żeby szybko sprawdzić co mam w domu**
   - Priorytet: P0

4. **Jako użytkownik, chcę odznaczać produkty które zużyłem poprzez checkboxy w Obsidian, żeby wiedzieć co mi zostało**
   - Priorytet: P0

5. **Jako użytkownik, chcę żeby produkty były automatycznie kategoryzowane (nabiał, pieczywo, etc.), żeby łatwiej się orientować w spiżarni**
   - Priorytet: P0

6. **Jako użytkownik, chcę otrzymać komunikat błędu gdy OCR zawiedzie, żeby wiedzieć że muszę ręcznie sprawdzić paragon**
   - Priorytet: P0

**P1 (Should Have):**

7. **Jako użytkownik, chcę żeby system flagował podejrzane dane (ceny >100zł), żeby uniknąć błędów OCR**
   - Priorytet: P1

8. **Jako użytkownik, chcę manualnie triggerować przetwarzanie przez webhook n8n, żeby mieć kontrolę nad procesem**
   - Priorytet: P1

**P2 (Nice to Have - poza MVP):**

9. **Jako użytkownik, chcę otrzymywać sugestie AI co mogę ugotować z produktów w spiżarni, żeby nie marnować jedzenia**
   - Priorytet: P2

10. **Jako użytkownik, chcę żeby system wykrywał duplikaty zakupów i ostrzegał mnie, żeby nie kupować tego co już mam**
    - Priorytet: P2

---

## 3. Główne funkcje (zakres MVP)

### Funkcja 1: Automatyczne przetwarzanie paragonów
**Co robi:**
System monitoruje folder `/paragony/inbox/`, wykrywa nowe pliki PNG/PDF, wywołuje OCR (deepseek-ocr) i ekstrahuje produkty (nazwa, cena, data).

**Kryteria akceptacji:**
- ✅ Plik wrzucony do folderu jest wykrywany w ciągu 30 sekund
- ✅ OCR zwraca JSON z listą produktów
- ✅ System obsługuje pliki PNG i PDF

### Funkcja 2: AI Kategorizacja produktów
**Co robi:**
Po ekstrakcji OCR, model LLM (qwen2.5:7b) klasyfikuje każdy produkt do kategorii: nabiał, pieczywo, warzywa, owoce, mięso, przekąski, napoje, chemia, mrożonki, nieokreślone.

**Kryteria akceptacji:**
- ✅ Każdy produkt ma przypisaną kategorię
- ✅ Kategorie są po polsku i sensowne
- ✅ Confidence score >0.7 dla większości produktów

### Funkcja 3: Zapis do Obsidian - Historia paragonów
**Co robi:**
Tworzy plik markdown dla każdego przetworzonego paragonu w folderze `vault/paragony/` z YAML frontmatter (sklep, data, suma) i listą produktów.

**Kryteria akceptacji:**
- ✅ Plik ma nazwę: `YYYY-MM-DD-{sklep}.md`
- ✅ Zawiera YAML frontmatter z metadanymi
- ✅ Lista produktów jest czytelna i sformatowana

### Funkcja 4: Zapis do Obsidian - Agregowana spiżarnia
**Co robi:**
Aktualizuje centralny plik `vault/spiżarnia.md` dodając nowe produkty z checkboxami, grupowane po kategoriach.

**Kryteria akceptacji:**
- ✅ Produkty są dodawane do odpowiednich kategorii
- ✅ Każdy produkt ma checkbox, datę zakupu, sklep, cenę
- ✅ Plik jestczytelny i łatwy do edycji ręcznej

### Funkcja 5: Ręczny tracking zużycia
**Co robi:**
Użytkownik może odznaczać checkboxy w `spiżarnia.md` w Obsidian, aby zaznaczyć produkty jako zużyte.

**Kryteria akceptacji:**
- ✅ Checkboxy działają w Obsidian
- ✅ Odznaczenie nie wpływa na pliki historii paragonów
- ✅ Użytkownik może w każdej chwili sprawdzić co mu zostało

### Funkcja 6: Walidacja i obsługa błędów
**Co robi:**
System waliduje dane (ceny >100zł = flaga), obsługuje fail OCR (tworzy ERROR.md), używa fallbacków (data z timestampu pliku).

**Kryteria akceptacji:**
- ✅ Błąd OCR tworzy plik `YYYY-MM-DD-{sklep}-ERROR.md`
- ✅ Podejrzane ceny mają flagę ⚠️
- ✅ Brak daty nie crashuje systemu (fallback do file timestamp)

### Funkcja 7: n8n Workflow automation
**Co robi:**
Workflow n8n monitoruje folder, wywołuje FastAPI endpoint, zarządza kolejką zadań, zapisuje wyniki do Obsidian.

**Kryteria akceptacji:**
- ✅ Folder watch działa ciągle
- ✅ Można manualnie triggerować przez webhook
- ✅ Workflow obsługuje błędy (nie crashuje przy fail OCR)

---

## 4. Ścieżka użytkownika

### Główny flow (Happy Path):

**Krok 1: Przygotowanie**
- Użytkownik ma paragon (PNG/PDF) z aplikacji sklepu (Biedronka, Lidl, Kaufland)
- Nazywa plik według konwencji: `YYYY-MM-DD-{sklep}.png` (np. `2025-01-31-lidl.png`)

**Krok 2: Upload**
- Użytkownik wrzuca plik do folderu `/paragony/inbox/`
- ALBO wywołuje webhook n8n z plikiem

**Krok 3: Automatyczne przetwarzanie (backend)**
- n8n wykrywa nowy plik (folder watch trigger)
- Wywołuje FastAPI endpoint `/process-receipt`
- Python ładuje `deepseek-ocr` i ekstrahuje produkty → JSON
- Python unloaduje OCR, ładuje `qwen2.5:7b` i kategoryzuje produkty
- Python waliduje dane (ceny, daty, confidence)

**Krok 4: Zapis do Obsidian**
- System tworzy plik `vault/paragony/2025-01-31-lidl.md` z historią zakupu
- System aktualizuje `vault/spiżarnia.md` dodając produkty do odpowiednich kategorii

**Krok 5: Przegląd w Obsidian**
- Użytkownik otwiera `spiżarnia.md`
- Widzi zaktualizowaną listę produktów z checkboxami
- Może przejrzeć historię w `paragony/2025-01-31-lidl.md`

**Krok 6: Tracking zużycia**
- Gdy użytkownik zużyje produkt (np. wypije mleko), odznacza checkbox
- Spiżarnia pokazuje aktualne produkty (te z pustym checkboxem)

**Krok 7: Cleanup**
- System przenosi przetworzony plik: `inbox/` → `processed/`

---

### Flow alternatywny (OCR Error):

**Krok 3b: OCR zawodzi**
- deepseek-ocr nie może odczytać paragonu (rozmazany, uszkodzony plik)
- System tworzy plik `vault/paragony/2025-01-31-lidl-ERROR.md` z komunikatem błędu
- Użytkownik dostaje notyfikację (opcjonalnie przez n8n)
- Użytkownik ręcznie sprawdza plik źródłowy i poprawia/przepisuje dane

---

## 5. Model danych

### Paragon (Receipt)
**Lokalizacja:** `vault/paragony/YYYY-MM-DD-{sklep}.md`

**Struktura YAML frontmatter:**
```yaml
sklep: string           # "lidl", "biedronka", "kaufland"
data: date              # YYYY-MM-DD
suma: float             # 123.45
processed: datetime     # timestamp przetworzenia
ocr_confidence: float   # średni confidence (opcjonalnie)
```

**Zawartość markdown:**
- Lista produktów: nazwa, cena, kategoria

---

### Produkt (Product)
**Struktura (JSON internal):**
```json
{
  "nazwa": "string",          // "Mleko OSM 3.2% 1L"
  "cena": "float",            // 4.99
  "kategoria": "string",      // "nabiał"
  "confidence": "float",      // 0.95
  "data_zakupu": "date",      // YYYY-MM-DD
  "sklep": "string"           // "lidl"
}
```

**Kategorie (enum):**
- nabiał
- pieczywo
- warzywa
- owoce
- mięso
- ryby
- przekąski
- napoje
- chemia
- mrożonki
- nieokreślone

---

### Spiżarnia (Pantry)
**Lokalizacja:** `vault/spiżarnia.md`

**Struktura YAML frontmatter:**
```yaml
updated: datetime       # ostatnia aktualizacja
```

**Zawartość markdown:**
- Produkty grupowane po kategoriach
- Każdy produkt = checkbox + metadane (data, sklep, cena)

---

### Log błędów
**Lokalizacja:** `vault/logs/ocr-errors.md`

**Struktura:**
```markdown
## 2025-01-31 14:23:00
- File: /inbox/2025-01-31-lidl.png
- Error: OCR model failed to load
- Action: Created ERROR.md
```

---

## 6. Preferencje techniczne

### Backend:
- **Język:** Python 3.11+
- **API Framework:** FastAPI
- **Konteneryzacja:** Docker + Docker Compose
- **AI Models:** Ollama (deepseek-ocr, qwen2.5:7b)
- **Orkiestracja:** n8n (self-hosted)

### Storage:
- **Pliki:** Lokalne (Obsidian vault)
- **Format:** Markdown + YAML frontmatter
- **Baza danych:** Nie (pliki markdown jako source of truth)

### Infrastruktura:
- **Hosting:** Local-first (RTX 3060 12GB VRAM, 32GB RAM)
- **OS:** Linux (Ubuntu / compatible)
- **Folder struktura:**
  ```
  /home/user/
    paragony/
      inbox/          # Upload folder (watched by n8n)
      processed/      # Archiwum przetworzonych plików
    vault/            # Obsidian vault
      paragony/       # Historia paragonów (markdown)
      spiżarnia.md    # Agregowany widok
      logs/
        ocr-errors.md
  ```

### Integracje:
- **Ollama API:** http://localhost:11434
- **n8n:** http://localhost:5678
- **FastAPI:** http://localhost:8000

---

## 7. Kierunek designu

**Klimat/styl:**
Nie dotyczy – brak tradycyjnego UI. System działa jako:
- Backend API (FastAPI)
- n8n workflows (no-code automation)
- Obsidian markdown (użytkownik edytuje pliki tekstowe)

**Inspiracje:**
- Obsidian: https://obsidian.md (minimalistyczny, markdown-first)
- n8n workflows: https://n8n.io (automatyzacja, visual flows)

**Paleta kolorów:**
N/A (output to czysty markdown bez styli)

---

## 8. Lista "ekranów" (componentów systemu)

### 1. FastAPI Endpoints
**Endpoint:** `POST /process-receipt`
- Input: file (PNG/PDF)
- Output: JSON (status, products, errors)

**Endpoint:** `GET /health`
- Sprawdzenie czy Ollama działa, czy modele są załadowane

### 2. n8n Workflows

**Workflow 1: "Folder Watch → Process Receipt"**
- Trigger: Folder Watch (`/paragony/inbox/`)
- Action: HTTP Request → FastAPI `/process-receipt`
- Action: Save to Obsidian (write files)

**Workflow 2: "Manual Webhook Trigger"**
- Trigger: Webhook
- Input: file upload lub file path
- Action: HTTP Request → FastAPI `/process-receipt`

### 3. Obsidian Views (pliki markdown)

**View 1: spiżarnia.md**
- Agregowany widok produktów z checkboxami
- Grupowanie po kategoriach
- Metadane: data, sklep, cena

**View 2: paragony/{YYYY-MM-DD-sklep}.md**
- Historia pojedynczego paragonu
- YAML frontmatter + lista produktów

**View 3: logs/ocr-errors.md**
- Chronologiczny log błędów OCR

### 4. Docker Services

**Service 1: Ollama**
- Port: 11434
- Models: deepseek-ocr, qwen2.5:7b

**Service 2: FastAPI Backend**
- Port: 8000
- Volumes: `/paragony`, `/vault`

**Service 3: n8n**
- Port: 5678
- Volumes: workflows, credentials

---

## 9. Integracje

### AI Models (Ollama):
- **deepseek-ocr** (OCR paragonów)
- **qwen2.5:7b** (klasyfikacja produktów)
- API: http://localhost:11434/api/generate

### File System:
- Folder watch: `/paragony/inbox/`
- Obsidian vault: `/vault/`

### n8n:
- HTTP Request node → FastAPI
- File Trigger node → folder watch
- Webhook node → manual trigger

### Opcjonalne (przyszłość):
- **Notyfikacje:** ntfy.sh lub Telegram bot (gdy OCR fail)
- **Backup:** Git auto-commit dla Obsidian vault

---

## 10. Czego NIE robimy w MVP

### ❌ Automatyczne wykrywanie nazwy sklepu
**Dlaczego:** Nazwa sklepu będzie w nazwie pliku (`2025-01-31-lidl.png`). OCR sklepu to dodatkowa złożoność, często zawodzi. Ręczne nazywanie plików to 2 sekundy, oszczędza godziny debugowania.

### ❌ Sugestie AI ("co mogę ugotować", "masz duplikaty")
**Dlaczego:** To wymaga RAG, embeddings, dodatkowej logiki. MVP to tracking, nie asystent kulinarny. Dodamy w wersji 2.0 gdy podstawy będą działać.

### ❌ Deduplikacja paragonów
**Dlaczego:** Rzadko zdarza się wrzucić ten sam paragon 2x. Jeśli się zdarzy, użytkownik ręcznie usunie duplikat z Obsidian. Walidacja to dodatkowa logika (porównywanie dat, sklepów, sum).

### ❌ Historia zmian / Archiwum zużytych produktów
**Dlaczego:** Git w Obsidian pokazuje historię zmian plików. Nie potrzebujemy osobnej tabeli "co zjadłem w styczniu". Użytkownik może sam przeglądać commit history.

### ❌ Interfejs webowy
**Dlaczego:** Obsidian to UI. Budowanie dodatkowej strony web to tygodnie pracy (autentykacja, routing, state management). MVP działa w terminal + n8n + Obsidian.

### ❌ Wersja mobilna / Aplikacja
**Dlaczego:** Desktop-first. Obsidian ma aplikację mobilną, więc użytkownik może przeglądać spiżarnię na telefonie. Upload paragonów to rzadka akcja (1x dziennie), można zrobić z komputera.

### ❌ Ilość/waga produktów
**Dlaczego:** OCR często zawodzi przy ilościach (2 szt, 0.5kg, 1L). Większość decyzji zakupowych to "mam mleko czy nie", nie "mam 2 kartony czy 3". Dodamy w v2 jeśli okaże się potrzebne.

### ❌ Inteligentne daty ważności
**Dlaczego:** Wymaga bazy wiedzy (mleko = 7 dni, chleb = 3 dni). OCR nie rozpoznaje dat ważności z paragonów. Użytkownik sam wie kiedy coś się psuje. Dodamy później z AI suggestions.

### ❌ Współdzielona spiżarnia (multi-user)
**Dlaczego:** MVP to single-user, local-first. Synchronizacja, konflikty, uprawnienia = miesiące pracy. Jeśli rodzina chce współdzielić, mogą używać Obsidian Sync (płatna funkcja Obsidian).

### ❌ Export do innych formatów (CSV, Excel, JSON)
**Dlaczego:** Obsidian markdown to wystarczająco uniwersalny format. Można ręcznie skopiować do Excel jeśli potrzeba. Automatyczny export to dodatkowe API endpoints bez wyraźnej wartości w MVP.

---

## 📋 Podsumowanie dla AI Tool (Lovable/Bolt/Claude Code)

**TL;DR:**
Zbuduj backend w Pythonie (FastAPI) + n8n workflows, który:
1. Monitoruje folder `/paragony/inbox/`
2. Wywołuje Ollama (deepseek-ocr → qwen2.5:7b sekwencyjnie)
3. Zapisuje wyniki do Obsidian markdown (historia paragonów + agregowana spiżarnia)
4. Obsługuje błędy (ERROR.md, walidacja, fallbacki)

**Stack:**
- Python 3.11+ FastAPI
- Ollama (deepseek-ocr, qwen2.5:7b)
- n8n workflows
- Docker Compose
- Obsidian vault (markdown files)

**Deliverables:**
- `docker-compose.yml` (Ollama + FastAPI + n8n)
- `app/main.py` (FastAPI endpoints)
- `app/ocr.py` (deepseek-ocr logic)
- `app/classifier.py` (qwen2.5 logic)
- `app/obsidian_writer.py` (markdown generation)
- `n8n-workflows/folder-watch.json` (import do n8n)
- `README.md` (setup instructions)

---

