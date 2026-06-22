"""
Golden Standard Extraction Rules.
Deterministic field resolution rules reverse-engineered from the Brzeziński case.
These rules encode exactly HOW a lawyer fills each field in an SKD lawsuit.
"""
import math
import re
from dataclasses import fields as dc_fields
from datetime import datetime, timedelta
from typing import Optional

from app.models.schema import CaseContext, CreditData, DocumentType


# Known Polish bank data for automatic lookup
BANK_REGISTRY = {
    'pko': {
        'nazwa_pelna': 'Powszechna Kasa Oszczędności Bank Polski Spółka Akcyjna',
        'nazwa_skrot': 'PKO Bank Polski S.A.',
        'krs': '0000026438',
        'siedziba': 'Warszawa',
        'adres': 'ul. Puławska 15, 02-515 Warszawa',
    },
    'mbank': {
        'nazwa_pelna': 'mBank Spółka Akcyjna',
        'nazwa_skrot': 'mBank S.A.',
        'krs': '0000025237',
        'siedziba': 'Warszawa',
        'adres': 'ul. Prosta 18, 00-850 Warszawa',
    },
    'ing': {
        'nazwa_pelna': 'ING Bank Śląski Spółka Akcyjna',
        'nazwa_skrot': 'ING Bank Śląski S.A.',
        'krs': '0000005459',
        'siedziba': 'Katowice',
        'adres': 'ul. Sokolska 34, 40-086 Katowice',
    },
    'santander': {
        'nazwa_pelna': 'Santander Bank Polska Spółka Akcyjna',
        'nazwa_skrot': 'Santander Bank Polska S.A.',
        'krs': '0000008723',
        'siedziba': 'Warszawa',
        'adres': 'al. Jana Pawła II 17, 00-854 Warszawa',
    },
    'bnp': {
        'nazwa_pelna': 'BNP Paribas Bank Polska Spółka Akcyjna',
        'nazwa_skrot': 'BNP Paribas Bank Polska S.A.',
        'krs': '0000011571',
        'siedziba': 'Warszawa',
        'adres': 'ul. Kasprzaka 2, 01-211 Warszawa',
    },
    'millennium': {
        'nazwa_pelna': 'Bank Millennium Spółka Akcyjna',
        'nazwa_skrot': 'Bank Millennium S.A.',
        'krs': '0000010186',
        'siedziba': 'Warszawa',
        'adres': 'ul. Stanisława Żaryna 2A, 02-593 Warszawa',
    },
    'alior': {
        'nazwa_pelna': 'Alior Bank Spółka Akcyjna',
        'nazwa_skrot': 'Alior Bank S.A.',
        'krs': '0000305178',
        'siedziba': 'Warszawa',
        'adres': 'ul. Łopuszańska 38D, 02-232 Warszawa',
    },
    'pekao': {
        'nazwa_pelna': 'Bank Polska Kasa Opieki Spółka Akcyjna',
        'nazwa_skrot': 'Bank Pekao S.A.',
        'krs': '0000014843',
        'siedziba': 'Warszawa',
        'adres': 'ul. Grzybowska 53/57, 00-844 Warszawa',
    },
    'credit_agricole': {
        'nazwa_pelna': 'Credit Agricole Bank Polska Spółka Akcyjna',
        'nazwa_skrot': 'Credit Agricole Bank Polska S.A.',
        'krs': '0000039887',
        'siedziba': 'Wrocław',
        'adres': 'pl. Orląt Lwowskich 1, 53-605 Wrocław',
    },
    'velobank': {
        'nazwa_pelna': 'VeloBank Spółka Akcyjna',
        'nazwa_skrot': 'VeloBank S.A.',
        'krs': '0000991173',
        'siedziba': 'Warszawa',
        'adres': 'Rondo Ignacego Daszyńskiego 2C, 00-843 Warszawa',
    },
    'getin': {
        'nazwa_pelna': 'VeloBank Spółka Akcyjna (dawniej Getin Noble Bank S.A.)',
        'nazwa_skrot': 'VeloBank S.A.',
        'krs': '0000991173',
        'siedziba': 'Warszawa',
        'adres': 'Rondo Ignacego Daszyńskiego 2C, 00-843 Warszawa',
    },
    'noble': {
        'nazwa_pelna': 'VeloBank Spółka Akcyjna (dawniej Getin Noble Bank S.A.)',
        'nazwa_skrot': 'VeloBank S.A.',
        'krs': '0000991173',
        'siedziba': 'Warszawa',
        'adres': 'Rondo Ignacego Daszyńskiego 2C, 00-843 Warszawa',
    },
}


def apply_golden_rules(ctx: CaseContext):
    """
    Apply deterministic rules learned from the golden standard case.
    Call AFTER regex/AI extraction to fill derived and calculated fields.
    """
    cd = ctx.credit_data

    _resolve_bank_data(cd)
    _extract_dates_from_filenames(cd, ctx)
    _apply_bank_specific_defaults(cd)
    _derive_financial_fields(cd, ctx)
    _derive_claim_amount(cd, ctx)
    _derive_wps_and_fee(cd)
    _derive_court(cd)
    _derive_processual_dates(cd)
    _extract_rrso_from_excel(cd, ctx)
    _extract_rates_from_excel(cd, ctx)
    _set_today_if_missing(cd)


def _resolve_bank_data(cd: CreditData):
    """Lookup bank details from registry by partial name match."""
    if not cd.pozwany_nazwa:
        return

    name_lower = cd.pozwany_nazwa.lower()
    for key, data in BANK_REGISTRY.items():
        if key in name_lower or data['nazwa_skrot'].lower() in name_lower or data['nazwa_pelna'].lower() in name_lower:
            if not cd.pozwany_krs:
                cd.pozwany_krs = data['krs']
            if not cd.pozwany_siedziba:
                cd.pozwany_siedziba = data['siedziba']
            if not cd.pozwany_adres:
                cd.pozwany_adres = data['adres']
            break


def _extract_dates_from_filenames(cd: CreditData, ctx: CaseContext):
    """Extract processual dates from document filenames and text content."""
    PL_MONTHS = {
        'stycznia': '01', 'lutego': '02', 'marca': '03', 'kwietnia': '04',
        'maja': '05', 'czerwca': '06', 'lipca': '07', 'sierpnia': '08',
        'września': '09', 'października': '10', 'listopada': '11', 'grudnia': '12',
    }

    def _normalize(s):
        """Normalize Polish characters for matching."""
        return s.lower().replace('ś', 's').replace('ż', 'z').replace('ź', 'z').replace('ć', 'c').replace('ą', 'a').replace('ę', 'e').replace('ł', 'l').replace('ó', 'o').replace('ń', 'n')

    for doc in ctx.classified_docs:
        fn_raw = doc.filename
        fn = _normalize(fn_raw)
        text = doc.extracted_text

        is_oswiadczenie = 'oswiadczenie' in fn or 'skd' in fn
        is_wniosek = 'wniosek' in fn
        is_zaswiadczenie_req = 'zaswiadczenie' in fn or 'zaświadczenie' in fn_raw.lower()
        is_wezwanie = 'wezwanie' in fn
        is_odpowiedz = 'odpowiedz' in fn

        # Parse Polish date from TEXT like "Krzepice, dnia 11 czerwca 2025 r."
        for month_name, month_num in PL_MONTHS.items():
            m = re.search(rf'(\d{{1,2}})\s+{month_name}\s+(\d{{4}})', text)
            if m:
                parsed = f'{m.group(1).zfill(2)}.{month_num}.{m.group(2)}'
                if is_oswiadczenie and not is_wniosek:
                    cd.data_oswiadczenia_skd = parsed  # text date overrides any previous value
                if is_wniosek and not cd.data_wniosku_zaswiadczenie:
                    cd.data_wniosku_zaswiadczenie = parsed
                break

        # Parse date from FILENAME like "07.05.25 r." or "11.06.25 r."
        dm = re.search(r'(\d{1,2})[.\s]+(\d{1,2})[.\s]+(\d{2,4})\s*r?\.?', fn_raw)
        if dm:
            d, mo, y = dm.groups()
            y = f'20{y}' if len(y) == 2 else y
            date_str = f'{d.zfill(2)}.{mo.zfill(2)}.{y}'

            if is_oswiadczenie and not is_wniosek:
                cd.data_oswiadczenia_skd = date_str  # filename date always overrides OCR
            elif is_wniosek and not cd.data_wniosku_zaswiadczenie:
                cd.data_wniosku_zaswiadczenie = date_str
            elif is_wezwanie and not cd.data_wezwania_do_zaplaty:
                cd.data_wezwania_do_zaplaty = date_str
            elif is_odpowiedz and not cd.data_odpowiedzi_banku:
                cd.data_odpowiedzi_banku = date_str

    # typ_umowy defaults to "pożyczki" for SKD cases
    if not cd.typ_umowy:
        cd.typ_umowy = 'pożyczki'

    # ubezpieczenie defaults to "0" ONLY if no document mentions insurance at all
    if not cd.ubezpieczenie:
        has_insurance_mention = False
        for doc in ctx.classified_docs:
            t = doc.extracted_text.lower()
            if any(kw in t for kw in ['ubezpiecz', 'składk', 'pakiet spokojna', 'insurance']):
                has_insurance_mention = True
                break
        if not has_insurance_mention:
            cd.ubezpieczenie = '0'

    # okres_odsetek_od = data_pierwszej_raty (from Excel payment schedule)
    if not cd.okres_odsetek_od and cd.data_pierwszej_raty:
        cd.okres_odsetek_od = cd.data_pierwszej_raty


# Standard paragraph references for each bank's contract template
PKO_PARAGRAPHS = {
    'paragraf_rrso': '§ 1 ust. 7 i 8 Umowy, oraz załącznik do Umowy',
    'paragraf_calkowita_kwota': '§ 1 ust. 2 pkt. 1',
    'paragraf_wczesniejsza_splata': '§ 6',
    'paragraf_ustep_wczesniejsza_splata': '1',
    'paragraf_odstapienie': '§ 9',
    'paragraf_ustep_odstapienie': '1',
    'paragraf_zmiana_oplat': '§ 4',
    'paragraf_prowizja_uiszczona': '§ 1 ust. 3',
    'kryteria_zmiany_oplat_1': 'zmiany stopy referencyjnej NBP, zmiany przepisów prawa',
    'kryteria_zmiany_oplat_2': 'zmiany rekomendacji KNF, zmiany sytuacji rynkowej, zmiany kosztów operacyjnych',
}


VELO_GETIN_PARAGRAPHS = {
    'paragraf_rrso': '§ 2 Umowy',
    'paragraf_calkowita_kwota': '§ 1',
    'paragraf_wczesniejsza_splata': '§ 8',
    'paragraf_ustep_wczesniejsza_splata': '1',
    'paragraf_odstapienie': '§ 11',
    'paragraf_ustep_odstapienie': '1',
    'paragraf_zmiana_oplat': '§ 3',
    'paragraf_prowizja_uiszczona': '§ 1 ust. 4',
    'kryteria_zmiany_oplat_1': 'zmiany stopy referencyjnej NBP, zmiany przepisów prawa',
    'kryteria_zmiany_oplat_2': 'zmiany rekomendacji organów nadzoru, zmiany kosztów operacyjnych',
}


def _apply_bank_specific_defaults(cd: CreditData):
    """Apply known default paragraph references based on bank identity."""
    if not cd.pozwany_nazwa:
        return

    bank_lower = cd.pozwany_nazwa.lower()

    defaults = None
    if 'pko' in bank_lower or 'powszechna kasa' in bank_lower:
        defaults = PKO_PARAGRAPHS
        if not cd.typ_oprocentowania:
            cd.typ_oprocentowania = 'zmiennej'
    elif 'velo' in bank_lower or 'getin' in bank_lower or 'noble' in bank_lower:
        defaults = VELO_GETIN_PARAGRAPHS

    if defaults:
        for field_name, default_val in defaults.items():
            if hasattr(cd, field_name) and not getattr(cd, field_name, None):
                setattr(cd, field_name, default_val)


def _derive_financial_fields(cd: CreditData, ctx: CaseContext):
    """
    Rule: prowizja = kwota_pozyczki - CKK
    Rule: calkowity_koszt = calkowita_do_zaplaty - CKK
    Rule: suma_odsetek ≈ (rata * liczba_rat + pierwsza_rata_diff + ostatnia_rata_diff) - kwota_pozyczki
    Rule: odsetki_od_kred_kosztow = calkowity_koszt_bank - calkowity_koszt_prawidlowy
    Rule: hipotetyczny_calkowity_koszt = calkowity_koszt_bank - odsetki_od_kred_kosztow
    Rule: calkowita_kwota_do_zaplaty_prawidlowa = calkowita_do_zaplaty_bank - odsetki_od_kred_kosztow
    """
    kp = _f(cd.kwota_pozyczki)
    ckk = _f(cd.calkowita_kwota_kredytu)
    prow = _f(cd.prowizja)
    ubez = _f(cd.ubezpieczenie)
    nr = _f(cd.liczba_rat)
    rata = _f(cd.kwota_raty)

    # Derive prowizja
    if not prow and kp and ckk and kp > ckk:
        prow = kp - ckk - (ubez or 0)
        cd.prowizja = _fmt(prow)
        ctx.resolution_log.append({'field': 'prowizja', 'value': cd.prowizja,
                                    'method': 'golden_rule', 'source': 'kwota_pożyczki - CKK'})

    # Derive kwota_pozyczki
    if not kp and ckk and prow:
        kp = ckk + prow + (ubez or 0)
        cd.kwota_pozyczki = _fmt(kp)
        ctx.resolution_log.append({'field': 'kwota_pozyczki', 'value': cd.kwota_pozyczki,
                                    'method': 'golden_rule', 'source': 'CKK + prowizja'})

    # Derive CKK
    if not ckk and kp and prow:
        ckk = kp - prow - (ubez or 0)
        cd.calkowita_kwota_kredytu = _fmt(ckk)

    # Derive suma_odsetek_bank from Excel payment schedule
    # suma_odsetek = total_payments - kwota_pozyczki
    if not cd.suma_odsetek_bank and kp and rata and nr:
        # Approximate: most rates are standard, first/last may differ
        # For accuracy, use: first_rata + (nr-2)*standard_rata + last_rata - kwota_pozyczki
        first = _f(ctx.credit_data.data_pierwszej_raty)  # this is a date not amount
        # Use Excel-sourced harmonogram info
        total_payments = rata * nr  # approximate
        # Check if we have first/last rate from Excel data in resolution_log
        for entry in ctx.resolution_log:
            if entry.get('field') == 'rata_pierwsza':
                r1 = _f(entry['value'])
                rl = _f(cd.kwota_raty)  # last rata from Excel
                if r1 and rl:
                    # first_rata + (nr-2)*standard + last_rata
                    total_payments = r1 + (nr - 2) * rata + rl
                break

        suma_ods = total_payments - kp
        if suma_ods > 0:
            cd.suma_odsetek_bank = _fmt(suma_ods)

    # Derive calkowity_koszt from calkowita_do_zaplaty or from suma_odsetek + prowizja
    ckk_val = _f(cd.calkowita_kwota_kredytu)
    cdz = _f(cd.calkowita_kwota_do_zaplaty)
    ckk_koszt = _f(cd.calkowity_koszt_kredytu)

    if not ckk_koszt and cdz and ckk_val:
        ckk_koszt = cdz - ckk_val
        cd.calkowity_koszt_kredytu = _fmt(ckk_koszt)

    # Derive calkowity_koszt = suma_odsetek + prowizja + ubezpieczenie
    if not ckk_koszt and cd.suma_odsetek_bank and prow:
        suma_ods = _f(cd.suma_odsetek_bank)
        ckk_koszt = suma_ods + (prow or 0) + (ubez or 0)
        cd.calkowity_koszt_kredytu = _fmt(ckk_koszt)

    # Derive calkowita_kwota_do_zaplaty = CKK + calkowity_koszt
    if not cd.calkowita_kwota_do_zaplaty and ckk_val and ckk_koszt:
        cd.calkowita_kwota_do_zaplaty = _fmt(ckk_val + ckk_koszt)

    # Odsetki od kredytowanych kosztów:
    # Gofin rata (pure CKK monthly payment) is used to calculate:
    # hipotetyczna_rata = gofin_rata + prowizja/nr
    # odsetki_od_kred = calkowity_koszt_bank - (gofin_interest + prowizja)
    # We calculate gofin_rata from CKK and oprocentowanie, NOT from cd.hipotetyczna_rata
    opr = _f(cd.oprocentowanie)
    if opr and opr > 1:
        opr = opr / 100
    rata_gofin = None
    if ckk_val and opr and nr and opr > 0:
        r_monthly = opr / 12
        rata_gofin = ckk_val * (r_monthly * (1 + r_monthly) ** nr) / ((1 + r_monthly) ** nr - 1)

    if rata_gofin and nr and ckk_val and ckk_koszt:
        # Method: odsetki_od_kred = total_interest_bank - total_interest_gofin
        total_interest_gofin = rata_gofin * nr - ckk_val
        calkowity_koszt_prawidlowy = total_interest_gofin + (prow or 0) + (ubez or 0)
        odsetki_kred = ckk_koszt - calkowity_koszt_prawidlowy

        if odsetki_kred > 0:
            cd.odsetki_od_kredytowanych_kosztow = _fmt(odsetki_kred)
            cd.hipotetyczny_calkowity_koszt = _fmt(calkowity_koszt_prawidlowy)
            cd.calkowita_kwota_do_zaplaty_prawidlowa = _fmt(ckk_val + calkowity_koszt_prawidlowy)
            cd.hipotetyczna_calkowita_do_zaplaty = cd.calkowita_kwota_do_zaplaty_prawidlowa

    # hipotetyczna_rata = Gofin_rata + prowizja/nr_rat (rata col4 logic)
    # This is the AUTHORITATIVE calculation — always override
    if rata_gofin and prow and nr:
        rata_z_prowizja = rata_gofin + prow / nr
        cd.hipotetyczna_rata = _fmt(rata_z_prowizja)


def _derive_claim_amount(cd: CreditData, ctx: CaseContext):
    """
    Rule: kwota_roszczenia = prowizja_z_zaswiadczenia + odsetki_z_zaswiadczenia
    Priority: zaświadczenie > umowa (zaświadczenie = actual payments)
    """
    prowizja = _f(cd.suma_prowizji_zaplaconej) or _f(cd.prowizja)
    odsetki = _f(cd.kwota_odsetek_zaplaconych) or _f(cd.suma_odsetek_zaplaconych)

    if prowizja and odsetki and not cd.kwota_roszczenia:
        total = prowizja + odsetki
        cd.kwota_roszczenia = _fmt(total)
        ctx.resolution_log.append({'field': 'kwota_roszczenia', 'value': cd.kwota_roszczenia,
                                    'method': 'golden_rule', 'source': 'prowizja + odsetki z zaświadczenia'})

    if cd.kwota_roszczenia and not cd.kwota_roszczenia_slownie:
        from app.services.context_engine import _kwota_slownie
        cd.kwota_roszczenia_slownie = _kwota_slownie(cd.kwota_roszczenia)


def _derive_wps_and_fee(cd: CreditData):
    """
    HARDCODED per golden standard:
    WPS = kwota_roszczenia (zapłata) + CKK (ustalenie)
    Opłata = ALWAYS 1000 zł (SKD cases)
    """
    # OPŁATA: always 1000 zł — hardcoded, non-negotiable
    cd.oplata = '1 000,00'

    roszczenie = _f(cd.kwota_roszczenia)
    ckk = _f(cd.calkowita_kwota_kredytu)

    if roszczenie and ckk:
        wps = roszczenie + ckk
        cd.wps = _fmt(wps)
    elif roszczenie and not cd.wps:
        cd.wps = cd.kwota_roszczenia


def _derive_court(cd: CreditData):
    """
    Rule: Sąd Rejonowy if WPS <= 100000, Sąd Okręgowy if WPS > 100000
    For SKD cases with kredytowane koszty, WPS is virtually always > 100000.
    If WPS is unknown, default to Okręgowy (CKK alone is usually > 100k).
    """
    if cd.sad:
        return

    wps = _f(cd.wps)
    ckk = _f(cd.calkowita_kwota_kredytu)
    siedziba = cd.pozwany_siedziba or 'Warszawa'

    # SKD cases: WPS = roszczenie + CKK. If CKK > 75000, WPS is certainly > 100000
    use_okregowy = (wps and wps > 100000) or (ckk and ckk > 75000)

    CITY_DECLENSION = {
        'warszawa': 'Warszawie', 'katowice': 'Katowicach',
        'wrocław': 'Wrocławiu', 'kraków': 'Krakowie', 'krakow': 'Krakowie',
        'poznań': 'Poznaniu', 'poznan': 'Poznaniu', 'gdańsk': 'Gdańsku',
        'łódź': 'Łodzi', 'lodz': 'Łodzi', 'szczecin': 'Szczecinie',
        'lublin': 'Lublinie', 'białystok': 'Białymstoku',
    }

    siedziba_lower = siedziba.lower()
    city_locative = CITY_DECLENSION.get(siedziba_lower, siedziba)

    if use_okregowy:
        cd.sad = f'Okręgowy w {city_locative}'
        cd.sad_wydzial = 'II Wydział Cywilny'
    elif wps:
        if 'warszaw' in siedziba_lower:
            cd.sad = 'Rejonowy dla Warszawy-Mokotowa w Warszawie'
        else:
            cd.sad = f'Rejonowy w {city_locative}'
        cd.sad_wydzial = 'I Wydział Cywilny'


def _derive_processual_dates(cd: CreditData):
    """
    Rule: data_wymagalnosci = data_wezwania + 3 dni
    Rule: okres_odsetek_od = data pierwszej raty
    Rule: okres_odsetek_do = data ostatniej raty in Excel (last installment before lawsuit)
    """
    if cd.data_wezwania_do_zaplaty and not cd.data_wymagalnosci:
        try:
            wezw = _parse_date(cd.data_wezwania_do_zaplaty)
            if wezw:
                cd.data_wymagalnosci = (wezw + timedelta(days=3)).strftime('%d.%m.%Y')
        except Exception:
            cd.data_wymagalnosci = cd.data_wezwania_do_zaplaty

    # okres_odsetek_od = first installment date (NOT disbursement date)
    if cd.data_pierwszej_raty:
        cd.okres_odsetek_od = cd.data_pierwszej_raty
    elif not cd.okres_odsetek_od and cd.data_zawarcia_umowy:
        cd.okres_odsetek_od = cd.data_zawarcia_umowy

    # okres_odsetek_do = last PAID installment date from zaświadczenie (NOT schedule end)
    # data_ostatniej_raty is the SCHEDULE end (e.g. 2032) — NEVER use for okres_odsetek_do
    # This field must come from zaświadczenie or data_ostatniej_wplaty only
    if not cd.okres_odsetek_do and cd.data_ostatniej_wplaty:
        cd.okres_odsetek_do = cd.data_ostatniej_wplaty

    # opis_kosztow_kredytowanych
    if not cd.opis_kosztow_kredytowanych and cd.prowizja:
        ubez = _f(cd.ubezpieczenie)
        if ubez and ubez > 0:
            cd.opis_kosztow_kredytowanych = f'prowizję w kwocie {cd.prowizja} zł oraz składki na ubezpieczenie w kwocie {cd.ubezpieczenie} zł'
        else:
            cd.opis_kosztow_kredytowanych = f'prowizję w kwocie {cd.prowizja} zł'

    # kwota_pozyczki słownie
    if cd.kwota_pozyczki and not cd.kwota_pozyczki_slownie:
        from app.services.context_engine import _kwota_slownie
        cd.kwota_pozyczki_slownie = _kwota_slownie(cd.kwota_pozyczki)


def _extract_rrso_from_excel(cd: CreditData, ctx: CaseContext):
    """
    Rule: RRSO values come DIRECTLY from Excel row 3.
    Col C (index 2) = RRSO bank / col1
    Col E (index 4) = RRSO col2
    Col G (index 6) = RRSO col3
    Col I (index 8) = RRSO col4
    Col K (index 10) = RRSO col5
    """
    excel_text = ctx.all_texts.get(DocumentType.INNE.value, '')
    # Also check for any classified Excel docs
    for doc in ctx.classified_docs:
        if doc.filename.endswith(('.xlsx', '.xls')):
            excel_text = doc.extracted_text
            break

    if not excel_text:
        return

    # RRSO values are stored in the structured extraction
    # Look for patterns like "0.17085..." or percentage values
    rrso_pattern = r'(?:RRSO|rrso)[^0-9]*?(0\.\d{5,}|\d{1,2}[.,]\d{2,}%?)'
    matches = re.findall(rrso_pattern, excel_text, re.I)

    # These are better handled by openpyxl in the pipeline - see _extract_excel_rrso_direct


def _extract_rates_from_excel(cd: CreditData, ctx: CaseContext):
    """
    Rule: First rate, standard rate, and last rate come from Excel payment schedule.
    These are needed for RRSO assumption descriptions in the lawsuit.
    """
    pass  # Handled by the Excel extraction pipeline


def _set_today_if_missing(cd: CreditData):
    """Set lawsuit date to today if not specified."""
    if not cd.data_pozwu:
        cd.data_pozwu = datetime.now().strftime('%d %B %Y r.').replace(
            'January', 'stycznia').replace('February', 'lutego').replace(
            'March', 'marca').replace('April', 'kwietnia').replace(
            'May', 'maja').replace('June', 'czerwca').replace(
            'July', 'lipca').replace('August', 'sierpnia').replace(
            'September', 'września').replace('October', 'października').replace(
            'November', 'listopada').replace('December', 'grudnia')


def extract_excel_rrso_direct(filepath: str) -> dict:
    """
    Extract ALL data from the Excel RRSO calculation file.
    This is the single most data-rich source: it contains kwota_pozyczki,
    prowizja, CKK, all RRSO values, all rate amounts, dates, and payment count.
    """
    try:
        import openpyxl
        from collections import Counter
        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb.active
        result = {}
        rows = list(ws.iter_rows(values_only=True))

        # === RRSO VALUES from row with decimals 0.01-1.0 ===
        rrso_cols = {2: 'col1', 4: 'col2', 6: 'col3', 8: 'col4', 10: 'col5'}
        for row_idx, row in enumerate(rows[:10]):
            if row is None or len(row) < 11:
                continue
            found = {}
            for col_idx, col_name in rrso_cols.items():
                if col_idx < len(row) and isinstance(row[col_idx], float) and 0.01 < row[col_idx] < 1.0:
                    found[col_name] = row[col_idx]
            if len(found) >= 3:
                bank_val = found.get('col1', found.get('col2'))
                if bank_val:
                    result['rrso_bank'] = f'{bank_val*100:.2f}'
                bank_pct = bank_val * 100 if bank_val else 0
                for cn, val in found.items():
                    if cn in ('col1', 'col2'):
                        continue
                    pct = val * 100
                    result[f'rrso_kolumna{cn[-1]}'] = f'{pct:.2f}%'
                    result[f'rrso_kolumna{cn[-1]}_roznica'] = f'{pct - bank_pct:.2f}'
                break

        # === KWOTA POZYCZKI and CKK from the Ck row (large negative number) ===
        for row in rows[4:10]:
            if row is None:
                continue
            # Col B (index 2) = Ck for method 1 (kwota_pozyczki), Col D (index 4) = Ck for method 2 (CKK)
            col_b = row[2] if len(row) > 2 else None
            col_d = row[4] if len(row) > 4 else None
            if isinstance(col_b, (int, float)) and col_b < -10000:
                result['kwota_pozyczki'] = _fmt(abs(col_b))
            if isinstance(col_d, (int, float)) and col_d < -10000:
                result['calkowita_kwota_kredytu'] = _fmt(abs(col_d))
            if result.get('kwota_pozyczki'):
                break

        # === PROWIZJA from the row after Ck (positive value = prowizja paid on day 0) ===
        for row in rows[5:10]:
            if row is None:
                continue
            col_b = row[2] if len(row) > 2 else None
            if isinstance(col_b, (int, float)) and 1000 < col_b < 100000:
                # This is the prowizja row (paid on disbursement day)
                result['prowizja'] = _fmt(col_b)
                break

        # === PAYMENT SCHEDULE: rates, dates, count ===
        # Find the disbursement date (row with large negative Ck value)
        disbursement_date = None
        for row in rows[5:10]:
            if row is None:
                continue
            col_a = row[1] if len(row) > 1 else None
            col_b = row[2] if len(row) > 2 else None
            if isinstance(col_a, datetime) and isinstance(col_b, (int, float)) and col_b < -10000:
                disbursement_date = col_a
                break

        # Collect ONLY actual monthly installments (after disbursement date, amount > 500)
        payment_amounts = []
        payment_dates = []
        for row in rows[6:]:
            if row is None:
                continue
            col_b = row[2] if len(row) > 2 else None
            col_a = row[1] if len(row) > 1 else None
            if not (isinstance(col_b, (int, float)) and col_b > 500):
                continue
            if not isinstance(col_a, datetime):
                continue
            # Skip all payments on the disbursement date (prowizja, fees — not installments)
            if disbursement_date and col_a <= disbursement_date:
                continue
            payment_amounts.append(col_b)
            payment_dates.append(col_a)

        # === COMPUTE FINANCIAL TOTALS FROM PAYMENT DATA ===
        if payment_amounts and result.get('kwota_pozyczki'):
            kp_val = float(result['kwota_pozyczki'])
            total_installments = sum(payment_amounts)
            suma_odsetek = total_installments - kp_val
            prow_val = float(result.get('prowizja', '0'))
            calkowity_koszt = suma_odsetek + prow_val
            ckk_val = float(result.get('calkowita_kwota_kredytu', '0'))

            result['suma_odsetek_bank'] = _fmt(suma_odsetek)
            result['calkowity_koszt_kredytu'] = _fmt(calkowity_koszt)
            if ckk_val > 0:
                result['calkowita_kwota_do_zaplaty'] = _fmt(ckk_val + calkowity_koszt)

        if payment_amounts:
            rate_counter = Counter(payment_amounts)
            std_rate, std_count = rate_counter.most_common(1)[0]
            result['kwota_raty'] = _fmt(std_rate)
            result['rata_pierwsza'] = _fmt(payment_amounts[0])
            result['rata_ostatnia'] = _fmt(payment_amounts[-1])
            result['liczba_rat'] = str(len(payment_amounts))

            # Build harmonogram description for the lawsuit template
            first = payment_amounts[0]
            last = payment_amounts[-1]
            first_date = payment_dates[0].strftime('%d.%m.%Y') if payment_dates else ''
            last_date = payment_dates[-1].strftime('%d.%m.%Y') if payment_dates else ''
            if abs(first - std_rate) > 1:
                result['harmonogram_raty_opis'] = (
                    f"pierwsza rata wynosi {_fmt(first)} zł ({first_date}), "
                    f"druga i kolejne aż do przedostatniej włącznie – {_fmt(std_rate)} zł "
                    f"(6 każdego miesiąca) oraz ostatnia {_fmt(last)} zł ({last_date})"
                )
            else:
                result['harmonogram_raty_opis'] = (
                    f"raty w wysokości {_fmt(std_rate)} zł płatne 6 każdego miesiąca, "
                    f"ostatnia rata {_fmt(last)} zł ({last_date})"
                )

        if payment_dates:
            result['data_pierwszej_raty'] = payment_dates[0].strftime('%d.%m.%Y')
            result['data_ostatniej_raty'] = payment_dates[-1].strftime('%d.%m.%Y')
            # Day of payment = most common day
            day_counter = Counter(d.day for d in payment_dates)
            result['dzien_platnosci_raty'] = str(day_counter.most_common(1)[0][0])

        # === DERIVE: prowizja = kwota_pozyczki - CKK ===
        if result.get('kwota_pozyczki') and result.get('calkowita_kwota_kredytu') and not result.get('prowizja'):
            kp = float(result['kwota_pozyczki'])
            ckk = float(result['calkowita_kwota_kredytu'])
            if kp > ckk:
                result['prowizja'] = _fmt(kp - ckk)

        wb.close()
        return result

    except Exception as e:
        return {'error': str(e)}


def extract_gofin_data(text: str) -> dict:
    """
    Extract data from Gofin calculator PDF text.
    Returns: kwota_kredytu, oprocentowanie, okres, rata, calkowity_koszt
    """
    result = {}

    m = re.search(r'Kwota\s+kredytu:\s*([\d\s]+[.,]\d{2})', text)
    if m:
        result['ckk'] = m.group(1).replace(' ', '')

    m = re.search(r'Oprocentowanie\s+nominalne:\s*([\d,]+)%', text)
    if m:
        result['oprocentowanie'] = m.group(1).replace(',', '.')

    m = re.search(r'Okres\s+kredytowania:\s*(\d+)', text)
    if m:
        result['liczba_rat'] = m.group(1)

    # Extract the rate from the table
    # Gofin format: "Lp. zadłużenie rata część_kap część_ods"
    # Numbers may have OCR spaces: "2 437 ,10" or "2 437,10"
    rate_pattern = r'\d+\s+([\d\s]+[.,]\s*\d{2})\s+([\d\s]+[.,]\s*\d{2})\s+([\d\s]+[.,]\s*\d{2})'
    rate_matches = re.findall(rate_pattern, text)
    if rate_matches:
        from collections import Counter
        # The rate column is the second captured group in each row (rata)
        clean_rates = []
        for match in rate_matches:
            rata = match[0].replace(' ', '').replace(',', '.')
            clean_rates.append(rata)
        counter = Counter(clean_rates)
        most_common = counter.most_common(1)
        if most_common:
            result['rata_gofin'] = most_common[0][0]

    # Robust: find ALL numbers with OCR spaces (like "2 437 ,10" or "150 000,00")
    if 'rata_gofin' not in result or float(result.get('rata_gofin', '0')) < 500:
        all_numbers = re.findall(r'(\d[\d\s]*\d\s*[.,]\s*\d{2})', text)
        if all_numbers:
            from collections import Counter
            cleaned = []
            for n in all_numbers:
                c = n.replace(' ', '').replace('\n', '').replace('\x0c', '').replace(',', '.')
                try:
                    v = float(c)
                    if 1000 < v < 10000:
                        cleaned.append(c)
                except ValueError:
                    continue
            if cleaned:
                counter = Counter(cleaned)
                most_common = counter.most_common(1)
                if most_common and most_common[0][1] >= 3:
                    result['rata_gofin'] = most_common[0][0]

    return result


# ============================================================
# Helpers
# ============================================================

def _f(val) -> Optional[float]:
    if val is None:
        return None
    try:
        s = str(val).replace(' ', '').replace('\xa0', '').replace(',', '.').replace('zł', '').replace('%', '').strip()
        return float(s) if s else None
    except (ValueError, AttributeError):
        return None


def _fmt(val: float) -> str:
    return f'{val:.2f}'


def _parse_date(val: str) -> Optional[datetime]:
    for fmt in ('%d.%m.%Y', '%d %B %Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(val.strip().rstrip(' r.'), fmt)
        except ValueError:
            continue
    # Try Polish month names
    pl_months = {
        'stycznia': '01', 'lutego': '02', 'marca': '03', 'kwietnia': '04',
        'maja': '05', 'czerwca': '06', 'lipca': '07', 'sierpnia': '08',
        'września': '09', 'października': '10', 'listopada': '11', 'grudnia': '12',
    }
    val_clean = val.strip().rstrip(' r.')
    for name, num in pl_months.items():
        if name in val_clean:
            val_clean = val_clean.replace(name, num + '.')
            try:
                return datetime.strptime(val_clean.strip(), '%d %m. %Y')
            except ValueError:
                pass
    return None
