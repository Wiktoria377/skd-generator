"""
Cross-Document Context Engine v3.
Aggressive cross-referencing, synonym resolution, derived field calculation,
and human-in-the-loop for ambiguous data.
"""
import json
import os
import re
import uuid
from typing import Optional
from anthropic import Anthropic

from app.models.schema import (
    CaseContext, CreditData, ClassifiedDocument, DocumentType,
    REQUIRED_DOCUMENTS, REQUIRED_DOC_ALERTS, DOC_TYPE_LABELS,
    UserQuestion,
)
from app.services.prompts.case_context import (
    SYSTEM_PROMPT_MULTI_DOC,
    MULTI_DOC_EXTRACTION_PROMPT,
    VIOLATION_DEEP_ANALYSIS_PROMPT,
    CLAIM_CALCULATION_PROMPT,
)

# ============================================================
# Polish banking synonym map for aggressive field resolution
# ============================================================

FIELD_SYNONYMS = {
    'calkowita_kwota_kredytu': [
        'całkowita kwota kredytu', 'całkowita kwota pożyczki',
        'kwota do dyspozycji', 'środki oddane do dyspozycji',
        'kwota wypłacona', 'kwota netto', 'kwota udostępniona',
        'kwota pożyczki netto', 'wypłacona kwota kredytu',
        'całkowita kwota pożyczki/kredytu',
    ],
    'kwota_pozyczki': [
        'kwota pożyczki wynosi', 'kwota kredytu wynosi',
        'kwota udzielonego kredytu', 'kwota udzielonej pożyczki',
        'nominalna kwota kredytu', 'kwota brutto',
    ],
    'prowizja': [
        'prowizja', 'prowizja za udzielenie', 'opłata przygotowawcza',
        'prowizja przygotowawcza', 'opłata za udzielenie kredytu',
        'opłata za udzielenie pożyczki', 'prowizja bankowa',
        'jednorazowa opłata', 'fee', 'commission',
    ],
    'oprocentowanie': [
        'oprocentowanie nominalne', 'stopa procentowa',
        'stopa oprocentowania', 'oprocentowanie roczne',
        'nominalna stopa procentowa', 'wynoszącej',
    ],
    'rrso_bank': [
        'rrso', 'rzeczywista roczna stopa oprocentowania',
        'apr', 'roczna stopa oprocentowania', 'rrso wynosi',
    ],
    'calkowity_koszt_kredytu': [
        'całkowity koszt kredytu', 'całkowity koszt pożyczki',
        'łączny koszt', 'koszt kredytu',
    ],
    'calkowita_kwota_do_zaplaty': [
        'całkowita kwota do zapłaty', 'łączna kwota do zapłaty',
        'suma do zapłaty', 'razem do zapłaty',
    ],
    'suma_odsetek_zaplaconych': [
        'suma odsetek', 'odsetki zapłacone', 'zapłacone odsetki',
        'naliczone odsetki', 'odsetki razem', 'suma zapłaconych odsetek',
        'łączna kwota odsetek', 'odsetki ogółem',
    ],
    'suma_kapitalu_splaconego': [
        'spłacony kapitał', 'kapitał spłacony', 'suma spłat kapitału',
        'spłata kapitału', 'kapitał razem',
    ],
    'kwota_raty': [
        'rata wynosi', 'wysokość raty', 'kwota raty', 'rata miesięczna',
        'miesięczna rata', 'rata kapitałowo-odsetkowa',
    ],
    'data_zawarcia_umowy': [
        'data zawarcia', 'data umowy', 'zawarta w dniu', 'z dnia',
        'data podpisania',
    ],
    'numer_umowy': [
        'numer umowy', 'nr umowy', 'umowa nr', 'numer', 'sygnatura',
    ],
}


class ContextEngine:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY', '')
        self.client = Anthropic(api_key=self.api_key) if self.api_key else None

    def build_case_context(
        self,
        classified_docs: list[ClassifiedDocument],
        financial_validation: Optional[dict] = None,
        user_answers: Optional[dict] = None,
        excel_rrso_data: Optional[dict] = None,
        gofin_data: Optional[dict] = None,
    ) -> CaseContext:
        """Build full case context with aggressive field resolution."""
        ctx = CaseContext()
        ctx.classified_docs = classified_docs

        self._check_missing_documents(ctx)

        ctx.all_texts = {}
        for doc in classified_docs:
            if doc.doc_type != DocumentType.UNKNOWN:
                key = doc.doc_type.value
                if key in ctx.all_texts:
                    ctx.all_texts[key] += "\n\n" + doc.extracted_text
                else:
                    ctx.all_texts[key] = doc.extracted_text

        # Phase 1: Regex-based extraction (works without API key)
        self._regex_extract_all(ctx)

        # Phase 2: AI extraction if available
        if self.client:
            self._ai_extract(ctx, classified_docs)
        else:
            ctx.warnings.append({
                "message": "TRYB DEMO: Brak ANTHROPIC_API_KEY. "
                           "Użyto ekstrakcji regexowej. Dla pełnej analizy AI ustaw klucz API."
            })

        # Phase 3: Cross-document derivation (calculate missing fields from available data)
        self._derive_missing_fields(ctx)

        # Phase 4: Apply user answers to override/fill remaining gaps
        if user_answers:
            self._apply_user_answers(ctx, user_answers)

        # Phase 5: Financial validation enrichment
        if financial_validation:
            ctx.financial_validation = financial_validation
            self._apply_financial_to_credit_data(ctx, financial_validation)

        # Phase 6: Identify remaining ambiguities -> generate questions
        self._generate_questions(ctx)

        # Phase 6.5: Inject Excel RRSO and Gofin data before golden rules
        # Excel data is the MOST RELIABLE source — it overrides regex-extracted values
        cd = ctx.credit_data
        EXCEL_OVERRIDE_FIELDS = {
            'rrso_bank', 'kwota_pozyczki', 'calkowita_kwota_kredytu', 'prowizja',
            'kwota_raty', 'liczba_rat', 'dzien_platnosci_raty',
            'data_pierwszej_raty', 'data_ostatniej_raty', 'harmonogram_raty_opis',
            'rrso_kolumna3', 'rrso_kolumna4', 'rrso_kolumna5',
            'rrso_kolumna3_roznica', 'rrso_kolumna4_roznica', 'rrso_kolumna5_roznica',
            'suma_odsetek_bank', 'calkowity_koszt_kredytu', 'calkowita_kwota_do_zaplaty',
        }
        if excel_rrso_data:
            for k, v in excel_rrso_data.items():
                if v and hasattr(cd, k):
                    if k in EXCEL_OVERRIDE_FIELDS or not getattr(cd, k, None):
                        setattr(cd, k, str(v))
                # Also log rata_pierwsza/ostatnia for golden rule calculations
                if k in ('rata_pierwsza', 'rata_ostatnia', 'rata_standardowa') and v:
                    ctx.resolution_log.append({'field': k, 'value': str(v), 'method': 'excel', 'source': 'RRSO Excel'})
        if gofin_data:
            if gofin_data.get('rata_gofin'):
                cd.hipotetyczna_rata = gofin_data['rata_gofin']
            if gofin_data.get('ckk') and not cd.calkowita_kwota_kredytu:
                cd.calkowita_kwota_kredytu = gofin_data['ckk']
            if gofin_data.get('oprocentowanie') and not cd.oprocentowanie:
                cd.oprocentowanie = gofin_data['oprocentowanie']
            if gofin_data.get('liczba_rat') and not cd.liczba_rat:
                cd.liczba_rat = gofin_data['liczba_rat']

        # Phase 7: Golden standard rules (deterministic derivation)
        from app.services.golden_rules import apply_golden_rules
        apply_golden_rules(ctx)

        # Phase 8: Violations analysis
        if self.client:
            self._ai_violations(ctx)

        return ctx

    # ============================================================
    # Phase 1: Regex extraction from raw text
    # ============================================================

    def _regex_extract_all(self, ctx: CaseContext):
        """Extract data using regex patterns — structured extractors first, then generic."""
        cd = ctx.credit_data

        # STEP 1: Structured extractors FIRST (highest reliability)
        self._extract_from_ankieta(ctx)
        self._extract_from_wniosek(ctx)

        # STEP 2: Generic synonym-based regex on non-ankieta text
        relevant_text = '\n'.join(
            text for doc_type, text in ctx.all_texts.items()
            if doc_type != DocumentType.INNE.value
        )
        for doc in ctx.classified_docs:
            if 'ankieta' not in doc.filename.lower() and doc.extracted_text not in relevant_text:
                relevant_text += '\n' + doc.extracted_text

        for field_name, synonyms in FIELD_SYNONYMS.items():
            if getattr(cd, field_name, None) is not None:
                continue
            value = self._regex_find_value(relevant_text, synonyms, field_name)
            if value:
                setattr(cd, field_name, value)
                ctx.resolution_log.append({
                    'field': field_name, 'value': value,
                    'method': 'regex', 'source': 'multi-doc',
                })

        # STEP 3: Document-type-specific extractors
        self._extract_from_contract(ctx)
        self._extract_from_certificate(ctx)
        self._extract_from_schedule(ctx)
        self._extract_from_demand_letter(ctx)
        self._extract_from_skd_statement(ctx)

    def _regex_find_value(self, text: str, synonyms: list, field_name: str) -> Optional[str]:
        """Find a value near a synonym keyword."""
        text_lower = text.lower()
        is_date = 'data' in field_name
        is_number = any(kw in field_name for kw in [
            'kwota', 'prowizja', 'oprocentowanie', 'rrso', 'suma', 'koszt',
            'raty', 'ubezpieczenie', 'saldo', 'oplata', 'wps', 'rat',
        ])

        for syn in synonyms:
            idx = text_lower.find(syn.lower())
            if idx == -1:
                continue

            # Look at the text after the synonym
            after = text[idx + len(syn):idx + len(syn) + 100]

            if is_date:
                m = re.search(r'(\d{1,2}[./\-]\d{1,2}[./\-]\d{4})', after)
                if m:
                    return m.group(1).replace('/', '.').replace('-', '.')

            if is_number:
                # Match Polish number formats: 35 000,00 or 35000.00 or 12,50%
                m = re.search(
                    r'[:\s=]*\s*([\d\s]{1,10}[\d](?:[,\.]\d{1,2})?)\s*(?:zł|PLN|%|złotych)?',
                    after
                )
                if m:
                    val = m.group(1).replace(' ', '').replace('\xa0', '')
                    return val

            # Generic: grab the next meaningful chunk
            m = re.search(r'[:\s]+([A-ZŁŚŻŹĆĘĄÓŃ][\w\s,./\-]{3,60})', after)
            if m:
                return m.group(1).strip().rstrip(',.')

        return None

    def _extract_from_ankieta(self, ctx: CaseContext):
        """Extract personal data from client questionnaire (ankieta)."""
        # Ankieta can be classified as INNE or even UMOWA due to keyword overlap
        ankieta_text = None
        for doc in ctx.classified_docs:
            if 'ankieta' in doc.filename.lower():
                ankieta_text = doc.extracted_text
                break
        if not ankieta_text:
            ankieta_text = ctx.all_texts.get(DocumentType.INNE.value, '')
        if not ankieta_text or 'ankieta' not in ankieta_text.lower():
            return

        cd = ctx.credit_data

        m = re.search(r'Imię\s+i\s+nazwisko\s+Klienta[:\s]+([A-ZŁŚŻŹĆĘĄÓŃ][a-ząćęłńóśźż]+\s+[A-ZŁŚŻŹĆĘĄÓŃ][a-ząćęłńóśźż]+)', ankieta_text)
        if m:
            cd.powod_imie_nazwisko = m.group(1).strip()

        m = re.search(r'PESEL\s+Klienta[:\s]+(\d{11})', ankieta_text)
        if m:
            cd.powod_pesel = m.group(1)

        m = re.search(r'[Aa]ktualny\s+adres\s+zamieszkania\s+Klienta\s*[:\s]+(.+?)(?:\n|$)', ankieta_text)
        if m:
            cd.powod_adres = m.group(1).strip()

    def _extract_from_wniosek(self, ctx: CaseContext):
        """Extract key data from wniosek o zaświadczenie (digital PDF with contract details)."""
        for doc in ctx.classified_docs:
            if 'wniosek' in doc.filename.lower() and doc.extracted_text:
                text = doc.extracted_text
                cd = ctx.credit_data

                # Contract number - may span two lines
                text_oneline = text.replace('\n', ' ')
                m = re.search(r'(?:umowy\s+pożyczki\s+(?:o\s+)?nr|umowy?\s+nr|nr)\s+([\d\s]{20,40}\d{4})', text_oneline)
                if m and not cd.numer_umowy:
                    cd.numer_umowy = re.sub(r'\s+', ' ', m.group(1)).strip()

                # Contract date
                m = re.search(r'z\s+dnia\s+(\d{1,2}[./]\d{1,2}[./]\d{4})', text_oneline)
                if m and not cd.data_zawarcia_umowy:
                    cd.data_zawarcia_umowy = m.group(1).replace('/', '.')

                # Bank name
                for pattern in [r'(PKO\s+Bank\s+Polski\s+S\.A\.)', r'(Powszechna\s+Kasa\s+Oszczędności[^,\n]+)',
                                r'^([A-Z][\w\s]+(?:S\.A\.|Bank\w*)[^,\n]*)', ]:
                    m = re.search(pattern, text, re.M)
                    if m and not cd.pozwany_nazwa:
                        cd.pozwany_nazwa = m.group(1).strip()
                        break

    def _extract_from_contract(self, ctx: CaseContext):
        """Extract specific fields from credit agreement text."""
        text = ctx.all_texts.get(DocumentType.UMOWA.value, '')
        if not text:
            return
        cd = ctx.credit_data

        # Number of installments
        if not cd.liczba_rat:
            m = re.search(r'(\d+)\s*rat(?:ach|y|a)', text)
            if m:
                cd.liczba_rat = m.group(1)

        # Day of payment
        if not cd.dzien_platnosci_raty:
            m = re.search(r'do\s+(\d{1,2})\s*(?:\.|-go)?\s*dnia\s+każdego\s+miesiąca', text, re.I)
            if m:
                cd.dzien_platnosci_raty = m.group(1)

        # Interest rate type
        if not cd.typ_oprocentowania:
            if re.search(r'stałe[jy]?\s+stop', text, re.I):
                cd.typ_oprocentowania = 'stałej'
            elif re.search(r'zmienne[jy]?\s+stop', text, re.I):
                cd.typ_oprocentowania = 'zmiennej'

        # Paragraph references for violations
        for para_field, patterns in [
            ('paragraf_wczesniejsza_splata', [r'§\s*(\d+).*?(?:wcześniejsz|przedterminow)']),
            ('paragraf_odstapienie', [r'§\s*(\d+).*?(?:odstąpieni|rezygnacj)']),
            ('paragraf_zmiana_oplat', [r'§\s*(\d+).*?(?:zmian\w+\s+opłat|zmian\w+\s+prowizj)']),
            ('paragraf_rrso', [r'§\s*(\d+).*?(?:rrso|rzeczywist)', r'(?:rrso|rzeczywist).*?§\s*(\d+)']),
        ]:
            if not getattr(cd, para_field, None):
                for pat in patterns:
                    m = re.search(pat, text, re.I)
                    if m:
                        setattr(cd, para_field, f'§ {m.group(1)}')
                        break

        # Change criteria (art. 30 pkt 10 violation)
        if not cd.kryteria_zmiany_oplat_1:
            m = re.search(r'zmian\w+\s+(?:opłat|prowizj)\w*\s+w\s+przypadku\s*:?\s*(.{50,300}?)(?:\.|§)', text, re.I | re.DOTALL)
            if m:
                criteria = m.group(1).strip()
                parts = re.split(r',\s*', criteria)
                if parts:
                    cd.kryteria_zmiany_oplat_1 = parts[0].strip()
                if len(parts) > 1:
                    cd.kryteria_zmiany_oplat_2 = parts[1].strip()

        # Borrower/lender names via common patterns
        if not cd.powod_imie_nazwisko:
            for pat in [r'(?:pożyczkobiorc\w+|kredytobiorc\w+)[:\s,]+([A-ZŁŚŻŹĆĘĄÓŃ][a-ząćęłńóśźż]+\s+[A-ZŁŚŻŹĆĘĄÓŃ][a-ząćęłńóśźż]+)',
                        r'([A-ZŁŚŻŹĆĘĄÓŃ][a-ząćęłńóśźż]+\s+[A-ZŁŚŻŹĆĘĄÓŃ][a-ząćęłńóśźż]+),?\s*(?:PESEL|zamieszkał)',
                        r'PESEL[:\s]*\d{11}.*?([A-ZŁŚŻŹĆĘĄÓŃ][a-ząćęłńóśźż]+\s+[A-ZŁŚŻŹĆĘĄÓŃ][a-ząćęłńóśźż]+)']:
                m = re.search(pat, text)
                if m:
                    cd.powod_imie_nazwisko = m.group(1)
                    break

        if not cd.pozwany_nazwa:
            for pat in [r'(?:pożyczkodawc\w+|kredytodawc\w+|bank\w*)[:\s]+([A-ZŁŚŻŹĆĘĄÓŃ][\w\s\.]+(?:S\.A\.|sp\.\s*z\s*o\.o\.|Bank\w*))',
                        r'([\w\s]+(?:Bank|S\.A\.)[\w\s]*?)(?:,|\sz\s+siedzibą)']:
                m = re.search(pat, text)
                if m:
                    cd.pozwany_nazwa = m.group(1).strip()
                    break

        if not cd.powod_pesel:
            m = re.search(r'PESEL[:\s]*(\d{11})', text)
            if m:
                cd.powod_pesel = m.group(1)

    def _extract_from_certificate(self, ctx: CaseContext):
        """Extract from bank certificate (zaświadczenie) — handles OCR uppercase output."""
        text = ctx.all_texts.get(DocumentType.ZASWIADCZENIE.value, '')
        if not text or len(text) < 100:
            return
        cd = ctx.credit_data
        text_upper = text.upper()

        # OCR pattern: "SPŁACONE ODSETKI 28 030,67" or "SPŁACONE ODSETKI: 28 030,67"
        for field, patterns in [
            ('suma_odsetek_zaplaconych', [r'SP[ŁL]ACONE\s+ODSETKI\s+\S*\s*([\d][\d\s]+[.,]\d{2})', r'ODSETKI\s+ZAP[ŁL]ACONE\s+\S*\s*([\d][\d\s]+[.,]\d{2})']),
            ('suma_kapitalu_splaconego', [r'SP[ŁL]ACONY\s+KAPITA[ŁL]\s+\S*\s*([\d][\d\s]+[.,]\d{2})', r'KAPITA[ŁL]\s+SP[ŁL]ACONY\s+\S*\s*([\d][\d\s]+[.,]\d{2})']),
            ('suma_prowizji_zaplaconej', [r'PROWIZJA\s+ZA\s+UDZIELENIE[^0-9]+([\d][\d\s]+[.,]\d{2})', r'PROWIZJA[:\s]+([\d][\d\s]+[.,]\d{2})\s*(?:PLN|Z[ŁL])?']),
        ]:
            if getattr(cd, field, None):
                continue
            for pat in patterns:
                m = re.search(pat, text_upper)
                if m:
                    val = m.group(1).replace(' ', '').replace(',', '.')
                    setattr(cd, field, val)
                    break

        # Extract last payment date from the payment table
        # OCR: "14.07.2025 SPŁATA WYMAGALNYCH ODSETEK" — find the LAST date before a SPŁATA line
        if not cd.data_ostatniej_wplaty:
            payment_dates = re.findall(r'(\d{2}[./]\d{2}[./]\d{4})\s+SP[ŁL]ATA', text_upper)
            if payment_dates:
                cd.data_ostatniej_wplaty = payment_dates[-1].replace('/', '.')

        # Extract the period from header: "od 01.02.2024 r. do 29.06.2025 r."
        m = re.search(r'od\s+(\d{2}[./]\d{2}[./]\d{4})\s*r?\.\s*do\s+(\d{2}[./]\d{2}[./]\d{4})', text, re.I)
        if m:
            if not cd.okres_odsetek_od:
                cd.okres_odsetek_od = m.group(1).replace('/', '.')

        # Extract zaświadczenie date and number
        m = re.search(r'Nr\s+pisma[:\s]+(\S+)', text)
        if m and not cd.historia_wplat_summary:
            cd.historia_wplat_summary = m.group(1)

    def _extract_from_schedule(self, ctx: CaseContext):
        """Extract from payment schedule (harmonogram)."""
        text = ctx.all_texts.get(DocumentType.HARMONOGRAM.value, '')
        if not text:
            return
        cd = ctx.credit_data

        dates = re.findall(r'(\d{1,2}[./\-]\d{1,2}[./\-]\d{4})', text)
        if dates:
            if not cd.data_pierwszej_raty:
                cd.data_pierwszej_raty = dates[0].replace('/', '.').replace('-', '.')
            if not cd.data_ostatniej_raty and len(dates) > 1:
                cd.data_ostatniej_raty = dates[-1].replace('/', '.').replace('-', '.')

    def _extract_from_demand_letter(self, ctx: CaseContext):
        """Extract from demand for payment (wezwanie do zapłaty) — handles OCR output."""
        text = ctx.all_texts.get(DocumentType.WEZWANIE.value, '')
        if not text or len(text) < 100:
            return
        cd = ctx.credit_data

        # Extract the demand letter date (e.g., "Łódź, dnia 07 sierpnia 2025 r.")
        PL_MONTHS = {
            'stycznia': '01', 'lutego': '02', 'marca': '03', 'kwietnia': '04',
            'maja': '05', 'czerwca': '06', 'lipca': '07', 'sierpnia': '08',
            'września': '09', 'października': '10', 'listopada': '11', 'grudnia': '12',
        }
        if not cd.data_wezwania_do_zaplaty:
            # Find ALL Polish dates in the text, take the EARLIEST one by position (header date)
            all_date_matches = []
            for month_name, month_num in PL_MONTHS.items():
                for m in re.finditer(rf'(\d{{1,2}})\s+{month_name}\s+(\d{{4}})', text):
                    date_str = f'{m.group(1).zfill(2)}.{month_num}.{m.group(2)}'
                    all_date_matches.append((m.start(), date_str))
            if all_date_matches:
                all_date_matches.sort(key=lambda x: x[0])
                cd.data_wezwania_do_zaplaty = all_date_matches[0][1]
            else:
                dates = re.findall(r'(\d{1,2}[./\-]\d{1,2}[./\-]\d{4})', text)
                if dates:
                    cd.data_wezwania_do_zaplaty = dates[0].replace('/', '.').replace('-', '.')

        # Extract claim amounts from wezwanie text
        # Pattern: "kwoty 28 030,67 zł tytułem zwrotu bezpodstawnie uiszczonych odsetek"
        if not cd.kwota_odsetek_zaplaconych:
            m = re.search(r'[Kk]wot[yę]\s+([\d\s]+[.,]\d{2})\s*z[łl]\s+tytu[łl]em\s+zwrotu.*?odsetek', text)
            if m:
                cd.kwota_odsetek_zaplaconych = m.group(1).replace(' ', '').replace(',', '.')

        # Pattern: "kwoty 20 435,18 zł tytułem zwrotu bezpodstawnie uiszczonej prowizji"
        if not cd.suma_prowizji_zaplaconej:
            m = re.search(r'[Kk]wot[yę]\s+([\d\s]+[.,]\d{2})\s*z[łl]\s+tytu[łl]em\s+zwrotu.*?prowizj', text)
            if m:
                cd.suma_prowizji_zaplaconej = m.group(1).replace(' ', '').replace(',', '.')

        # Pattern: "łącznie 48 465,85 zł" or "kwoty 48 465,85 zł"
        if not cd.kwota_roszczenia:
            m = re.search(r'[łl][aą]cznie\s+([\d\s]+[.,]\d{2})\s*z[łl]', text)
            if m:
                cd.kwota_roszczenia = m.group(1).replace(' ', '').replace(',', '.')

        # Extract interest period from wezwanie: "za okres od dnia 01.02.2025 r. do dnia 14.07.2025 r."
        m = re.search(r'(?:za\s+)?okres\s+od\s+(?:dnia\s+)?(\d{1,2}[./]\d{1,2}[./]\d{4})\s*r?\.\s*do\s+(?:dnia\s+)?(\d{1,2}[./]\d{1,2}[./]\d{4})', text, re.I)
        if m:
            if not cd.okres_odsetek_od:
                cd.okres_odsetek_od = m.group(1).replace('/', '.')
            if not cd.okres_odsetek_do:
                cd.okres_odsetek_do = m.group(2).replace('/', '.')

    def _extract_from_skd_statement(self, ctx: CaseContext):
        """Extract from SKD statement (oświadczenie SKD)."""
        text = ctx.all_texts.get(DocumentType.OSWIADCZENIE_SKD.value, '')
        if not text:
            return
        cd = ctx.credit_data

        if not cd.data_oswiadczenia_skd:
            dates = re.findall(r'(\d{1,2}[./\-]\d{1,2}[./\-]\d{4})', text)
            if dates:
                cd.data_oswiadczenia_skd = dates[0].replace('/', '.').replace('-', '.')

    # ============================================================
    # Phase 2: AI extraction
    # ============================================================

    def _ai_extract(self, ctx: CaseContext, docs: list[ClassifiedDocument]):
        """Use Claude to extract structured data from all documents."""
        documents_block = self._format_documents_block(docs)
        prompt = MULTI_DOC_EXTRACTION_PROMPT.format(documents_block=documents_block)
        extracted = self._call_ai(prompt)
        if 'error' in extracted:
            ctx.warnings.append({"message": f"Ostrzeżenie AI: {extracted.get('error')}"})
            return

        ai_cd = self._map_extracted_to_credit_data(extracted)

        # Merge: AI fills gaps that regex missed, but regex values take priority
        # (regex is deterministic, AI might hallucinate)
        cd = ctx.credit_data
        from dataclasses import fields as dc_fields
        for f in dc_fields(cd):
            existing = getattr(cd, f.name)
            ai_val = getattr(ai_cd, f.name, None)
            if existing is None and ai_val is not None:
                setattr(cd, f.name, ai_val)
                ctx.resolution_log.append({
                    'field': f.name, 'value': ai_val,
                    'method': 'ai', 'source': 'claude',
                })

        ctx.cross_doc_discrepancies = extracted.get('rozbieznosci_miedzy_dokumentami', [])
        ctx.violations = extracted.get('naruszenia_art30', [])
        ctx.timeline = self._build_timeline(extracted)

    def _ai_violations(self, ctx: CaseContext):
        """Deep violation analysis via AI."""
        cd_dict = {}
        from dataclasses import fields as dc_fields
        for f in dc_fields(ctx.credit_data):
            v = getattr(ctx.credit_data, f.name)
            if v is not None:
                cd_dict[f.name] = v

        case_json = json.dumps(cd_dict, ensure_ascii=False, indent=2)
        if len(case_json) > 25000:
            case_json = case_json[:25000]

        prompt = VIOLATION_DEEP_ANALYSIS_PROMPT.format(case_context_json=case_json)
        result = self._call_ai(prompt)
        if result and 'error' not in result:
            if result.get('naruszenia_potwierdzone'):
                ctx.violations = result['naruszenia_potwierdzone']
            if result.get('naruszenia_prawdopodobne'):
                ctx.warnings.extend(result['naruszenia_prawdopodobne'])

    # ============================================================
    # Phase 3: Cross-document derived fields
    # ============================================================

    def _derive_missing_fields(self, ctx: CaseContext):
        """Calculate fields that can be derived from other available data."""
        cd = ctx.credit_data

        # Derive kwota_pozyczki = calkowita_kwota_kredytu + prowizja + ubezpieczenie
        if not cd.kwota_pozyczki and cd.calkowita_kwota_kredytu and cd.prowizja:
            try:
                ckk = self._to_float(cd.calkowita_kwota_kredytu)
                prow = self._to_float(cd.prowizja)
                ubez = self._to_float(cd.ubezpieczenie) if cd.ubezpieczenie else 0
                cd.kwota_pozyczki = f"{ckk + prow + ubez:.2f}"
                ctx.resolution_log.append({
                    'field': 'kwota_pozyczki',
                    'value': cd.kwota_pozyczki,
                    'method': 'derived',
                    'source': 'CKK + prowizja + ubezpieczenie',
                })
            except (ValueError, TypeError):
                pass

        # Derive calkowita_kwota_kredytu = kwota_pozyczki - prowizja - ubezpieczenie
        if not cd.calkowita_kwota_kredytu and cd.kwota_pozyczki and cd.prowizja:
            try:
                kp = self._to_float(cd.kwota_pozyczki)
                prow = self._to_float(cd.prowizja)
                ubez = self._to_float(cd.ubezpieczenie) if cd.ubezpieczenie else 0
                cd.calkowita_kwota_kredytu = f"{kp - prow - ubez:.2f}"
                ctx.resolution_log.append({
                    'field': 'calkowita_kwota_kredytu',
                    'value': cd.calkowita_kwota_kredytu,
                    'method': 'derived',
                    'source': 'kwota_pożyczki - prowizja - ubezpieczenie',
                })
            except (ValueError, TypeError):
                pass

        # Derive kwota_roszczenia from zaświadczenie data
        if not cd.kwota_roszczenia:
            prowizja = self._to_float(cd.suma_prowizji_zaplaconej or cd.prowizja)
            odsetki = self._to_float(cd.suma_odsetek_zaplaconych or cd.kwota_odsetek_zaplaconych)
            if prowizja and odsetki:
                cd.kwota_roszczenia = f"{prowizja + odsetki:.2f}"
                ctx.resolution_log.append({
                    'field': 'kwota_roszczenia',
                    'value': cd.kwota_roszczenia,
                    'method': 'derived',
                    'source': 'prowizja + odsetki zapłacone',
                })

        # Derive kwota_roszczenia_slownie
        if cd.kwota_roszczenia and not cd.kwota_roszczenia_slownie:
            cd.kwota_roszczenia_slownie = _kwota_slownie(cd.kwota_roszczenia)

        # Derive WPS
        if cd.kwota_roszczenia and not cd.wps:
            cd.wps = cd.kwota_roszczenia

        # Derive opłata sądowa (5% of WPS, min 30, max 100000)
        if cd.wps and not cd.oplata:
            try:
                wps = self._to_float(cd.wps)
                import math
                oplata = math.ceil(wps * 0.05)
                oplata = max(30, min(oplata, 100000))
                cd.oplata = str(oplata)
            except (ValueError, TypeError):
                pass

        # data_wymagalnosci is derived by golden rules (wezwanie + 3 days)

        # Copy odsetki from zaświadczenie if missing
        if not cd.kwota_odsetek_zaplaconych and cd.suma_odsetek_zaplaconych:
            cd.kwota_odsetek_zaplaconych = cd.suma_odsetek_zaplaconych

        # Derive period dates
        if not cd.okres_odsetek_od and cd.data_zawarcia_umowy:
            cd.okres_odsetek_od = cd.data_zawarcia_umowy
        if not cd.okres_odsetek_do and cd.data_ostatniej_wplaty:
            cd.okres_odsetek_do = cd.data_ostatniej_wplaty

    # ============================================================
    # Phase 5: Financial validation enrichment
    # ============================================================

    def _apply_financial_to_credit_data(self, ctx: CaseContext, fv: dict):
        cd = ctx.credit_data
        if fv.get('odsetki_od_kredytowanych_kosztow') and not cd.odsetki_od_kredytowanych_kosztow:
            cd.odsetki_od_kredytowanych_kosztow = str(fv['odsetki_od_kredytowanych_kosztow'])
        # DO NOT override hipotetyczna_rata — golden rules set it correctly from Gofin+prowizja
        if fv.get('calkowity_koszt_prawidlowy'):
            cd.hipotetyczny_calkowity_koszt = str(fv['calkowity_koszt_prawidlowy'])
        if fv.get('calkowita_do_zaplaty_prawidlowa'):
            cd.calkowita_kwota_do_zaplaty_prawidlowa = str(fv['calkowita_do_zaplaty_prawidlowa'])
            cd.hipotetyczna_calkowita_do_zaplaty = str(fv['calkowita_do_zaplaty_prawidlowa'])
        for col_key, cd_field, diff_field in [
            ('rrso_col3', 'rrso_kolumna3', 'rrso_kolumna3_roznica'),
            ('rrso_col4', 'rrso_kolumna4', 'rrso_kolumna4_roznica'),
            ('rrso_col5', 'rrso_kolumna5', 'rrso_kolumna5_roznica'),
        ]:
            col = fv.get(col_key)
            if col:
                setattr(cd, cd_field, col.get('rrso_percent', col.get('rrso_value')))
            diff_key = f'roznica_{col_key}'
            if fv.get(diff_key) is not None:
                setattr(cd, diff_field, str(fv[diff_key]))

    # ============================================================
    # Phase 6: Generate questions for ambiguous fields
    # ============================================================

    def _generate_questions(self, ctx: CaseContext):
        """Generate questions for fields that couldn't be resolved."""
        cd = ctx.credit_data
        questions = []

        # Critical fields that MUST be filled
        critical_fields = [
            ('powod_imie_nazwisko', 'Nie udało się ustalić imienia i nazwiska powoda (kredytobiorcy). Proszę podać imię i nazwisko kredytobiorcy.'),
            ('pozwany_nazwa', 'Nie udało się ustalić pełnej nazwy pozwanego (banku/pożyczkodawcy). Proszę podać pełną nazwę banku z formą prawną (np. "PKO Bank Polski S.A.").'),
            ('data_zawarcia_umowy', 'Nie udało się ustalić daty zawarcia umowy kredytowej. Proszę podać datę w formacie DD.MM.RRRR.'),
            ('calkowita_kwota_kredytu', 'Nie udało się ustalić całkowitej kwoty kredytu (CKK - kwoty do dyspozycji konsumenta). Proszę podać kwotę.'),
            ('kwota_pozyczki', 'Nie udało się ustalić kwoty pożyczki/kredytu (CKK + skredytowane koszty). Proszę podać kwotę z umowy.'),
            ('prowizja', 'Nie udało się ustalić kwoty prowizji. Proszę podać kwotę prowizji z umowy.'),
            ('oprocentowanie', 'Nie udało się ustalić oprocentowania nominalnego. Proszę podać wartość procentową (np. "7.9").'),
            ('rrso_bank', 'Nie udało się ustalić RRSO wskazanego przez bank. Proszę podać wartość procentową z umowy.'),
            ('liczba_rat', 'Nie udało się ustalić liczby rat. Proszę podać liczbę rat z umowy.'),
        ]

        # Ambiguity: prowizja from umowa vs zaświadczenie
        if cd.prowizja and cd.suma_prowizji_zaplaconej:
            try:
                p1 = self._to_float(cd.prowizja)
                p2 = self._to_float(cd.suma_prowizji_zaplaconej)
                if p1 and p2 and abs(p1 - p2) > 0.01:
                    questions.append(UserQuestion(
                        question_id=str(uuid.uuid4())[:8],
                        field_name='prowizja_source',
                        question_pl=(
                            f"Prowizja w umowie: {cd.prowizja} zł, "
                            f"prowizja w zaświadczeniu bankowym: {cd.suma_prowizji_zaplaconej} zł. "
                            f"Która wartość jest prawidłowa do pozwu?"
                        ),
                        options=[
                            f"Z umowy: {cd.prowizja} zł",
                            f"Z zaświadczenia: {cd.suma_prowizji_zaplaconej} zł",
                        ],
                        severity='important',
                    ))
            except (ValueError, TypeError):
                pass

        for field_name, question_text in critical_fields:
            if getattr(cd, field_name, None) is None:
                questions.append(UserQuestion(
                    question_id=str(uuid.uuid4())[:8],
                    field_name=field_name,
                    question_pl=question_text,
                    severity='blocking',
                ))

        # Processual dates
        processual = [
            ('data_oswiadczenia_skd', 'Proszę podać datę złożenia oświadczenia o skorzystaniu z sankcji kredytu darmowego (art. 45 u.k.k.).'),
            ('data_wezwania_do_zaplaty', 'Proszę podać datę wysłania wezwania do zapłaty do banku.'),
            ('sad', 'Proszę wskazać właściwy sąd (np. "Rejonowy dla Łodzi-Śródmieścia w Łodzi, I Wydział Cywilny").'),
        ]
        for field_name, q in processual:
            if getattr(cd, field_name, None) is None:
                questions.append(UserQuestion(
                    question_id=str(uuid.uuid4())[:8],
                    field_name=field_name,
                    question_pl=q,
                    severity='important',
                ))

        ctx.pending_questions = questions

    # ============================================================
    # Phase 4: Apply user answers
    # ============================================================

    def _apply_user_answers(self, ctx: CaseContext, answers: dict):
        cd = ctx.credit_data
        for field_name, value in answers.items():
            if hasattr(cd, field_name) and value:
                setattr(cd, field_name, str(value))
                ctx.resolution_log.append({
                    'field': field_name, 'value': str(value),
                    'method': 'user_answer', 'source': 'manual',
                })

        # Re-derive after applying answers
        self._derive_missing_fields(ctx)

        # Clear answered questions
        answered_fields = set(answers.keys())
        ctx.pending_questions = [
            q for q in ctx.pending_questions
            if q.field_name not in answered_fields
        ]

    # ============================================================
    # Helpers
    # ============================================================

    def _check_missing_documents(self, ctx: CaseContext):
        found_types = {doc.doc_type for doc in ctx.classified_docs}
        for req_type in REQUIRED_DOCUMENTS:
            if req_type not in found_types:
                ctx.missing_documents.append(req_type)
                ctx.critical_errors.append(
                    f"BRAK WYMAGANEGO DOKUMENTU: {DOC_TYPE_LABELS[req_type]}"
                )

    def _format_documents_block(self, docs: list[ClassifiedDocument]) -> str:
        blocks = []
        for doc in docs:
            label = DOC_TYPE_LABELS.get(doc.doc_type, doc.doc_type.value)
            text = doc.extracted_text
            if len(text) > 12000:
                text = text[:12000] + f"\n[...skrócono, pominięto {len(doc.extracted_text) - 12000} znaków]"
            blocks.append(
                f"=== DOKUMENT: {doc.filename} ===\n"
                f"TYP: {label}\n"
                f"PEWNOŚĆ: {doc.confidence}\n---\n{text}\n"
                f"=== KONIEC ===\n"
            )
        return "\n\n".join(blocks)

    def _call_ai(self, prompt: str) -> dict:
        if not self.client:
            return {"error": "Brak klienta API"}
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8192,
                system=SYSTEM_PROMPT_MULTI_DOC,
                messages=[{"role": "user", "content": prompt}],
            )
            return self._parse_json(response.content[0].text)
        except Exception as e:
            return {"error": str(e)}

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1]
            text = text.rsplit('```', 1)[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
            return {"error": "JSON parse error", "raw": text[:2000]}

    def _map_extracted_to_credit_data(self, extracted: dict) -> CreditData:
        cd = CreditData()

        def v(section, key):
            s = extracted.get(section, {})
            entry = s.get(key, {})
            val = entry.get('wartosc', '') if isinstance(entry, dict) else str(entry)
            if val and str(val).upper() not in ('BRAK_DANYCH', 'NONE', 'N/A', ''):
                return str(val)
            return None

        cd.powod_imie_nazwisko = v('dane_stron', 'kredytobiorca_imie_nazwisko')
        cd.powod_adres = v('dane_stron', 'kredytobiorca_adres')
        cd.powod_pesel = v('dane_stron', 'kredytobiorca_pesel')
        cd.pozwany_nazwa = v('dane_stron', 'kredytodawca_nazwa_pelna')
        cd.pozwany_siedziba = v('dane_stron', 'kredytodawca_siedziba')
        cd.pozwany_adres = v('dane_stron', 'kredytodawca_adres')
        cd.pozwany_krs = v('dane_stron', 'kredytodawca_krs')
        cd.numer_umowy = v('dane_umowy', 'numer_umowy')
        cd.data_zawarcia_umowy = v('dane_umowy', 'data_zawarcia')
        cd.typ_umowy = v('dane_umowy', 'typ_umowy')
        cd.kwota_pozyczki = v('dane_umowy', 'kwota_pozyczki')
        cd.calkowita_kwota_kredytu = v('dane_umowy', 'calkowita_kwota_kredytu')
        cd.calkowita_kwota_do_zaplaty = v('dane_umowy', 'calkowita_kwota_do_zaplaty')
        cd.calkowity_koszt_kredytu = v('dane_umowy', 'calkowity_koszt_kredytu')
        cd.oprocentowanie = v('dane_umowy', 'oprocentowanie_nominalne')
        cd.typ_oprocentowania = v('dane_umowy', 'typ_oprocentowania')
        cd.rrso_bank = v('dane_umowy', 'rrso')
        cd.liczba_rat = v('dane_umowy', 'liczba_rat')
        cd.kwota_raty = v('dane_umowy', 'kwota_raty')
        cd.dzien_platnosci_raty = v('dane_umowy', 'dzien_platnosci_raty')
        cd.prowizja = v('dane_umowy', 'prowizja')
        cd.ubezpieczenie = v('dane_umowy', 'ubezpieczenie')
        cd.suma_odsetek_bank = v('dane_umowy', 'suma_odsetek_umownych')
        cd.opis_kosztow_kredytowanych = v('dane_umowy', 'opis_kosztow_kredytowanych')
        cd.suma_odsetek_zaplaconych = v('dane_zaswiadczenia', 'suma_odsetek_zaplaconych')
        cd.suma_kapitalu_splaconego = v('dane_zaswiadczenia', 'suma_kapitalu_splaconego')
        cd.suma_prowizji_zaplaconej = v('dane_zaswiadczenia', 'suma_prowizji_zaplaconej')
        cd.data_ostatniej_wplaty = v('dane_zaswiadczenia', 'data_ostatniej_wplaty')
        cd.saldo_zadluzenia = v('dane_zaswiadczenia', 'saldo_zadluzenia')
        cd.data_pierwszej_raty = v('dane_harmonogramu', 'data_pierwszej_raty')
        cd.data_ostatniej_raty = v('dane_harmonogramu', 'data_ostatniej_raty')
        cd.harmonogram_raty_opis = v('dane_harmonogramu', 'raty_opis')
        cd.data_oswiadczenia_skd = v('przebieg_przedsadowy', 'data_oswiadczenia_skd')
        cd.data_reklamacji = v('przebieg_przedsadowy', 'data_reklamacji')
        cd.data_odpowiedzi_banku = v('przebieg_przedsadowy', 'data_odpowiedzi_banku')
        cd.data_wezwania_do_zaplaty = v('przebieg_przedsadowy', 'data_wezwania_do_zaplaty')
        cd.data_odbioru_wezwania = v('przebieg_przedsadowy', 'data_odbioru_wezwania')
        cd.data_wniosku_zaswiadczenie = v('przebieg_przedsadowy', 'data_wniosku_o_zaswiadczenie')
        cd.data_wymagalnosci = v('przebieg_przedsadowy', 'data_wezwania_do_zaplaty')
        cd.paragraf_rrso = v('paragrafy_naruszen', 'paragraf_rrso')
        cd.paragraf_calkowita_kwota = v('paragrafy_naruszen', 'paragraf_calkowita_kwota')
        cd.paragraf_wczesniejsza_splata = v('paragrafy_naruszen', 'paragraf_wczesniejsza_splata')
        cd.paragraf_ustep_wczesniejsza_splata = v('paragrafy_naruszen', 'ustep_wczesniejsza_splata')
        cd.paragraf_odstapienie = v('paragrafy_naruszen', 'paragraf_odstapienie')
        cd.paragraf_ustep_odstapienie = v('paragrafy_naruszen', 'ustep_odstapienie')
        cd.paragraf_zmiana_oplat = v('paragrafy_naruszen', 'paragraf_zmiana_oplat')
        cd.paragraf_prowizja_uiszczona = v('paragrafy_naruszen', 'paragraf_prowizja_uiszczona')

        kryteria = extracted.get('paragrafy_naruszen', {}).get('kryteria_zmiany_oplat', {})
        kv = kryteria.get('wartosc', []) if isinstance(kryteria, dict) else (kryteria if isinstance(kryteria, list) else [])
        if isinstance(kv, list):
            if len(kv) >= 1:
                cd.kryteria_zmiany_oplat_1 = str(kv[0])
            if len(kv) >= 2:
                cd.kryteria_zmiany_oplat_2 = str(kv[1])

        return cd

    def _build_timeline(self, extracted: dict) -> list[dict]:
        events = []
        for section, key, label in [
            ('dane_umowy', 'data_zawarcia', 'Zawarcie umowy'),
            ('przebieg_przedsadowy', 'data_oswiadczenia_skd', 'Oświadczenie SKD'),
            ('przebieg_przedsadowy', 'data_reklamacji', 'Reklamacja'),
            ('przebieg_przedsadowy', 'data_odpowiedzi_banku', 'Odpowiedź banku'),
            ('przebieg_przedsadowy', 'data_wniosku_o_zaswiadczenie', 'Wniosek o zaświadczenie'),
            ('przebieg_przedsadowy', 'data_wezwania_do_zaplaty', 'Wezwanie do zapłaty'),
            ('przebieg_przedsadowy', 'data_odbioru_wezwania', 'Odbiór wezwania'),
        ]:
            entry = extracted.get(section, {}).get(key, {})
            date_val = entry.get('wartosc', '') if isinstance(entry, dict) else str(entry)
            if date_val and date_val.upper() not in ('BRAK_DANYCH', 'NONE', ''):
                events.append({'date': date_val, 'event': label})
        return events

    def _to_float(self, val) -> Optional[float]:
        if val is None:
            return None
        try:
            s = str(val).replace(' ', '').replace('\xa0', '').replace(',', '.').replace('zł', '').replace('%', '').strip()
            return float(s) if s else None
        except (ValueError, AttributeError):
            return None


def _kwota_slownie(kwota_str: Optional[str]) -> Optional[str]:
    if not kwota_str:
        return None
    try:
        kwota = float(str(kwota_str).replace(' ', '').replace(',', '.'))
    except (ValueError, AttributeError):
        return None

    jednosci = ['', 'jeden', 'dwa', 'trzy', 'cztery', 'pięć', 'sześć', 'siedem', 'osiem', 'dziewięć']
    nastki = ['dziesięć', 'jedenaście', 'dwanaście', 'trzynaście', 'czternaście', 'piętnaście', 'szesnaście', 'siedemnaście', 'osiemnaście', 'dziewiętnaście']
    dziesiatki = ['', 'dziesięć', 'dwadzieścia', 'trzydzieści', 'czterdzieści', 'pięćdziesiąt', 'sześćdziesiąt', 'siedemdziesiąt', 'osiemdziesiąt', 'dziewięćdziesiąt']
    setki = ['', 'sto', 'dwieście', 'trzysta', 'czterysta', 'pięćset', 'sześćset', 'siedemset', 'osiemset', 'dziewięćset']

    def _grupa(n):
        s, d, j = n // 100, (n % 100) // 10, n % 10
        parts = []
        if s: parts.append(setki[s])
        if d == 1: parts.append(nastki[j])
        else:
            if d: parts.append(dziesiatki[d])
            if j: parts.append(jednosci[j])
        return ' '.join(parts)

    zlote = int(kwota)
    grosze = round((kwota - zlote) * 100)

    if zlote == 0:
        result = 'zero'
    else:
        parts = []
        tysiace = zlote // 1000
        reszta = zlote % 1000
        if tysiace:
            if tysiace == 1: parts.append('tysiąc')
            elif 2 <= tysiace % 10 <= 4 and not (12 <= tysiace % 100 <= 14):
                parts.append(f'{_grupa(tysiace)} tysiące')
            else:
                parts.append(f'{_grupa(tysiace)} tysięcy')
        if reszta:
            parts.append(_grupa(reszta))
        result = ' '.join(parts)

    return f"{result} złotych {grosze:02d}/100"
