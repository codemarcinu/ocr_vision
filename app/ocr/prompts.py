"""Zoptymalizowane prompty OCR dla DeepSeek-OCR i LLM strukturyzacji.

Bazowane na analizie prawdziwych paragonów z:
- Lidl (druk termiczny)
- Auchan (druk termiczny)
- Carrefour (e-paragon z aplikacji mobilnej)
- Kaufland (e-paragon PDF)
- Biedronka (e-paragon PDF wielostronicowy)

Kluczowe wnioski:
- DeepSeek-OCR wymaga KRÓTKICH promptów (długie powodują pętle repetycji)
- Zachowanie layoutu jest krytyczne (ceny wyrównane do prawej)
- Polskie paragony używają przecinka dziesiętnego (X,XX)
- Każdy sklep ma unikalny format wymagający specyficznych reguł ekstrakcji
"""

# =============================================================================
# DeepSeek-OCR PROMPTS (muszą być KRÓTKIE żeby uniknąć pętli)
# =============================================================================

# Uniwersalny prompt OCR - zoptymalizowany dla polskich paragonów
# Kluczowe: zachowaj layout, czytaj WSZYSTKIE liczby, polskie znaki
OCR_PROMPT_UNIVERSAL = """Odczytaj ten polski paragon. Zachowaj układ z cenami po prawej stronie.
Uwzględnij WSZYSTKIE nazwy produktów i ceny (format: X,XX).
Zachowaj oryginalną strukturę linii."""

# Alternatywny krótszy prompt jeśli uniwersalny powoduje problemy
OCR_PROMPT_MINIMAL = "Odczytaj paragon. Zachowaj układ, wszystkie teksty i ceny."

# Prompty OCR dla konkretnych sklepów (do przyszłej implementacji 2-pass)
OCR_PROMPTS = {
    "lidl": """Paragon z Lidl. Format: nazwa produktu, potem ilość*cena=wartość.
Czytaj wszystkie linie włącznie z RABAT. Zachowaj układ.""",

    "auchan": """Paragon z Auchan. Produkty mają kody EAN po nazwach.
Format: NAZWA KOD ilość x cena wartość. Czytaj też linie Rabat.""",

    "biedronka": """E-paragon z Biedronki (tabela). Kolumny: Nazwa|PTU|Ilość×|Cena|Wartość.
Linie Rabat pod produktami to zniżki. Cena końcowa to pogrubiona liczba po Rabat.""",

    "kaufland": """E-paragon z Kaufland. Nazwy produktów bez spacji (CamelCase).
Prosty format: NazwaProduktu Cena. Czytaj wszystkie wiersze.""",

    "carrefour": """E-paragon z Carrefour. Nazwy produktów w wielu liniach.
Format ceny: ilość*cena = wartość. Czerwone linie Rabat to zniżki.""",
}


# =============================================================================
# PROMPTY LLM DO STRUKTURYZACJI (dla konkretnych sklepów, z prawdziwymi przykładami)
# =============================================================================

STRUCTURING_PROMPT_BIEDRONKA = """Paragon z BIEDRONKI. Ekstrahuj produkty do JSON.

FORMAT PARAGONU (tabela):
```
Nazwa             PTU   Ilość ×    Cena    Wartość
Banan Luz          C    0.815 ×    6,99      5,70
  Rabat                                     -3,02
                                             2,68
```

ZASADY:
1. KAŻDY produkt osobno (nawet jak nazwa się powtarza)
2. "cena" = OSTATNIA liczba w bloku (po Rabat jeśli jest) → tu: 2,68
3. "cena_przed" = wartość przed rabatem → tu: 5,70
4. "rabat" = wartość dodatnia bez minusa → tu: 3,02
5. Produkty wagowe: Ilość to waga (0.815 = 815g)
6. IGNORUJ: "Sprzedaż opodatkowana", "PTU", "Suma PTU", "Karta płatnicza", "Strona X z Y"
7. "suma" = wartość przy "Suma PLN"

PRZYKŁAD Z PRAWDZIWEGO PARAGONU:
```
Jog Naturalny 400g    C    1.000 ×    1,79      1,79
MieszankaProtBak150   C    1.000 ×    8,99      8,99
  Rabat                                        -2,45
                                                6,54
```
→ produkty: [
    {{"nazwa":"Jog Naturalny 400g","cena":1.79}},
    {{"nazwa":"MieszankaProtBak150","cena":6.54,"cena_przed":8.99,"rabat":2.45}}
  ]

KATEGORIE (przypisz każdemu produktowi):
- Nabiał: mleko, ser, jogurt, masło, śmietana, twaróg, kefir, skyr, jaja
- Pieczywo: chleb, bułka, bagietka, rogal
- Mięso: kurczak, schab, mielone, wołowina, indyk
- Wędliny: szynka, kiełbasa, salami, boczek, kabanos, parówki
- Ryby: łosoś, dorsz, śledź, tuńczyk
- Warzywa: pomidory, ziemniaki, ogórki, papryka, cebula, marchew, sałata
- Owoce: banany, jabłka, pomarańcze, winogrona, mandarynki
- Napoje: woda, sok, cola, oranżada
- Alkohol: piwo, wino, wódka
- Napoje gorące: kawa, herbata, kakao
- Słodycze: czekolada, ciastka, cukierki, żelki, wafle
- Przekąski: chipsy, paluszki, orzeszki, nachos
- Produkty sypkie: makaron, ryż, kasza, mąka, płatki
- Przyprawy: sól, pieprz, ketchup, musztarda, majonez
- Konserwy: groszek, kukurydza, fasola
- Mrożonki: frytki, pizza mrożona, pierogi, warzywa mrożone
- Dania gotowe: zupa instant, hummus, bigos
- Chemia: proszek, płyn do naczyń, papier toaletowy
- Kosmetyki: szampon, mydło, dezodorant, pasta do zębów
- Dla dzieci: pieluchy, kaszka
- Dla zwierząt: karma, żwirek
- Inne: torba, wszystko inne

Zwróć TYLKO JSON:
{{"sklep":"Biedronka","data":"RRRR-MM-DD","produkty":[{{"nazwa":"X","cena":0.00,"kategoria":"Y"}}],"suma":0.00}}

TEKST PARAGONU:
{ocr_text}"""

STRUCTURING_PROMPT_LIDL = """Paragon z LIDL. Ekstrahuj produkty do JSON.

FORMAT PARAGONU (termiczny):
```
Reklamówka mała r...   2 * 0,79 1,58 A
Poszcie1684610119      1 * 9,34 34,99 A
  RABAT 5zt                     -8,50
Scizereczki nas... 80  1 * 0,99 0,99 C
Mięso UdźL 1,5%...     0,646 * 17.99 11.62 A
```

ZASADY:
1. Format: "Nazwa    ilość * cena wartość KAT"
2. RABAT to osobna linia z minusem
3. "cena" = wartość po prawej stronie (11.62 dla produktów wagowych)
4. Produkty wagowe: ilość < 1 to waga w kg (0,646 = 646g)
5. Litera na końcu (A/B/C) to stawka VAT - IGNORUJ
6. IGNORUJ: "Kwota A/B/C", "PTU", "Suma", "Razem"
7. "suma" = wartość przy "Razem" lub "Płatność Karta płatnicza"

PRZYKŁAD:
```
Bułka kajzerka         4 * 0.35 1.4 C
Śmietana 12% 4         1 * 3.59 3.59 C
Kwota C 5,00%                   0,51
Razem                          21,72
```
→ produkty: [{{"nazwa":"Bułka kajzerka","cena":1.40}},{{"nazwa":"Śmietana 12%","cena":3.59}}]
→ suma: 21.72

KATEGORIE: Nabiał, Pieczywo, Mięso, Wędliny, Ryby, Warzywa, Owoce, Napoje, Alkohol, Napoje gorące, Słodycze, Przekąski, Produkty sypkie, Przyprawy, Konserwy, Mrożonki, Dania gotowe, Chemia, Kosmetyki, Dla dzieci, Dla zwierząt, Inne

Zwróć TYLKO JSON:
{{"sklep":"Lidl","data":"RRRR-MM-DD","produkty":[{{"nazwa":"X","cena":0.00,"kategoria":"Y"}}],"suma":0.00}}

TEKST PARAGONU:
{ocr_text}"""

STRUCTURING_PROMPT_AUCHAN = """Paragon z AUCHAN. Ekstrahuj produkty do JSON.

FORMAT PARAGONU (termiczny):
```
AMIGO MATE 475638C        1 x8,19 8,19C
SMOOTHIE J 359548C        1 x4,15 4,15C
MUS MARCHE 360228C        1 x2,68 2,68C
Rabat SMOOTHIE J 359553C         -4,14C
SUMA PLN                         51,90
Udzielono łącznie rabatów:        8,98
```

ZASADY:
1. Format: "NAZWA PRODUKTU KODEAN    ilość xcena wartośćKAT"
2. Kod EAN (6-8 cyfr + litera) jest częścią linii - USUŃ z nazwy
3. Rabaty: "Rabat NAZWA KODEAN -wartość" - przypisz do produktu o tej nazwie
4. Litera na końcu (A/B/C) to VAT - IGNORUJ
5. "suma" = wartość przy "SUMA PLN"
6. IGNORUJ: "Sprzedaż opodatk.", "PTU", "Udzielono łącznie rabatów"

PRZYKŁAD:
```
JOGURT GRE 940801C        1 x2,84 2,84C
POMIDORY K 390987C        1 x3,99 3,99C
Rabat POMIDORY K 390987C        -1,00C
SUMA PLN                        75,82
```
→ produkty: [
    {{"nazwa":"JOGURT GRECKI","cena":2.84,"kategoria":"Nabiał"}},
    {{"nazwa":"POMIDORY","cena":2.99,"cena_przed":3.99,"rabat":1.00,"kategoria":"Warzywa"}}
  ]

WAŻNE: Usuń kody EAN z nazw (np. "JOGURT GRE 940801C" → "JOGURT GRECKI")

KATEGORIE: Nabiał, Pieczywo, Mięso, Wędliny, Ryby, Warzywa, Owoce, Napoje, Alkohol, Napoje gorące, Słodycze, Przekąski, Produkty sypkie, Przyprawy, Konserwy, Mrożonki, Dania gotowe, Chemia, Kosmetyki, Dla dzieci, Dla zwierząt, Inne

Zwróć TYLKO JSON:
{{"sklep":"Auchan","data":"RRRR-MM-DD","produkty":[{{"nazwa":"X","cena":0.00,"kategoria":"Y"}}],"suma":0.00}}

TEKST PARAGONU:
{ocr_text}"""

STRUCTURING_PROMPT_KAUFLAND = """Paragon z KAUFLAND (e-paragon). Ekstrahuj produkty do JSON.

FORMAT PARAGONU (PDF z aplikacji):
```
                                    Cena w
Torba foliowa                        0,79
MonteSantWater0,75                  14,99
SerekŁaciatyCzos135g                 3,69
KabanosWołowWieprz                   6,79
Suma                     none       61,50
```

ZASADY:
1. Format prosty: "NazwaProduktuBezSpacji    cena"
2. Nazwy są sklejone (CamelCase) - rozdziel na słowa
3. Ceny są już KOŃCOWE (po rabatach)
4. "none" przy Suma to błąd OCR - ignoruj
5. IGNORUJ: "Podatek", "Brutto", "Netto", "PTU", "Za ten zakup otrzymałeś"
6. "suma" = wartość przy "Suma"

PRZYKŁAD:
```
MilkaNapójMlecznyK...                5,99
CheetosSweetChil165g                 6,49
Suma                     none       61,50
```
→ produkty: [
    {{"nazwa":"Milka Napój Mleczny","cena":5.99,"kategoria":"Napoje"}},
    {{"nazwa":"Cheetos Sweet Chili 165g","cena":6.49,"kategoria":"Słodycze"}}
  ]
→ suma: 61.50

ROZDZIELANIE NAZW:
- "SerekŁaciatyCzos135g" → "Serek Łaciaty Czosnek 135g"
- "KabanosWołowWieprz" → "Kabanos Wołowo-Wieprzowy"
- "MlekoZagęszczon530g" → "Mleko Zagęszczone 530g"

KATEGORIE: Nabiał, Pieczywo, Mięso, Wędliny, Ryby, Warzywa, Owoce, Napoje, Alkohol, Napoje gorące, Słodycze, Przekąski, Produkty sypkie, Przyprawy, Konserwy, Mrożonki, Dania gotowe, Chemia, Kosmetyki, Dla dzieci, Dla zwierząt, Inne

Zwróć TYLKO JSON:
{{"sklep":"Kaufland","data":"RRRR-MM-DD","produkty":[{{"nazwa":"X","cena":0.00,"kategoria":"Y"}}],"suma":0.00}}

TEKST PARAGONU:
{ocr_text}"""

STRUCTURING_PROMPT_CARREFOUR = """Paragon z CARREFOUR (e-paragon z aplikacji). Ekstrahuj produkty do JSON.

FORMAT PARAGONU (screenshot z aplikacji mobilnej):
```
FUTOMAKI Z               1*29,99 = 29,99
PIECZONYM
ŁOSOSIEM

California łosoś pie     1*23,99 = 23,99

Bakoma Maxi Meal Napój   1*9,99 = 9,99
mleczny o smaku
bananowym 500 g
Rabat                    1*2,49 = 2,49

Suma                     53,98 zł
Karta Płatnicza          53,98 zł
```

ZASADY:
1. Nazwa produktu może być w WIELU LINIACH - połącz je
2. Format ceny: "ilość*cena = wartość"
3. "Rabat" to osobna linia - odejmij od poprzedniego produktu
4. "cena" = wartość końcowa (po rabacie jeśli był)
5. IGNORUJ: "Sprzed. opod.", "Kwota C", "Podatek PTU"
6. "suma" = wartość przy "Suma" lub "Karta Płatnicza"

PRZYKŁAD:
```
Bakoma 7 zbóż Men        1*5,29 = 5,29
Jogurt z grejpfrutem
żurawiną i ziarnami zbóż
300 g

Bakoma Maxi Meal Napój   1*9,99 = 9,99
mleczny o smaku słonego
karmelu 500 g
Rabat                    1*2,49 = 2,49

Suma                     20,29 zł
```
→ produkty: [
    {{"nazwa":"Bakoma 7 zbóż Jogurt z grejpfrutem żurawiną i ziarnami zbóż 300g","cena":5.29,"kategoria":"Nabiał"}},
    {{"nazwa":"Bakoma Maxi Meal Napój mleczny o smaku słonego karmelu 500g","cena":7.50,"cena_przed":9.99,"rabat":2.49,"kategoria":"Napoje"}}
  ]

KATEGORIE: Nabiał, Pieczywo, Mięso, Wędliny, Ryby, Warzywa, Owoce, Napoje, Alkohol, Napoje gorące, Słodycze, Przekąski, Produkty sypkie, Przyprawy, Konserwy, Mrożonki, Dania gotowe, Chemia, Kosmetyki, Dla dzieci, Dla zwierząt, Inne

Zwróć TYLKO JSON:
{{"sklep":"Carrefour","data":"RRRR-MM-DD","produkty":[{{"nazwa":"X","cena":0.00,"kategoria":"Y"}}],"suma":0.00}}

TEKST PARAGONU:
{ocr_text}"""

STRUCTURING_PROMPT_GENERIC = """Paragon ze sklepu. Ekstrahuj produkty do JSON.

OGÓLNE ZASADY:
1. Każda linia z nazwą i ceną = produkt
2. "cena" = cena KOŃCOWA (po rabacie)
3. Rabat/Promocja to linie z minusem (-X,XX) - odejmij od produktu powyżej
4. IGNORUJ: PTU, VAT, podatki, "Suma PTU", płatności
5. "suma" = "DO ZAPŁATY", "SUMA", "RAZEM" lub "Karta płatnicza"

KATEGORIE:
- Nabiał: mleko, ser, jogurt, masło, śmietana, jaja
- Pieczywo: chleb, bułka, bagietka
- Mięso: kurczak, schab, mielone, wołowina
- Wędliny: szynka, kiełbasa, boczek, parówki
- Ryby: łosoś, dorsz, śledź, tuńczyk
- Warzywa: pomidor, ogórek, ziemniaki, marchew
- Owoce: jabłko, banan, pomarańcze, winogrona
- Napoje: woda, sok, cola, oranżada
- Alkohol: piwo, wino, wódka
- Napoje gorące: kawa, herbata, kakao
- Słodycze: czekolada, ciastka, cukierki, żelki
- Przekąski: chipsy, paluszki, orzeszki
- Produkty sypkie: makaron, ryż, kasza, mąka
- Przyprawy: sól, pieprz, ketchup, musztarda
- Konserwy: groszek, kukurydza, fasola
- Mrożonki: frytki, pizza mrożona, pierogi
- Dania gotowe: zupa instant, hummus, bigos
- Chemia: proszek, płyn, papier toaletowy
- Kosmetyki: szampon, mydło, dezodorant
- Dla dzieci: pieluchy, kaszka
- Dla zwierząt: karma, żwirek
- Inne: wszystko inne

Zwróć TYLKO JSON:
{{"sklep":"nazwa","data":"RRRR-MM-DD","produkty":[{{"nazwa":"X","cena":0.00,"kategoria":"Y"}}],"suma":0.00}}

TEKST PARAGONU:
{ocr_text}"""

_ZAKAZANE = """

ZAKAZANE (BEZWZGLĘDNIE PRZESTRZEGAJ):
- NIE dodawaj produktów których NIE MA na paragonie
- NIE wymyślaj ani nie zgaduj cen — wpisuj DOKŁADNIE to co na paragonie
- NIE zaokrąglaj kwot (3,49 to NIE 3,50)
- NIE dodawaj domyślnych produktów (sól, woda, reklamówka) jeśli nie widać ich na paragonie
- NIE wymyślaj daty jeśli nie jest czytelna — zostaw puste
- NIE zmieniaj nazw produktów na "bardziej poprawne" — przepisz jak jest
"""

# Mapowanie sklepu na prompt strukturyzacji
STRUCTURING_PROMPTS = {
    "biedronka": STRUCTURING_PROMPT_BIEDRONKA,
    "lidl": STRUCTURING_PROMPT_LIDL,
    "auchan": STRUCTURING_PROMPT_AUCHAN,
    "kaufland": STRUCTURING_PROMPT_KAUFLAND,
    "carrefour": STRUCTURING_PROMPT_CARREFOUR,
}


def get_ocr_prompt(store: str = None) -> str:
    """Pobierz prompt OCR dla DeepSeek-OCR.

    Uwaga: Obecnie zwraca uniwersalny prompt, ponieważ wykrywanie sklepu
    następuje PO OCR. W przyszłej implementacji 2-pass może zwracać
    prompty specyficzne dla sklepu.
    """
    if store and store.lower() in OCR_PROMPTS:
        return OCR_PROMPTS[store.lower()]
    return OCR_PROMPT_UNIVERSAL


def get_structuring_prompt(store: str = None) -> str:
    """Pobierz prompt LLM do strukturyzacji dla wykrytego sklepu."""
    if store and store.lower() in STRUCTURING_PROMPTS:
        return STRUCTURING_PROMPTS[store.lower()] + _ZAKAZANE
    return STRUCTURING_PROMPT_GENERIC + _ZAKAZANE
