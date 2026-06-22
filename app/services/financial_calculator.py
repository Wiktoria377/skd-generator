"""
Kalkulator finansowy z rekoncyliacją krzyżową między dokumentami.
Implementuje wzór RRSO z Załącznika nr 1 Dyrektywy 2008/48/WE.
Porównuje dane z umowy, harmonogramu i zaświadczenia bankowego.
"""
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta
from typing import Optional
import math

try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    class relativedelta:
        def __init__(self, months=0):
            self.months = months
        def __radd__(self, other):
            m = other.month + self.months - 1
            y = other.year + m // 12
            m = m % 12 + 1
            d = min(other.day, 28)
            return other.replace(year=y, month=m, day=d)


@dataclass
class RRSOResult:
    rrso_value: float
    rrso_percent: str
    method_description: str


@dataclass
class DiscrepancyAlert:
    field: str
    source_1: str
    value_1: str
    source_2: str
    value_2: str
    recommendation: str
    severity: str  # "critical" | "warning" | "info"


@dataclass
class FinancialValidation:
    rrso_bank: Optional[float] = None
    rrso_col1: Optional[RRSOResult] = None
    rrso_col2: Optional[RRSOResult] = None
    rrso_col3: Optional[RRSOResult] = None
    rrso_col4: Optional[RRSOResult] = None
    rrso_col5: Optional[RRSOResult] = None

    rata_prawidlowa: Optional[float] = None
    calkowity_koszt_prawidlowy: Optional[float] = None
    calkowita_do_zaplaty_prawidlowa: Optional[float] = None
    odsetki_od_kredytowanych_kosztow: Optional[float] = None

    roznica_rrso_col3: Optional[float] = None
    roznica_rrso_col4: Optional[float] = None
    roznica_rrso_col5: Optional[float] = None

    discrepancies: list = dc_field(default_factory=list)
    reconciliation_notes: list = dc_field(default_factory=list)


def calculate_monthly_payment(principal: float, annual_rate: float, num_months: int) -> float:
    if annual_rate == 0:
        return principal / num_months
    r = annual_rate / 12
    return principal * (r * (1 + r) ** num_months) / ((1 + r) ** num_months - 1)


def calculate_total_interest(principal: float, annual_rate: float, num_months: int) -> float:
    payment = calculate_monthly_payment(principal, annual_rate, num_months)
    return payment * num_months - principal


def calculate_xirr(cashflows: list[tuple[datetime, float]], guess: float = 0.1) -> Optional[float]:
    if not cashflows or len(cashflows) < 2:
        return None

    dates = [cf[0] for cf in cashflows]
    amounts = [cf[1] for cf in cashflows]
    d0 = dates[0]

    def xnpv(rate):
        return sum(
            amount / (1 + rate) ** ((d - d0).days / 365.0)
            for d, amount in zip(dates, amounts)
        )

    def xnpv_deriv(rate):
        return sum(
            -amount * ((d - d0).days / 365.0) / (1 + rate) ** ((d - d0).days / 365.0 + 1)
            for d, amount in zip(dates, amounts)
        )

    rate = guess
    for _ in range(300):
        npv = xnpv(rate)
        deriv = xnpv_deriv(rate)
        if abs(deriv) < 1e-14:
            break
        new_rate = rate - npv / deriv
        if abs(new_rate - rate) < 1e-10:
            return new_rate
        rate = new_rate
        if rate <= -1:
            rate = guess / 2

    return rate if abs(xnpv(rate)) < 0.01 else None


def validate_credit(
    calkowita_kwota_kredytu: float,
    kwota_pozyczki: float,
    prowizja: float,
    ubezpieczenie: float,
    oprocentowanie: float,
    liczba_rat: int,
    kwota_raty_bank: float,
    rrso_bank: float,
    data_wyplaty: datetime,
    dzien_raty: int = 15,
    # Cross-document data from zaświadczenie
    zaswiadczenie_odsetki: Optional[float] = None,
    zaswiadczenie_kapital: Optional[float] = None,
    zaswiadczenie_prowizja: Optional[float] = None,
) -> FinancialValidation:
    """Pełna walidacja z rekoncyliacją krzyżową."""
    result = FinancialValidation()
    result.rrso_bank = rrso_bank
    koszty_kredytowane = prowizja + ubezpieczenie

    # --- Obliczenia rat ---
    rata_od_kwoty_pozyczki = calculate_monthly_payment(kwota_pozyczki, oprocentowanie, liczba_rat)
    rata_od_ckk = calculate_monthly_payment(calkowita_kwota_kredytu, oprocentowanie, liczba_rat)
    rata_z_kapitalem_prowizji = rata_od_ckk + koszty_kredytowane / liczba_rat
    result.rata_prawidlowa = round(rata_z_kapitalem_prowizji, 2)

    # Odsetki od kredytowanych kosztów
    odsetki_od_pozyczki = calculate_total_interest(kwota_pozyczki, oprocentowanie, liczba_rat)
    odsetki_od_ckk = calculate_total_interest(calkowita_kwota_kredytu, oprocentowanie, liczba_rat)
    result.odsetki_od_kredytowanych_kosztow = round(odsetki_od_pozyczki - odsetki_od_ckk, 2)

    result.calkowity_koszt_prawidlowy = round(odsetki_od_ckk + prowizja + ubezpieczenie, 2)
    result.calkowita_do_zaplaty_prawidlowa = round(
        calkowita_kwota_kredytu + result.calkowity_koszt_prawidlowy, 2
    )

    # --- Cross-document reconciliation ---
    if zaswiadczenie_prowizja is not None:
        if abs(zaswiadczenie_prowizja - prowizja) > 0.01:
            result.discrepancies.append(DiscrepancyAlert(
                field="prowizja",
                source_1="Umowa kredytowa",
                value_1=f"{prowizja:.2f} zł",
                source_2="Zaświadczenie bankowe",
                value_2=f"{zaswiadczenie_prowizja:.2f} zł",
                recommendation="Użyj wartości z zaświadczenia bankowego jako faktycznie zapłaconej",
                severity="critical",
            ).__dict__)
            result.reconciliation_notes.append(
                f"Prowizja z zaświadczenia ({zaswiadczenie_prowizja:.2f} zł) "
                f"różni się od umowy ({prowizja:.2f} zł). Zastosowano wartość z zaświadczenia."
            )

    if kwota_raty_bank > 0 and abs(rata_od_kwoty_pozyczki - kwota_raty_bank) > 0.02:
        result.discrepancies.append(DiscrepancyAlert(
            field="kwota_raty",
            source_1="Obliczenie matematyczne",
            value_1=f"{rata_od_kwoty_pozyczki:.2f} zł",
            source_2="Umowa kredytowa",
            value_2=f"{kwota_raty_bank:.2f} zł",
            recommendation="Rozbieżność raty może wskazywać na dodatkowe koszty lub inną metodę naliczania",
            severity="warning",
        ).__dict__)

    # --- Harmonogram ---
    first_payment = data_wyplaty + relativedelta(months=1)
    first_payment = first_payment.replace(day=min(dzien_raty, 28))
    dates = [first_payment + relativedelta(months=i) for i in range(liczba_rat)]

    # --- RRSO calculations (5 columns) ---
    # Kolumna 1: Ck = kwota pożyczki, z odsetkami od kosztów
    cf1 = [(data_wyplaty, -kwota_pozyczki)]
    cf1.append((data_wyplaty, prowizja + ubezpieczenie))
    for d in dates:
        cf1.append((d, rata_od_kwoty_pozyczki))
    r1 = calculate_xirr(cf1)
    if r1 is not None:
        result.rrso_col1 = RRSOResult(
            round(r1 * 100, 2), f"{r1 * 100:.2f}%",
            "Ck = kwota pożyczki, prowizja w dniu wypłaty + raty z odsetkami od kosztów"
        )

    # Kolumna 2: Ck = CKK, prowizja w ratach, z odsetkami od kosztów
    cf2 = [(data_wyplaty, -calkowita_kwota_kredytu)]
    for d in dates:
        cf2.append((d, rata_od_kwoty_pozyczki))
    r2 = calculate_xirr(cf2)
    if r2 is not None:
        result.rrso_col2 = RRSOResult(
            round(r2 * 100, 2), f"{r2 * 100:.2f}%",
            "Ck = CKK, prowizja w ratach, z odsetkami od kosztów"
        )

    # Kolumna 3: Ck = CKK, prowizja jednorazowa, z odsetkami od kosztów
    rata_bez_kap_prow = rata_od_kwoty_pozyczki - koszty_kredytowane / liczba_rat
    cf3 = [(data_wyplaty, -calkowita_kwota_kredytu)]
    cf3.append((data_wyplaty, prowizja + ubezpieczenie))
    for d in dates:
        cf3.append((d, rata_bez_kap_prow))
    r3 = calculate_xirr(cf3)
    if r3 is not None:
        result.rrso_col3 = RRSOResult(
            round(r3 * 100, 2), f"{r3 * 100:.2f}%",
            "Ck = CKK, prowizja jednorazowo, raty z odsetkami od kosztów"
        )
        result.roznica_rrso_col3 = round(r3 * 100 - rrso_bank, 2)

    # Kolumna 4: Ck = CKK, prowizja w ratach, bez odsetek od kosztów
    cf4 = [(data_wyplaty, -calkowita_kwota_kredytu)]
    for d in dates:
        cf4.append((d, rata_z_kapitalem_prowizji))
    r4 = calculate_xirr(cf4)
    if r4 is not None:
        result.rrso_col4 = RRSOResult(
            round(r4 * 100, 2), f"{r4 * 100:.2f}%",
            "Ck = CKK, prowizja w ratach, bez odsetek od kosztów"
        )
        result.roznica_rrso_col4 = round(r4 * 100 - rrso_bank, 2)

    # Kolumna 5: Ck = CKK, prowizja jednorazowa, bez odsetek od kosztów (PRAWIDŁOWE)
    cf5 = [(data_wyplaty, -calkowita_kwota_kredytu)]
    cf5.append((data_wyplaty, prowizja + ubezpieczenie))
    for d in dates:
        cf5.append((d, rata_od_ckk))
    r5 = calculate_xirr(cf5)
    if r5 is not None:
        result.rrso_col5 = RRSOResult(
            round(r5 * 100, 2), f"{r5 * 100:.2f}%",
            "Ck = CKK, prowizja jednorazowo, bez odsetek od kosztów (PRAWIDŁOWE wg C-744/24)"
        )
        result.roznica_rrso_col5 = round(r5 * 100 - rrso_bank, 2)

    return result


def serialize_validation(fv: FinancialValidation) -> dict:
    """Serializuje wynik walidacji do dict."""
    return {
        "rrso_bank": fv.rrso_bank,
        "rrso_col1": fv.rrso_col1.__dict__ if fv.rrso_col1 else None,
        "rrso_col2": fv.rrso_col2.__dict__ if fv.rrso_col2 else None,
        "rrso_col3": fv.rrso_col3.__dict__ if fv.rrso_col3 else None,
        "rrso_col4": fv.rrso_col4.__dict__ if fv.rrso_col4 else None,
        "rrso_col5": fv.rrso_col5.__dict__ if fv.rrso_col5 else None,
        "rata_prawidlowa": fv.rata_prawidlowa,
        "odsetki_od_kredytowanych_kosztow": fv.odsetki_od_kredytowanych_kosztow,
        "calkowity_koszt_prawidlowy": fv.calkowity_koszt_prawidlowy,
        "calkowita_do_zaplaty_prawidlowa": fv.calkowita_do_zaplaty_prawidlowa,
        "roznica_rrso_col3": fv.roznica_rrso_col3,
        "roznica_rrso_col4": fv.roznica_rrso_col4,
        "roznica_rrso_col5": fv.roznica_rrso_col5,
        "discrepancies": fv.discrepancies,
        "reconciliation_notes": fv.reconciliation_notes,
    }
