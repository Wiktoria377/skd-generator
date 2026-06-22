"""Data models for the autonomous SKD lawsuit compilation engine."""
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class DocumentType(Enum):
    UMOWA = "umowa_kredytowa"
    REGULAMIN = "regulamin"
    HARMONOGRAM = "harmonogram_splat"
    ZASWIADCZENIE = "zaswiadczenie_bankowe"
    WEZWANIE = "wezwanie_do_zaplaty"
    POTWIERDZENIE_NADANIA = "potwierdzenie_nadania"
    REKLAMACJA = "reklamacja"
    ODPOWIEDZ_BANKU = "odpowiedz_banku"
    OSWIADCZENIE_SKD = "oswiadczenie_skd"
    PISMO_NBP = "pismo_nbp"
    INNE = "inne"
    UNKNOWN = "unknown"


DOC_TYPE_LABELS = {
    DocumentType.UMOWA: "Umowa kredytowa / pożyczki",
    DocumentType.REGULAMIN: "Regulamin / Ogólne Warunki Umowy",
    DocumentType.HARMONOGRAM: "Harmonogram spłat",
    DocumentType.ZASWIADCZENIE: "Zaświadczenie bankowe o historii spłat",
    DocumentType.WEZWANIE: "Wezwanie do zapłaty",
    DocumentType.POTWIERDZENIE_NADANIA: "Potwierdzenie nadania / odbioru",
    DocumentType.REKLAMACJA: "Reklamacja konsumencka",
    DocumentType.ODPOWIEDZ_BANKU: "Odpowiedź banku na reklamację / oświadczenie SKD",
    DocumentType.OSWIADCZENIE_SKD: "Oświadczenie o skorzystaniu z SKD",
    DocumentType.PISMO_NBP: "Pismo / informacja NBP",
    DocumentType.INNE: "Inny dokument",
    DocumentType.UNKNOWN: "Nierozpoznany",
}

REQUIRED_DOCUMENTS = [
    DocumentType.UMOWA,
    DocumentType.HARMONOGRAM,
    DocumentType.ZASWIADCZENIE,
    DocumentType.WEZWANIE,
    DocumentType.OSWIADCZENIE_SKD,
]

REQUIRED_DOC_ALERTS = {
    DocumentType.UMOWA: "[BRAK DOKUMENTU: Brak umowy kredytowej - niemożliwe ustalenie warunków kredytu]",
    DocumentType.HARMONOGRAM: "[BRAK DOKUMENTU: Brak harmonogramu spłat - niemożliwe zweryfikowanie rat i RRSO]",
    DocumentType.ZASWIADCZENIE: "[BRAK DOKUMENTU: Brak zaświadczenia bankowego - niemożliwe ustalenie kwot faktycznie zapłaconych]",
    DocumentType.WEZWANIE: "[BRAK DOKUMENTU: Wklej datę i dowód nadania wezwania do zapłaty]",
    DocumentType.OSWIADCZENIE_SKD: "[BRAK DOKUMENTU: Brak oświadczenia SKD - wymagane do wykazania złożenia oświadczenia art. 45 u.k.k.]",
}


@dataclass
class ClassifiedDocument:
    filepath: str
    filename: str
    doc_type: DocumentType
    confidence: float
    extracted_text: str
    page_count: int = 1
    classification_reason: str = ""


@dataclass
class CreditData:
    # === Dane stron ===
    data_pozwu: Optional[str] = None
    sad: Optional[str] = None
    sad_wydzial: Optional[str] = None
    powod_imie_nazwisko: Optional[str] = None
    powod_adres: Optional[str] = None
    powod_pesel: Optional[str] = None
    pozwany_nazwa: Optional[str] = None
    pozwany_adres: Optional[str] = None
    pozwany_siedziba: Optional[str] = None
    pozwany_krs: Optional[str] = None
    wps: Optional[str] = None
    oplata: Optional[str] = None

    # === Dane umowy ===
    data_zawarcia_umowy: Optional[str] = None
    numer_umowy: Optional[str] = None
    typ_umowy: Optional[str] = None
    kwota_pozyczki: Optional[str] = None
    kwota_pozyczki_slownie: Optional[str] = None
    calkowita_kwota_kredytu: Optional[str] = None
    calkowita_kwota_do_zaplaty: Optional[str] = None
    calkowita_kwota_do_zaplaty_prawidlowa: Optional[str] = None
    calkowity_koszt_kredytu: Optional[str] = None
    oprocentowanie: Optional[str] = None
    typ_oprocentowania: Optional[str] = None
    rrso_bank: Optional[str] = None
    liczba_rat: Optional[str] = None
    dzien_platnosci_raty: Optional[str] = None
    kwota_raty: Optional[str] = None
    prowizja: Optional[str] = None
    ubezpieczenie: Optional[str] = None
    opis_kosztow_kredytowanych: Optional[str] = None

    # === Dane z zaświadczenia bankowego ===
    suma_odsetek_zaplaconych: Optional[str] = None
    suma_kapitalu_splaconego: Optional[str] = None
    suma_prowizji_zaplaconej: Optional[str] = None
    data_ostatniej_wplaty: Optional[str] = None
    saldo_zadluzenia: Optional[str] = None
    historia_wplat_summary: Optional[str] = None

    # === Dane z harmonogramu ===
    harmonogram_raty_opis: Optional[str] = None
    data_pierwszej_raty: Optional[str] = None
    data_ostatniej_raty: Optional[str] = None

    # === Obliczenia finansowe ===
    suma_odsetek_bank: Optional[str] = None
    odsetki_od_kredytowanych_kosztow: Optional[str] = None
    hipotetyczna_rata: Optional[str] = None
    hipotetyczny_calkowity_koszt: Optional[str] = None
    hipotetyczna_calkowita_do_zaplaty: Optional[str] = None

    # === RRSO obliczone (5 kolumn) ===
    rrso_kolumna1: Optional[str] = None
    rrso_kolumna2: Optional[str] = None
    rrso_kolumna3: Optional[str] = None
    rrso_kolumna3_roznica: Optional[str] = None
    rrso_kolumna4: Optional[str] = None
    rrso_kolumna4_roznica: Optional[str] = None
    rrso_kolumna5: Optional[str] = None
    rrso_kolumna5_roznica: Optional[str] = None

    # === Daty i zdarzenia procesowe ===
    data_oswiadczenia_skd: Optional[str] = None
    data_wniosku_zaswiadczenie: Optional[str] = None
    data_wezwania_do_zaplaty: Optional[str] = None
    data_odbioru_wezwania: Optional[str] = None
    data_wymagalnosci: Optional[str] = None
    data_reklamacji: Optional[str] = None
    data_odpowiedzi_banku: Optional[str] = None

    # === Kwoty roszczenia ===
    kwota_roszczenia: Optional[str] = None
    kwota_roszczenia_slownie: Optional[str] = None
    kwota_odsetek_zaplaconych: Optional[str] = None
    okres_odsetek_od: Optional[str] = None
    okres_odsetek_do: Optional[str] = None

    # === Paragrafy umowy (naruszenia) ===
    paragraf_rrso: Optional[str] = None
    paragraf_calkowita_kwota: Optional[str] = None
    paragraf_wczesniejsza_splata: Optional[str] = None
    paragraf_ustep_wczesniejsza_splata: Optional[str] = None
    paragraf_odstapienie: Optional[str] = None
    paragraf_ustep_odstapienie: Optional[str] = None
    paragraf_zmiana_oplat: Optional[str] = None
    paragraf_prowizja_uiszczona: Optional[str] = None
    kryteria_zmiany_oplat_1: Optional[str] = None
    kryteria_zmiany_oplat_2: Optional[str] = None


@dataclass
class UserQuestion:
    """A question the system needs answered before it can proceed."""
    question_id: str
    field_name: str
    question_pl: str
    options: list = field(default_factory=list)
    context: str = ""
    severity: str = "blocking"  # "blocking" | "important" | "optional"
    answer: Optional[str] = None


@dataclass
class CaseContext:
    """Zunifikowany kontekst sprawy z wszystkich dokumentów."""
    credit_data: CreditData = field(default_factory=CreditData)
    classified_docs: list = field(default_factory=list)
    missing_documents: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    critical_errors: list = field(default_factory=list)
    cross_doc_discrepancies: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    financial_validation: dict = field(default_factory=dict)
    all_texts: dict = field(default_factory=dict)
    pending_questions: list = field(default_factory=list)
    resolution_log: list = field(default_factory=list)
