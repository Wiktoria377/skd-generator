"""
Automatyczny klasyfikator dokumentów prawnych SKD.
Klasyfikuje dokumenty na podstawie analizy treści (słowa kluczowe + AI).
"""
import re
from pathlib import Path
from app.models.schema import DocumentType, ClassifiedDocument


KEYWORD_PATTERNS: dict[DocumentType, list[tuple[str, float]]] = {
    DocumentType.UMOWA: [
        (r'umow[aęy]\s+(po[żz]yczki|kredyt)', 3.0),
        (r'ca[łl]kowita\s+kwota\s+kredytu', 2.5),
        (r'rrso|rzeczywist[aą]\s+roczn[aą]\s+stop', 2.0),
        (r'kredytodawc[aąę]|po[żz]yczkodawc', 2.0),
        (r'oprocentowani[ea]', 1.5),
        (r'kredytobiorc[aąę]|po[żz]yczkobiorc', 1.5),
        (r'ca[łl]kowit[aąy]\s+koszt\s+kredytu', 2.0),
        (r'prowizj[aąęi]', 1.0),
        (r'zabezpieczeni[ea]\s+kredytu', 1.5),
        (r'warunki\s+udzielenia', 1.5),
    ],
    DocumentType.REGULAMIN: [
        (r'regulamin', 3.0),
        (r'og[oó]lne\s+warunki', 3.0),
        (r'tabela\s+op[łl]at', 2.5),
        (r'postanowienia\s+og[oó]lne', 2.0),
        (r'definicje', 1.5),
        (r'reklamacj[aąęi]', 1.0),
    ],
    DocumentType.HARMONOGRAM: [
        (r'harmonogram\s+sp[łl]at', 4.0),
        (r'rata\s+nr|nr\s+raty|numer\s+raty', 3.0),
        (r'kapita[łl]ow[ao]-?\s*odsetkow', 2.5),
        (r'saldo\s+po\s+sp[łl]acie', 2.0),
        (r'cz[eę][sś][ćc]\s+kapita[łl]owa', 2.0),
        (r'cz[eę][sś][ćc]\s+odsetkowa', 2.0),
        (r'termin\s+p[łl]atno[sś]ci\s+raty', 2.0),
    ],
    DocumentType.ZASWIADCZENIE: [
        (r'za[sś]wiadczeni[ea]', 3.5),
        (r'historia\s+sp[łl]at', 3.0),
        (r'stan\s+zad[łl]u[żz]enia', 2.5),
        (r'wp[łl]at[aąy]\s+dokonan[aeych]', 2.0),
        (r'saldo\s+kredytu', 2.0),
        (r'sp[łl]acon[ayeych]\s+kapita[łl]', 2.0),
        (r'naliczon[eych]\s+odsetk', 2.0),
        (r'za[sś]wiadcza\s+si[eę]', 2.0),
    ],
    DocumentType.WEZWANIE: [
        (r'wezwani[ea]\s+do\s+zap[łl]aty', 4.0),
        (r'wzywam[y]?\s+do\s+zap[łl]aty', 3.5),
        (r'nienale[żz]n[eaego]+\s+[sś]wiadczeni', 2.5),
        (r'termin\s+\d+\s+dni', 1.5),
        (r'zwrot\s+kwoty', 1.5),
    ],
    DocumentType.POTWIERDZENIE_NADANIA: [
        (r'potwierdzen\w+\s+nadani[ea]', 4.0),
        (r'potwierdzen\w+\s+odbioru', 4.0),
        (r'potwierdzen\w+\s+dor[eę]czeni', 3.5),
        (r'list\s+polecony', 2.5),
        (r'poczta\s+polsk', 2.0),
        (r'przesy[łl]k[aąi]', 1.5),
        (r'nadawc[aą]|adresat', 1.5),
    ],
    DocumentType.REKLAMACJA: [
        (r'reklamacj[aąęi]', 3.5),
        (r'sk[łl]adam\s+reklamacj', 4.0),
        (r'naruszeni[ea]\s+art', 2.0),
        (r'wnosz[eę]\s+o\s+rozpatrzenie', 2.5),
        (r'niezgodno[sś][ćc]\s+z\s+umow', 1.5),
    ],
    DocumentType.ODPOWIEDZ_BANKU: [
        (r'odpowied[zź]\s+na\s+(reklamacj|o[sś]wiadczenie)', 4.0),
        (r'rozpatrzeni[ea]\s+reklamacji', 3.5),
        (r'stanowisko\s+banku', 3.0),
        (r'nie\s+uznaj[eę]m[y]?\s+stanowisk', 2.5),
        (r'podtrzymuj[eę]m[y]?\s+stanowisk', 2.0),
        (r'informuj[eę]m[y]?.*reklamacj', 2.0),
    ],
    DocumentType.OSWIADCZENIE_SKD: [
        (r'o[sś]wiadczeni[ea].*sankcj[aąi]\s+kredytu\s+darmowego', 5.0),
        (r'o[sś]wiadczeni[ea].*art\.?\s*45', 4.0),
        (r'sankcj[aąi]\s+kredytu\s+darmowego', 4.0),
        (r'skd', 2.0),
        (r'o[sś]wiadczam.*kredyt\s+darmow', 3.5),
        (r'art\.?\s*45\s+u\.?k\.?k', 3.0),
        (r'zwrot\s+kredytu\s+bez\s+odsetek', 2.5),
    ],
    DocumentType.PISMO_NBP: [
        (r'narodowy\s+bank\s+polsk', 4.0),
        (r'nbp', 3.0),
        (r'komisj[aą]\s+nadzoru\s+finansow', 2.5),
        (r'knf', 2.0),
    ],
    DocumentType.INNE: [
        (r'ankieta\s+dla\s+kredytobiorc', 5.0),
        (r'ankieta\s+dla\s+po[żz]yczkobiorc', 5.0),
        (r'czy\s+negocjowa[łl]\s+pan', 3.0),
        (r'czy\s+zawiera[łl]\s+pan.*aneks', 3.0),
        (r'czy\s+po[żz]yczka.*zosta[łl]a?\s+sp[łl]acon', 3.0),
    ],
}


def classify_document(text: str, filename: str = "") -> tuple[DocumentType, float, str]:
    """
    Klasyfikuje dokument na podstawie analizy treści.
    Zwraca (typ, pewność 0-1, uzasadnienie).
    """
    text_lower = text.lower()
    filename_lower = filename.lower()

    scores: dict[DocumentType, float] = {}
    match_details: dict[DocumentType, list[str]] = {}

    for doc_type, patterns in KEYWORD_PATTERNS.items():
        total = 0.0
        matches = []
        for pattern, weight in patterns:
            found = re.findall(pattern, text_lower)
            if found:
                total += weight * min(len(found), 3)
                matches.append(f"{pattern}: {len(found)}x")
        scores[doc_type] = total
        match_details[doc_type] = matches

    # Bonus from filename
    filename_hints = {
        DocumentType.UMOWA: ['umowa', 'kredyt', 'pozyczk'],
        DocumentType.REGULAMIN: ['regulamin', 'owu', 'warunki'],
        DocumentType.HARMONOGRAM: ['harmonogram', 'splat', 'raty'],
        DocumentType.ZASWIADCZENIE: ['zaswiadczenie', 'zaświadczenie', 'historia'],
        DocumentType.WEZWANIE: ['wezwanie', 'wezw'],
        DocumentType.POTWIERDZENIE_NADANIA: ['potwierdzenie', 'nadanie', 'odbioru', 'zwrotka'],
        DocumentType.REKLAMACJA: ['reklamacja', 'reklam'],
        DocumentType.ODPOWIEDZ_BANKU: ['odpowiedz', 'odpowiedź', 'stanowisko'],
        DocumentType.OSWIADCZENIE_SKD: ['oswiadczenie', 'oświadczenie', 'skd'],
        DocumentType.PISMO_NBP: ['nbp'],
        DocumentType.INNE: ['ankieta'],
    }
    # Filename is DEFINITIVE for certain document types — override all content scores
    DEFINITIVE_FILENAME_TYPES = {
        DocumentType.ZASWIADCZENIE: ['zaswiadczenie', 'zaświadczenie'],
        DocumentType.WEZWANIE: ['wezwanie'],
        DocumentType.OSWIADCZENIE_SKD: ['oswiadczenie', 'oświadczenie'],
        DocumentType.INNE: ['ankieta'],
    }
    for doc_type, keywords in DEFINITIVE_FILENAME_TYPES.items():
        for kw in keywords:
            if kw in filename_lower:
                # But "wezwanie" in filename beats "oświadczenie" in text
                # and "zaświadczenie" in filename beats "umowa" in text
                scores[doc_type] = scores.get(doc_type, 0) + 50.0
                break

    for doc_type, hints in filename_hints.items():
        for hint in hints:
            if hint in filename_lower:
                scores[doc_type] = scores.get(doc_type, 0) + 8.0

    if not scores or max(scores.values()) == 0:
        return DocumentType.UNKNOWN, 0.0, "Brak rozpoznanych wzorców"

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    max_possible = sum(w * 3 for _, w in KEYWORD_PATTERNS.get(best_type, [])) + 2.0
    confidence = min(best_score / max(max_possible * 0.4, 1), 1.0)

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_scores) > 1 and sorted_scores[1][1] > 0:
        ratio = sorted_scores[1][1] / best_score if best_score > 0 else 0
        if ratio > 0.8:
            confidence *= 0.7

    reason_parts = match_details.get(best_type, [])
    reason = f"Dopasowane wzorce: {'; '.join(reason_parts[:5])}" if reason_parts else "Dopasowanie z nazwy pliku"

    return best_type, round(confidence, 2), reason


def classify_documents_batch(documents: list[tuple[str, str, str]]) -> list[ClassifiedDocument]:
    """
    Klasyfikuje partię dokumentów.
    documents: lista (filepath, filename, extracted_text)
    """
    results = []
    for filepath, filename, text in documents:
        doc_type, confidence, reason = classify_document(text, filename)
        results.append(ClassifiedDocument(
            filepath=filepath,
            filename=filename,
            doc_type=doc_type,
            confidence=confidence,
            extracted_text=text,
            classification_reason=reason,
        ))

    # Resolve conflicts - if multiple docs classified as same type, keep highest confidence
    type_counts: dict[DocumentType, list[ClassifiedDocument]] = {}
    for doc in results:
        type_counts.setdefault(doc.doc_type, []).append(doc)

    for doc_type, docs in type_counts.items():
        if len(docs) > 1 and doc_type not in (DocumentType.INNE, DocumentType.UNKNOWN):
            docs.sort(key=lambda d: d.confidence, reverse=True)
            for i, doc in enumerate(docs):
                if i > 0:
                    doc.classification_reason += f" [UWAGA: Zduplikowana klasyfikacja - dokument #{i+1} z {len(docs)}]"

    return results
