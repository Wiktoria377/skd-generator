"""
Generator Pozwów SKD — Interfejs webowy Streamlit
Sankcja Kredytu Darmowego — automatyczne generowanie pozwów
"""
import os
import sys
import tempfile
import time
import shutil
from pathlib import Path
from datetime import datetime

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from app.services.ocr_service import extract_text, SUPPORTED_EXTENSIONS
from app.services.document_classifier import classify_documents_batch
from app.services.context_engine import ContextEngine
from app.services.golden_rules import (
    extract_excel_rrso_direct, extract_gofin_data, apply_golden_rules,
)
from app.services.document_generator import generate_lawsuit_autonomous
from app.models.schema import DOC_TYPE_LABELS, CaseContext

MASTER_TEMPLATE = Path(__file__).parent / "app" / "templates" / "master_template.docx"

st.set_page_config(
    page_title="Generator Pozwów SKD",
    page_icon="⚖️",
    layout="wide",
)

st.markdown("""
<style>
    .main-header {font-size: 2rem; font-weight: 700; color: #1a365d; margin-bottom: 0.5rem;}
    .sub-header {font-size: 1rem; color: #718096; margin-bottom: 2rem;}
    .stat-card {background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 0.5rem;
                padding: 1rem; text-align: center;}
    .stat-value {font-size: 2rem; font-weight: 700; color: #1a365d;}
    .stat-label {font-size: 0.8rem; color: #718096;}
    .stDownloadButton > button {background-color: #38a169 !important; color: white !important;
                                 font-size: 1.1rem !important; padding: 0.75rem 2rem !important;}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">⚖️ Generator Pozwów SKD</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Sankcja Kredytu Darmowego — automatyczne generowanie pozwów z dokumentacji klienta</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("ℹ️ Instrukcja")
    st.markdown("""
    **Krok 1:** Załaduj dokumenty klienta poniżej.

    **Krok 2:** Kliknij „Generuj pozew".

    **Krok 3:** Pobierz gotowy plik .docx.

    ---
    **Obsługiwane dokumenty:**
    - 📄 Umowa kredytowa (PDF/skan)
    - 📊 Excel z obliczeniami RRSO
    - 📋 Zaświadczenie bankowe (PDF/skan)
    - 📝 Wezwanie do zapłaty (PDF/skan)
    - 📝 Oświadczenie SKD (PDF/skan)
    - 📊 Wyliczenie Gofin (PDF)
    - 📋 Ankieta klienta (DOCX)
    - 📄 Wnioski o zaświadczenia (PDF)

    ---
    **Format plików:** PDF, DOCX, XLSX, XLS, PNG, JPG
    """)
    st.markdown("---")
    st.caption("Wersja 4.0 — Madejczyk Kancelaria Prawna")


uploaded_files = st.file_uploader(
    "📁 Załaduj dokumenty klienta",
    type=["pdf", "docx", "doc", "xlsx", "xls", "csv", "png", "jpg", "jpeg", "tiff"],
    accept_multiple_files=True,
    help="Załaduj wszystkie dokumenty z folderu klienta: umowę, zaświadczenie, wezwanie, Excel RRSO, ankietę itp.",
)

if uploaded_files:
    st.info(f"📎 Załadowano **{len(uploaded_files)}** plików: {', '.join(f.name for f in uploaded_files)}")


col_btn, col_space = st.columns([1, 3])
with col_btn:
    generate_btn = st.button(
        "⚖️ Generuj pozew",
        type="primary",
        disabled=not uploaded_files,
        use_container_width=True,
    )

if generate_btn and uploaded_files:
    work_dir = Path(tempfile.mkdtemp(prefix="skd_"))
    output_path = work_dir / f"Pozew_SKD_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"

    progress = st.progress(0, text="Przygotowywanie dokumentów...")
    status_area = st.empty()
    log_expander = st.expander("📋 Dziennik przetwarzania", expanded=False)

    try:
        # === FAZA 1: Zapis i ekstrakcja tekstu ===
        progress.progress(5, text="🔍 OCR / Ekstrakcja tekstu z dokumentów...")
        status_area.info("Trwa odczytywanie dokumentów — OCR dla skanów, parsowanie Excel/PDF...")

        saved_paths = []
        for uf in uploaded_files:
            fpath = work_dir / uf.name
            fpath.write_bytes(uf.read())
            saved_paths.append(fpath)

        extraction_results = []
        errors = []
        total_files = len(saved_paths)
        for i, fpath in enumerate(saved_paths):
            pct = 5 + int((i / total_files) * 30)
            progress.progress(pct, text=f"🔍 OCR: {fpath.name} ({i+1}/{total_files})...")
            try:
                text = extract_text(str(fpath))
                extraction_results.append((str(fpath), fpath.name, text))
                with log_expander:
                    st.write(f"✅ {fpath.name}: {len(text)} znaków wyodrębniono")
            except Exception as e:
                errors.append(f"{fpath.name}: {e}")
                extraction_results.append((str(fpath), fpath.name, ""))
                with log_expander:
                    st.write(f"⚠️ {fpath.name}: {e}")

        # === FAZA 2: Klasyfikacja dokumentów ===
        progress.progress(40, text="📂 Klasyfikacja dokumentów...")
        status_area.info("Automatyczna identyfikacja typów dokumentów...")

        classified = classify_documents_batch(extraction_results)

        with log_expander:
            st.write("**Klasyfikacja:**")
            for doc in classified:
                label = DOC_TYPE_LABELS.get(doc.doc_type, doc.doc_type.value)
                st.write(f"  📄 {doc.filename} → **{label}** ({doc.confidence*100:.0f}%)")

        # === FAZA 3: Ekstrakcja Excel RRSO i Gofin ===
        progress.progress(50, text="📊 Analiza Excel RRSO i kalkulatora Gofin...")
        status_area.info("Odczytywanie RRSO, rat, kwot z plików Excel i Gofin...")

        excel_rrso_data = {}
        gofin_data = {}
        for doc in classified:
            if doc.filename.endswith(('.xlsx', '.xls')):
                if 'rrso' in doc.filename.lower() or 'obliczen' in doc.filename.lower() or 'excel' in doc.filename.lower():
                    excel_rrso_data = extract_excel_rrso_direct(doc.filepath)
            if 'gofin' in doc.filename.lower():
                gofin_data = extract_gofin_data(doc.extracted_text)

        with log_expander:
            if excel_rrso_data:
                st.write(f"✅ Excel RRSO: {len(excel_rrso_data)} pól wyodrębniono")
            if gofin_data:
                st.write(f"✅ Gofin: rata = {gofin_data.get('rata_gofin', '?')}")

        # === FAZA 4: Budowa kontekstu sprawy ===
        progress.progress(60, text="🧠 Budowa kontekstu sprawy — analiza krzyżowa dokumentów...")
        status_area.info("Ekstrakcja danych stron, kwot, dat, paragrafów naruszeń...")

        engine = ContextEngine()
        ctx = engine.build_case_context(
            classified,
            excel_rrso_data=excel_rrso_data,
            gofin_data=gofin_data,
        )

        from dataclasses import fields as dc_fields
        cd = ctx.credit_data
        filled_count = sum(1 for f in dc_fields(cd) if getattr(cd, f.name) is not None)
        total_count = len(dc_fields(cd))

        with log_expander:
            st.write(f"✅ Kontekst sprawy: **{filled_count}/{total_count}** pól wypełnionych")
            if ctx.missing_documents:
                for md in ctx.missing_documents:
                    st.write(f"⚠️ Brak dokumentu: {DOC_TYPE_LABELS.get(md, str(md))}")

        # === FAZA 5: Walidacja finansowa ===
        progress.progress(75, text="🔢 Kalkulacja WPS, dat i kwot roszczenia...")
        status_area.info("Obliczanie wartości przedmiotu sporu, rat hipotetycznych, RRSO...")

        from app.services.financial_calculator import validate_credit, serialize_validation

        def _pf(val, default=0.0):
            if not val: return default
            try: return float(str(val).replace(' ', '').replace(',', '.').replace('%', '').replace('zł', ''))
            except: return default

        try:
            ckk = _pf(cd.calkowita_kwota_kredytu)
            kp = _pf(cd.kwota_pozyczki)
            prow = _pf(cd.prowizja)
            if ckk > 0 and kp > 0 and prow > 0:
                from datetime import datetime as dt
                fv = validate_credit(
                    calkowita_kwota_kredytu=ckk, kwota_pozyczki=kp, prowizja=prow,
                    ubezpieczenie=_pf(cd.ubezpieczenie),
                    oprocentowanie=_pf(cd.oprocentowanie) / 100 if _pf(cd.oprocentowanie) > 1 else _pf(cd.oprocentowanie),
                    liczba_rat=int(_pf(cd.liczba_rat, 60)),
                    kwota_raty_bank=_pf(cd.kwota_raty), rrso_bank=_pf(cd.rrso_bank),
                    data_wyplaty=dt.strptime(cd.data_zawarcia_umowy, '%d.%m.%Y') if cd.data_zawarcia_umowy else dt.now(),
                    dzien_raty=int(_pf(cd.dzien_platnosci_raty, 15)),
                )
                ctx.financial_validation = serialize_validation(fv)
                apply_golden_rules(ctx)
        except Exception as e:
            with log_expander:
                st.write(f"⚠️ Walidacja finansowa: {e}")

        # === FAZA 6: Generowanie pozwu ===
        progress.progress(85, text="📝 Generowanie pozwu — wypełnianie szablonu...")
        status_area.info("Wstawianie danych do szablonu z żółtym podświetleniem...")

        _, report = generate_lawsuit_autonomous(
            template_path=str(MASTER_TEMPLATE),
            output_path=str(output_path),
            case_context=ctx,
        )

        filled_ph = sum(1 for r in report if r['status'] == 'filled')
        missing_ph = sum(1 for r in report if r['status'] == 'missing')

        progress.progress(100, text="✅ Pozew wygenerowany!")
        status_area.success(f"Pozew wygenerowany pomyślnie! Wypełniono {filled_ph}/{filled_ph+missing_ph} pól.")

        # === WYNIKI ===
        st.markdown("---")
        st.subheader("📊 Wyniki generowania")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Pola wypełnione", f"{filled_ph}", delta=None)
        with col2:
            st.metric("Pola brakujące", f"{missing_ph}", delta=None, delta_color="inverse")
        with col3:
            accuracy = filled_ph / (filled_ph + missing_ph) * 100 if (filled_ph + missing_ph) > 0 else 0
            st.metric("Dokładność", f"{accuracy:.1f}%")
        with col4:
            st.metric("Dokumentów", f"{len(uploaded_files)}")

        # Download button
        with open(output_path, "rb") as f:
            docx_bytes = f.read()

        st.download_button(
            label="📥 Pobierz pozew (.docx)",
            data=docx_bytes,
            file_name=output_path.name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
        )

        # Extracted data summary
        with st.expander("📋 Wyodrębnione dane", expanded=False):
            data_labels = {
                'powod_imie_nazwisko': 'Powód', 'pozwany_nazwa': 'Pozwany',
                'numer_umowy': 'Nr umowy', 'data_zawarcia_umowy': 'Data umowy',
                'calkowita_kwota_kredytu': 'CKK', 'kwota_pozyczki': 'Kwota pożyczki',
                'prowizja': 'Prowizja', 'oprocentowanie': 'Oprocentowanie',
                'rrso_bank': 'RRSO bank', 'liczba_rat': 'Liczba rat',
                'kwota_raty': 'Rata', 'kwota_roszczenia': 'Kwota roszczenia',
                'wps': 'WPS', 'oplata': 'Opłata sądowa',
                'data_wezwania_do_zaplaty': 'Data wezwania',
                'data_wymagalnosci': 'Wymagalność',
                'kwota_odsetek_zaplaconych': 'Odsetki zapłacone',
                'suma_odsetek_bank': 'Suma odsetek (umowa)',
                'hipotetyczna_rata': 'Rata hipotetyczna',
                'sad': 'Sąd',
            }
            cols = st.columns(3)
            i = 0
            for field, label in data_labels.items():
                val = getattr(cd, field, None)
                with cols[i % 3]:
                    if val:
                        st.success(f"**{label}:** {val}")
                    else:
                        st.error(f"**{label}:** brak danych")
                i += 1

        # Pending questions / warnings
        if ctx.pending_questions:
            with st.expander("❓ Pytania wymagające odpowiedzi", expanded=True):
                st.warning("Poniższe pola nie zostały automatycznie ustalone. Uzupełnij je ręcznie w wygenerowanym pliku .docx (oznaczone na czerwono).")
                for q in ctx.pending_questions:
                    severity_icon = "🔴" if q.severity == 'blocking' else "🟡"
                    st.write(f"{severity_icon} **{q.field_name}**: {q.question_pl}")

        if errors:
            with st.expander("⚠️ Błędy ekstrakcji", expanded=False):
                for err in errors:
                    st.error(err)

    except Exception as e:
        progress.progress(100, text="❌ Błąd!")
        status_area.error(f"Wystąpił błąd: {e}")
        import traceback
        with log_expander:
            st.code(traceback.format_exc())
    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except:
            pass

elif not uploaded_files:
    st.markdown("""
    <div style="text-align: center; padding: 3rem; color: #718096;">
        <div style="font-size: 4rem;">📁</div>
        <div style="font-size: 1.2rem; margin-top: 1rem;">Załaduj dokumenty klienta powyżej, aby rozpocząć</div>
        <div style="font-size: 0.9rem; margin-top: 0.5rem;">System automatycznie rozpozna typy dokumentów, wyodrębi dane i wygeneruje pozew</div>
    </div>
    """, unsafe_allow_html=True)
