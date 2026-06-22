"""
Prompty AI do budowy zunifikowanego kontekstu sprawy SKD
z wielu dokumentów jednocześnie.
"""

SYSTEM_PROMPT_MULTI_DOC = """Jesteś ekspertem prawa bankowego i kredytów konsumenckich w Polsce.
Specjalizujesz się w budowaniu pełnego kontekstu sprawy dotyczącej sankcji kredytu darmowego (SKD)
na podstawie WIELU dokumentów jednocześnie.

ABSOLUTNE ZASADY:
1. NIGDY nie zgaduj ani nie wymyślaj danych. Każda wartość musi mieć źródło w dostarczonym tekście.
2. Jeśli informacja jest nieczytelna lub nie występuje w żadnym dokumencie, użyj wartości: "BRAK_DANYCH".
3. Kwoty ZAWSZE w formacie liczbowym z 2 miejscami po przecinku (np. 15000.00).
4. Daty ZAWSZE w formacie DD.MM.RRRR.
5. Przy każdej wyodrębnionej wartości podaj ŹRÓDŁO (nazwa dokumentu + numer strony/paragraf).
6. Gdy dane z różnych dokumentów są SPRZECZNE, podaj OBE wartości i oznacz rozbieżność.
7. PRIORYTET źródeł: zaświadczenie bankowe > harmonogram > umowa (bo zaświadczenie = stan faktyczny).
"""

MULTI_DOC_EXTRACTION_PROMPT = """Przeanalizuj WSZYSTKIE poniższe dokumenty i zbuduj zunifikowany kontekst sprawy SKD.
Dokumenty zostały sklasyfikowane automatycznie.

{documents_block}

ZADANIE: Wyodrębnij KOMPLETNE dane sprawy, KRZYŻOWO weryfikując informacje między dokumentami.

Zwróć odpowiedź WYŁĄCZNIE jako JSON:

{{
    "dane_stron": {{
        "kredytobiorca_imie_nazwisko": {{"wartosc": "", "zrodlo": ""}},
        "kredytobiorca_adres": {{"wartosc": "", "zrodlo": ""}},
        "kredytobiorca_pesel": {{"wartosc": "", "zrodlo": ""}},
        "kredytodawca_nazwa_pelna": {{"wartosc": "", "zrodlo": ""}},
        "kredytodawca_siedziba": {{"wartosc": "", "zrodlo": ""}},
        "kredytodawca_adres": {{"wartosc": "", "zrodlo": ""}},
        "kredytodawca_krs": {{"wartosc": "", "zrodlo": ""}}
    }},
    "dane_umowy": {{
        "numer_umowy": {{"wartosc": "", "zrodlo": ""}},
        "data_zawarcia": {{"wartosc": "", "zrodlo": ""}},
        "typ_umowy": {{"wartosc": "", "zrodlo": "", "komentarz": "pożyczka lub kredyt"}},
        "kwota_pozyczki": {{"wartosc": "", "zrodlo": "", "komentarz": "kwota pożyczki/kredytu z umowy - CKK + koszty"}},
        "calkowita_kwota_kredytu": {{"wartosc": "", "zrodlo": "", "komentarz": "CKK - kwota do dyspozycji"}},
        "calkowita_kwota_do_zaplaty": {{"wartosc": "", "zrodlo": ""}},
        "calkowity_koszt_kredytu": {{"wartosc": "", "zrodlo": ""}},
        "oprocentowanie_nominalne": {{"wartosc": "", "zrodlo": "", "komentarz": "wartość procentowa np. 7.2"}},
        "typ_oprocentowania": {{"wartosc": "", "zrodlo": "", "komentarz": "stałej lub zmiennej"}},
        "rrso": {{"wartosc": "", "zrodlo": "", "komentarz": "wartość procentowa wskazana przez bank"}},
        "liczba_rat": {{"wartosc": "", "zrodlo": ""}},
        "kwota_raty": {{"wartosc": "", "zrodlo": ""}},
        "dzien_platnosci_raty": {{"wartosc": "", "zrodlo": ""}},
        "prowizja": {{"wartosc": "", "zrodlo": ""}},
        "ubezpieczenie": {{"wartosc": "", "zrodlo": "", "komentarz": "0 jeśli brak"}},
        "suma_odsetek_umownych": {{"wartosc": "", "zrodlo": ""}},
        "opis_kosztow_kredytowanych": {{"wartosc": "", "zrodlo": ""}}
    }},
    "dane_zaswiadczenia": {{
        "suma_odsetek_zaplaconych": {{"wartosc": "", "zrodlo": ""}},
        "suma_kapitalu_splaconego": {{"wartosc": "", "zrodlo": ""}},
        "suma_prowizji_zaplaconej": {{"wartosc": "", "zrodlo": ""}},
        "data_ostatniej_wplaty": {{"wartosc": "", "zrodlo": ""}},
        "saldo_zadluzenia": {{"wartosc": "", "zrodlo": ""}},
        "data_wystawienia_zaswiadczenia": {{"wartosc": "", "zrodlo": ""}}
    }},
    "dane_harmonogramu": {{
        "data_pierwszej_raty": {{"wartosc": "", "zrodlo": ""}},
        "data_ostatniej_raty": {{"wartosc": "", "zrodlo": ""}},
        "raty_opis": {{"wartosc": "", "zrodlo": "", "komentarz": "krótki opis struktury rat"}}
    }},
    "przebieg_przedsadowy": {{
        "data_oswiadczenia_skd": {{"wartosc": "", "zrodlo": ""}},
        "data_reklamacji": {{"wartosc": "", "zrodlo": ""}},
        "data_odpowiedzi_banku": {{"wartosc": "", "zrodlo": ""}},
        "data_wezwania_do_zaplaty": {{"wartosc": "", "zrodlo": ""}},
        "data_nadania_wezwania": {{"wartosc": "", "zrodlo": ""}},
        "data_odbioru_wezwania": {{"wartosc": "", "zrodlo": ""}},
        "data_wniosku_o_zaswiadczenie": {{"wartosc": "", "zrodlo": ""}},
        "kwota_z_wezwania": {{"wartosc": "", "zrodlo": ""}},
        "stanowisko_banku_streszczenie": {{"wartosc": "", "zrodlo": ""}}
    }},
    "paragrafy_naruszen": {{
        "paragraf_rrso": {{"wartosc": "", "zrodlo": ""}},
        "paragraf_calkowita_kwota": {{"wartosc": "", "zrodlo": ""}},
        "paragraf_wczesniejsza_splata": {{"wartosc": "", "zrodlo": ""}},
        "ustep_wczesniejsza_splata": {{"wartosc": "", "zrodlo": ""}},
        "paragraf_odstapienie": {{"wartosc": "", "zrodlo": ""}},
        "ustep_odstapienie": {{"wartosc": "", "zrodlo": ""}},
        "paragraf_zmiana_oplat": {{"wartosc": "", "zrodlo": ""}},
        "paragraf_prowizja_uiszczona": {{"wartosc": "", "zrodlo": ""}},
        "kryteria_zmiany_oplat": {{"wartosc": [], "zrodlo": ""}}
    }},
    "naruszenia_art30": [
        {{
            "punkt_art30": "",
            "art_dyrektywy": "",
            "opis_naruszenia": "",
            "cytat_z_umowy": "",
            "paragraf_umowy": "",
            "pewnosc": "wysoka/srednia/niska"
        }}
    ],
    "rozbieznosci_miedzy_dokumentami": [
        {{
            "pole": "",
            "wartosc_dokument_1": "",
            "zrodlo_1": "",
            "wartosc_dokument_2": "",
            "zrodlo_2": "",
            "rekomendacja": ""
        }}
    ],
    "ochrona_czasowa": {{
        "czy_termin_dochowany": "",
        "uzasadnienie": "",
        "data_wykonania_umowy": {{"wartosc": "", "zrodlo": ""}}
    }}
}}"""


TEMPLATE_FILLING_PROMPT = """Jesteś precyzyjnym systemem wypełniania szablonów prawnych.

Otrzymujesz:
1. PEŁNY KONTEKST SPRAWY (wyodrębniony z wielu dokumentów)
2. PARAGRAF SZABLONU POZWU zawierający puste miejsca (podkreślenia ___, wielokropki ……)

ZADANIE: Dla KAŻDEGO pustego miejsca w paragrafie, na podstawie kontekstu sprawy,
wskaż DOKŁADNĄ wartość do wstawienia.

KONTEKST SPRAWY:
{case_context_json}

PARAGRAF SZABLONU DO WYPEŁNIENIA:
{paragraph_text}

ZASADY:
1. Jeśli masz wartość z kontekstu sprawy - podaj ją dokładnie.
2. Jeśli BRAK danych - odpowiedz "BRAK_DANYCH" i podaj wyjaśnienie.
3. Rozróżniaj kontekstowo KTÓRE pole jest odpowiednie (np. "kwota pożyczki" vs "całkowita kwota kredytu").
4. Daty w formacie DD.MM.RRRR, kwoty z 2 miejscami po przecinku.
5. Nie dodawaj żadnych informacji spoza kontekstu sprawy.

Odpowiedz jako JSON:
{{
    "wypelnienia": [
        {{
            "placeholder_pozycja": 0,
            "wartosc": "",
            "pole_zrodlowe": "",
            "pewnosc": "wysoka/srednia/niska"
        }}
    ]
}}"""


VIOLATION_DEEP_ANALYSIS_PROMPT = """Na podstawie PEŁNEGO KONTEKSTU SPRAWY przeprowadź pogłębioną analizę
naruszeń art. 30 ust. 1 ustawy o kredycie konsumenckim.

KONTEKST SPRAWY:
{case_context_json}

KLUCZOWE PYTANIA DO ZBADANIA:

1. ODSETKI OD KREDYTOWANYCH KOSZTÓW (art. 30 ust. 1 pkt 6 i 7 u.k.k.)
   - Porównaj "kwotę pożyczki" z "całkowitą kwotą kredytu"
   - Czy odsetki naliczane są od kwoty zawierającej prowizję/ubezpieczenie?
   - Oblicz różnicę w odsetkach

2. RRSO (art. 30 ust. 1 pkt 7 u.k.k.)
   - Czy bank wskazał założenia do obliczenia RRSO?
   - Czy na podstawie umowy konsument mógł zweryfikować RRSO?
   - Porównaj RRSO z umowy z danymi z zaświadczenia

3. CAŁKOWITA KWOTA DO ZAPŁATY (art. 30 ust. 1 pkt 7 u.k.k.)
   - Czy uwzględnia odsetki od kredytowanych kosztów?
   - Porównaj z sumą faktycznych wpłat z zaświadczenia

4. KOLEJNOŚĆ ZARACHOWANIA WPŁAT (art. 30 ust. 1 pkt 8 u.k.k.)
   - Czy umowa informuje o zarachowaniu na saldo prowizji vs saldo kapitału?

5. ZMIANA OPŁAT I PROWIZJI (art. 30 ust. 1 pkt 10 u.k.k.)
   - Czy kryteria zmiany są weryfikowalne przez konsumenta?
   - Cytuj dokładne zapisy umowy

6. WCZEŚNIEJSZA SPŁATA (art. 30 ust. 1 pkt 10 i 16 u.k.k.)
   - Czy umowa informuje o prawie do zwrotu prowizji?
   - Czy opisano procedurę wcześniejszej spłaty?

7. PRAWO ODSTĄPIENIA (art. 30 ust. 1 pkt 15 u.k.k.)
   - Czy bank poinformował o art. 53 ust. 2 u.k.k. (14 dni od uzupełnienia braków)?

Odpowiedz jako JSON:
{{
    "naruszenia_potwierdzone": [
        {{
            "punkt_art30": "",
            "art_dyrektywy": "",
            "opis": "",
            "cytat_umowy": "",
            "paragraf": "",
            "argument_prawny": "",
            "pewnosc": "wysoka"
        }}
    ],
    "naruszenia_prawdopodobne": [...],
    "brak_danych_do_oceny": [...]
}}"""


CLAIM_CALCULATION_PROMPT = """Na podstawie kontekstu sprawy oblicz wartość roszczenia SKD.

KONTEKST SPRAWY:
{case_context_json}

DANE Z WALIDACJI FINANSOWEJ:
{financial_validation_json}

OBLICZ:
1. Kwotę prowizji do zwrotu (z zaświadczenia bankowego, nie z umowy)
2. Kwotę odsetek zapłaconych do dnia sporządzenia pozwu (z zaświadczenia)
3. Łączną kwotę roszczenia (prowizja + odsetki)
4. Kwotę roszczenia słownie (po polsku)
5. Wartość Przedmiotu Sporu (WPS)
6. Opłatę sądową (5% WPS, min. 30 zł, max. 100 000 zł, zaokrąglona w górę do pełnych złotych)

WERYFIKACJA KRZYŻOWA:
- Porównaj kwotę z wezwania do zapłaty z obliczoną kwotą roszczenia
- Jeśli się różnią - wskaż rozbieżność

Odpowiedz jako JSON:
{{
    "prowizja_do_zwrotu": {{"wartosc": "", "zrodlo": ""}},
    "odsetki_do_zwrotu": {{"wartosc": "", "zrodlo": "", "okres_od": "", "okres_do": ""}},
    "kwota_roszczenia": "",
    "kwota_roszczenia_slownie": "",
    "wps": "",
    "oplata_sadowa": "",
    "weryfikacja_z_wezwaniem": {{
        "kwota_wezwanie": "",
        "kwota_obliczona": "",
        "zgodnosc": true,
        "komentarz": ""
    }}
}}"""
