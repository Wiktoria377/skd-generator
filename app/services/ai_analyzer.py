"""
Serwis analizy AI umów kredytowych przy użyciu Claude API.
Semantyczna analiza tekstu umowy w kontekście naruszeń art. 30 u.k.k.
"""
import json
import os
from typing import Optional
try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None
from app.models.schema import CreditData, AnalysisResult


SYSTEM_PROMPT = """Jesteś ekspertem prawa bankowego i kredytów konsumenckich w Polsce.
Specjalizujesz się w analizie umów kredytowych pod kątem naruszeń ustawy o kredycie konsumenckim
(u.k.k.) i Dyrektywy 2008/48/WE, ze szczególnym uwzględnieniem sankcji kredytu darmowego (SKD).

TWOJE ZADANIE: Dokładnie przeanalizuj dostarczoną umowę kredytową i wyodrębnij WSZYSTKIE
dane potrzebne do wypełnienia pozwu o SKD.

ZASADY:
1. NIGDY nie zgaduj ani nie wymyślaj danych. Jeśli informacja nie jest wyraźnie podana
   w tekście umowy, oznacz pole jako "BRAK_DANYCH".
2. Cytuj dokładne paragrafy i ustępy umowy jako źródło każdej informacji.
3. Kwoty podawaj w formacie liczbowym z dwoma miejscami po przecinku.
4. Daty podawaj w formacie DD.MM.RRRR.
5. Analizuj pod kątem naruszeń art. 30 ust. 1 u.k.k.

KLUCZOWE NARUSZENIA DO IDENTYFIKACJI:
- Naliczanie odsetek od kredytowanych kosztów (prowizji, ubezpieczenia)
- Błędne obliczenie RRSO
- Błędne wskazanie całkowitej kwoty do zapłaty
- Brak wskazania kolejności zarachowania wpłat na różne salda
- Nieweryfikowalne kryteria zmiany opłat i prowizji
- Brak informacji o prawie do zwrotu prowizji przy wcześniejszej spłacie
- Niepełna informacja o prawie odstąpienia od umowy"""


EXTRACTION_PROMPT = """Przeanalizuj poniższą umowę kredytową i wyodrębnij dane w formacie JSON.

TEKST UMOWY:
{contract_text}

Zwróć odpowiedź WYŁĄCZNIE jako JSON z następującymi polami (wartość "BRAK_DANYCH" jeśli
informacja nie występuje w umowie):

{{
    "dane_stron": {{
        "kredytobiorca_imie_nazwisko": "",
        "kredytobiorca_adres": "",
        "kredytobiorca_pesel": "",
        "kredytodawca_nazwa": "",
        "kredytodawca_adres": "",
        "kredytodawca_siedziba": ""
    }},
    "dane_umowy": {{
        "numer_umowy": "",
        "data_zawarcia": "",
        "typ_umowy": "",
        "kwota_pozyczki": "",
        "calkowita_kwota_kredytu": "",
        "calkowita_kwota_do_zaplaty": "",
        "calkowity_koszt_kredytu": "",
        "oprocentowanie_nominalne": "",
        "typ_oprocentowania": "",
        "rrso": "",
        "liczba_rat": "",
        "kwota_raty": "",
        "dzien_platnosci_raty": "",
        "prowizja": "",
        "ubezpieczenie": "",
        "suma_odsetek": ""
    }},
    "paragrafy_naruszen": {{
        "paragraf_rrso": "",
        "paragraf_wczesniejsza_splata": "",
        "ustep_wczesniejsza_splata": "",
        "paragraf_odstapienie": "",
        "ustep_odstapienie": "",
        "paragraf_zmiana_oplat": "",
        "kryteria_zmiany_oplat": [],
        "paragraf_prowizja_uiszczona": "",
        "paragraf_calkowita_kwota": ""
    }},
    "naruszenia": [
        {{
            "art_ukk": "",
            "opis": "",
            "cytat_umowy": "",
            "paragraf_umowy": "",
            "pewnosc": "wysoka/srednia/niska"
        }}
    ],
    "harmonogram_pierwsza_rata": "",
    "harmonogram_ostatnia_rata": ""
}}"""


VIOLATION_ANALYSIS_PROMPT = """Na podstawie wyodrębnionych danych z umowy kredytowej, przeprowadź
szczegółową analizę naruszeń art. 30 ust. 1 u.k.k.

WYODRĘBNIONE DANE:
{extracted_data}

TEKST UMOWY (fragmenty kluczowe):
{contract_excerpts}

Dla każdego naruszenia wskaż:
1. Konkretny przepis art. 30 ust. 1 u.k.k. (punkt)
2. Odpowiadający przepis Dyrektywy 2008/48/WE
3. Dokładny cytat z umowy potwierdzający naruszenie
4. Argumentację prawną
5. Poziom pewności (wysoka/średnia/niska)

Szczególnie zbadaj:
- Czy odsetki naliczane są od kwoty pożyczki (zawierającej prowizję) czy od całkowitej kwoty kredytu
- Czy RRSO zostało prawidłowo obliczone
- Czy założenia do RRSO są wystarczająco szczegółowe
- Czy informacja o wcześniejszej spłacie jest kompletna
- Czy informacja o odstąpieniu obejmuje art. 53 ust. 2 u.k.k.

Odpowiedz w formacie JSON:
{{
    "naruszenia_potwierdzone": [...],
    "naruszenia_watpliwe": [...],
    "brak_danych_do_oceny": [...]
}}"""


class AIAnalyzer:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY', '')
        if self.api_key:
            self.client = Anthropic(api_key=self.api_key)
        else:
            self.client = None

    def analyze_contract(self, contract_text: str) -> AnalysisResult:
        """Pełna analiza umowy kredytowej."""
        if not self.client:
            return self._demo_analysis(contract_text)

        extracted = self._extract_data(contract_text)
        violations = self._analyze_violations(contract_text, extracted)

        result = AnalysisResult(raw_text=contract_text)
        result.credit_data = self._map_to_credit_data(extracted)
        result.violations = violations.get('naruszenia_potwierdzone', [])
        result.warnings = violations.get('naruszenia_watpliwe', [])

        return result

    def _extract_data(self, contract_text: str) -> dict:
        prompt = EXTRACTION_PROMPT.format(contract_text=contract_text[:15000])
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._parse_json_response(response.content[0].text)

    def _analyze_violations(self, contract_text: str, extracted: dict) -> dict:
        prompt = VIOLATION_ANALYSIS_PROMPT.format(
            extracted_data=json.dumps(extracted, ensure_ascii=False, indent=2),
            contract_excerpts=contract_text[:8000],
        )
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._parse_json_response(response.content[0].text)

    def _parse_json_response(self, text: str) -> dict:
        text = text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1]
            text = text.rsplit('```', 1)[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {"error": "Nie udało się sparsować odpowiedzi AI", "raw": text}

    def _map_to_credit_data(self, extracted: dict) -> CreditData:
        cd = CreditData()
        ds = extracted.get('dane_stron', {})
        du = extracted.get('dane_umowy', {})
        pn = extracted.get('paragrafy_naruszen', {})

        cd.powod_imie_nazwisko = self._val(ds.get('kredytobiorca_imie_nazwisko'))
        cd.powod_adres = self._val(ds.get('kredytobiorca_adres'))
        cd.powod_pesel = self._val(ds.get('kredytobiorca_pesel'))
        cd.pozwany_nazwa = self._val(ds.get('kredytodawca_nazwa'))
        cd.pozwany_adres = self._val(ds.get('kredytodawca_adres'))
        cd.pozwany_siedziba = self._val(ds.get('kredytodawca_siedziba'))

        cd.numer_umowy = self._val(du.get('numer_umowy'))
        cd.data_zawarcia_umowy = self._val(du.get('data_zawarcia'))
        cd.typ_umowy = self._val(du.get('typ_umowy'))
        cd.kwota_pozyczki = self._val(du.get('kwota_pozyczki'))
        cd.calkowita_kwota_kredytu = self._val(du.get('calkowita_kwota_kredytu'))
        cd.calkowita_kwota_do_zaplaty = self._val(du.get('calkowita_kwota_do_zaplaty'))
        cd.calkowity_koszt_kredytu = self._val(du.get('calkowity_koszt_kredytu'))
        cd.oprocentowanie = self._val(du.get('oprocentowanie_nominalne'))
        cd.typ_oprocentowania = self._val(du.get('typ_oprocentowania'))
        cd.rrso_bank = self._val(du.get('rrso'))
        cd.liczba_rat = self._val(du.get('liczba_rat'))
        cd.kwota_raty = self._val(du.get('kwota_raty'))
        cd.dzien_platnosci_raty = self._val(du.get('dzien_platnosci_raty'))
        cd.prowizja = self._val(du.get('prowizja'))
        cd.ubezpieczenie = self._val(du.get('ubezpieczenie'))
        cd.suma_odsetek_bank = self._val(du.get('suma_odsetek'))

        cd.paragraf_rrso = self._val(pn.get('paragraf_rrso'))
        cd.paragraf_wczesniejsza_splata = self._val(pn.get('paragraf_wczesniejsza_splata'))
        cd.paragraf_ustep_wczesniejsza_splata = self._val(pn.get('ustep_wczesniejsza_splata'))
        cd.paragraf_odstapienie = self._val(pn.get('paragraf_odstapienie'))
        cd.paragraf_ustep_odstapienie = self._val(pn.get('ustep_odstapienie'))
        cd.paragraf_zmiana_oplat = self._val(pn.get('paragraf_zmiana_oplat'))
        cd.paragraf_prowizja_uiszczona = self._val(pn.get('paragraf_prowizja_uiszczona'))
        cd.paragraf_calkowita_kwota = self._val(pn.get('paragraf_calkowita_kwota'))

        kryteria = pn.get('kryteria_zmiany_oplat', [])
        if isinstance(kryteria, list) and len(kryteria) >= 1:
            cd.kryteria_zmiany_oplat_1 = kryteria[0]
        if isinstance(kryteria, list) and len(kryteria) >= 2:
            cd.kryteria_zmiany_oplat_2 = kryteria[1]

        return cd

    def _val(self, v) -> Optional[str]:
        if v and str(v).upper() not in ('BRAK_DANYCH', 'NONE', 'N/A', ''):
            return str(v)
        return None

    def _demo_analysis(self, contract_text: str) -> AnalysisResult:
        """Tryb demo bez klucza API - zwraca pusty wynik z ostrzeżeniem."""
        result = AnalysisResult(raw_text=contract_text)
        result.warnings = [{
            "message": "TRYB DEMO: Brak klucza API Anthropic. "
                       "Ustaw zmienną ANTHROPIC_API_KEY aby włączyć analizę AI. "
                       "Dane muszą zostać wprowadzone ręcznie."
        }]
        return result
