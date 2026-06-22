"""
API Router - Autonomous Multi-Document SKD Lawsuit Compilation Engine.
Obsługuje pełny pipeline od uploadu folderu do wygenerowanego pozwu.
"""
import os
import json
import uuid
import shutil
import zipfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.services.ocr_service import extract_text, SUPPORTED_EXTENSIONS
from app.services.document_classifier import classify_documents_batch
from app.services.context_engine import ContextEngine
from app.services.financial_calculator import validate_credit, serialize_validation
from app.services.document_generator import generate_lawsuit_autonomous
from app.models.schema import (
    CaseContext, CreditData, DocumentType, DOC_TYPE_LABELS,
    REQUIRED_DOCUMENTS, REQUIRED_DOC_ALERTS, ClassifiedDocument, UserQuestion,
)

router = APIRouter(prefix="/api", tags=["SKD Generator v2"])

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

sessions: dict = {}


def _parse_float(val: Optional[str], default: float = 0.0) -> float:
    if not val:
        return default
    try:
        return float(str(val).replace(' ', '').replace(',', '.').replace('%', '').replace('zł', '').strip())
    except (ValueError, AttributeError):
        return default


def _parse_date(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(val.strip(), fmt)
        except ValueError:
            continue
    return None


@router.post("/compile")
async def compile_lawsuit(
    template: UploadFile = File(...),
    documents: list[UploadFile] = File(...),
):
    """
    ZERO-CLICK: Upload template + all client docs -> get final lawsuit.
    Accepts individual files or a ZIP archive.
    """
    session_id = str(uuid.uuid4())
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Save template
    template_path = session_dir / f"template_{template.filename}"
    with open(template_path, "wb") as f:
        shutil.copyfileobj(template.file, f)

    # Save and extract documents
    doc_paths = []
    for doc_file in documents:
        fpath = session_dir / doc_file.filename
        with open(fpath, "wb") as f:
            shutil.copyfileobj(doc_file.file, f)

        if fpath.suffix.lower() == '.zip':
            extract_dir = session_dir / fpath.stem
            extract_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(fpath, 'r') as zf:
                zf.extractall(extract_dir)
            for p in extract_dir.rglob('*'):
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                    doc_paths.append(p)
        elif fpath.suffix.lower() in SUPPORTED_EXTENSIONS:
            doc_paths.append(fpath)

    sessions[session_id] = {
        "template_path": str(template_path),
        "status": "processing",
        "doc_count": len(doc_paths),
    }

    # === PHASE 1: Extract text from all documents ===
    extraction_results = []
    extraction_errors = []
    for dp in doc_paths:
        try:
            text = extract_text(str(dp))
            extraction_results.append((str(dp), dp.name, text))
        except Exception as e:
            extraction_errors.append({"file": dp.name, "error": str(e)})

    # === PHASE 2: Classify documents ===
    classified = classify_documents_batch(extraction_results)

    classification_summary = []
    for doc in classified:
        classification_summary.append({
            "filename": doc.filename,
            "type": DOC_TYPE_LABELS.get(doc.doc_type, doc.doc_type.value),
            "type_id": doc.doc_type.value,
            "confidence": doc.confidence,
            "reason": doc.classification_reason,
            "text_length": len(doc.extracted_text),
        })

    # === PHASE 2.5: Extract RRSO from Excel files and Gofin data BEFORE building context ===
    from app.services.golden_rules import extract_excel_rrso_direct, extract_gofin_data, apply_golden_rules
    excel_rrso_data = {}
    gofin_data = {}
    for doc in classified:
        if doc.filename.endswith(('.xlsx', '.xls')) and ('rrso' in doc.filename.lower() or 'obliczen' in doc.filename.lower()):
            excel_rrso_data = extract_excel_rrso_direct(doc.filepath)
        if 'gofin' in doc.filename.lower():
            gofin_data = extract_gofin_data(doc.extracted_text)

    # === PHASE 3: Build context ONCE with Excel/Gofin data ===
    # Golden rules (phase 7 inside build_case_context) now see Excel RRSO and Gofin data
    context_engine = ContextEngine()
    case_ctx = context_engine.build_case_context(
        classified,
        excel_rrso_data=excel_rrso_data,
        gofin_data=gofin_data,
    )
    cd = case_ctx.credit_data

    # === PHASE 4: Financial validation (if enough data exists) ===
    fv_result = None
    try:
        ckk = _parse_float(cd.calkowita_kwota_kredytu)
        kp = _parse_float(cd.kwota_pozyczki)
        prow = _parse_float(cd.prowizja)

        if ckk > 0 and kp > 0 and prow > 0:
            fv = validate_credit(
                calkowita_kwota_kredytu=ckk,
                kwota_pozyczki=kp,
                prowizja=prow,
                ubezpieczenie=_parse_float(cd.ubezpieczenie),
                oprocentowanie=_parse_float(cd.oprocentowanie) / 100 if cd.oprocentowanie and _parse_float(cd.oprocentowanie) > 1 else _parse_float(cd.oprocentowanie),
                liczba_rat=int(_parse_float(cd.liczba_rat, 60)),
                kwota_raty_bank=_parse_float(cd.kwota_raty),
                rrso_bank=_parse_float(cd.rrso_bank),
                data_wyplaty=_parse_date(cd.data_zawarcia_umowy) or datetime.now(),
                dzien_raty=int(_parse_float(cd.dzien_platnosci_raty, 15)),
                zaswiadczenie_odsetki=_parse_float(cd.suma_odsetek_zaplaconych) or None,
                zaswiadczenie_kapital=_parse_float(cd.suma_kapitalu_splaconego) or None,
                zaswiadczenie_prowizja=_parse_float(cd.suma_prowizji_zaplaconej) or None,
            )
            fv_result = serialize_validation(fv)

            # Apply financial results — but NEVER override Excel-sourced values
            # Excel RRSO and golden-rule hipotetyczna_rata are the authoritative source
            if not cd.odsetki_od_kredytowanych_kosztow and fv.odsetki_od_kredytowanych_kosztow:
                cd.odsetki_od_kredytowanych_kosztow = str(fv.odsetki_od_kredytowanych_kosztow)
            if not cd.hipotetyczny_calkowity_koszt and fv.calkowity_koszt_prawidlowy:
                cd.hipotetyczny_calkowity_koszt = str(fv.calkowity_koszt_prawidlowy)
            if not cd.hipotetyczna_calkowita_do_zaplaty and fv.calkowita_do_zaplaty_prawidlowa:
                cd.hipotetyczna_calkowita_do_zaplaty = str(fv.calkowita_do_zaplaty_prawidlowa)
                cd.calkowita_kwota_do_zaplaty_prawidlowa = str(fv.calkowita_do_zaplaty_prawidlowa)
            # DO NOT override: hipotetyczna_rata (golden rule), rrso_kolumna3/4/5 (Excel)

            # Re-run golden rules once more with financial validation results
            case_ctx.financial_validation = fv_result
            apply_golden_rules(case_ctx)
    except Exception as e:
        extraction_errors.append({"file": "financial_validation", "error": str(e)})

    # === PHASE 5: Generate lawsuit ===
    output_filename = f"Pozew_SKD_{session_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
    output_path = str(OUTPUT_DIR / output_filename)

    _, generation_report = generate_lawsuit_autonomous(
        template_path=str(template_path),
        output_path=output_path,
        case_context=case_ctx,
    )

    # Build response
    filled_count = sum(1 for r in generation_report if r['status'] == 'filled')
    missing_count = sum(1 for r in generation_report if r['status'] == 'missing')

    has_questions = len(case_ctx.pending_questions) > 0
    status = "needs_input" if has_questions else "completed"

    sessions[session_id].update({
        "status": status,
        "output_path": output_path,
        "output_filename": output_filename,
        "classified_docs": classified,
        "financial_validation": fv_result,
    })

    return {
        "session_id": session_id,
        "status": status,
        "pipeline_summary": {
            "documents_processed": len(doc_paths),
            "documents_classified": len(classified),
            "extraction_errors": extraction_errors,
            "fields_filled": filled_count,
            "fields_missing": missing_count,
        },
        "classification": classification_summary,
        "missing_documents": [
            DOC_TYPE_LABELS.get(dt, dt.value)
            for dt in case_ctx.missing_documents
        ],
        "critical_errors": case_ctx.critical_errors,
        "violations": case_ctx.violations,
        "warnings": case_ctx.warnings,
        "cross_doc_discrepancies": case_ctx.cross_doc_discrepancies,
        "timeline": case_ctx.timeline,
        "financial_validation": fv_result,
        "extracted_data": _credit_data_to_dict(cd),
        "generation_report": generation_report[:50],
        "resolution_log": case_ctx.resolution_log,
        "pending_questions": [
            {"question_id": q.question_id, "field_name": q.field_name,
             "question_pl": q.question_pl, "options": q.options,
             "severity": q.severity}
            for q in case_ctx.pending_questions
        ],
        "download_url": f"/api/download/{session_id}",
    }


@router.post("/compile/step-by-step/upload-template")
async def upload_template(file: UploadFile = File(...)):
    """Step 1: Upload template for step-by-step mode."""
    if not file.filename.endswith('.docx'):
        raise HTTPException(400, "Szablon musi być w formacie .docx")

    session_id = str(uuid.uuid4())
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    template_path = session_dir / f"template_{file.filename}"
    with open(template_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    sessions[session_id] = {
        "template_path": str(template_path),
        "status": "template_uploaded",
        "classified_docs": [],
        "doc_paths": [],
    }

    return {"session_id": session_id, "message": "Szablon załadowany."}


@router.post("/compile/step-by-step/upload-docs/{session_id}")
async def upload_documents(session_id: str, documents: list[UploadFile] = File(...)):
    """Step 2: Upload client documents."""
    if session_id not in sessions:
        raise HTTPException(404, "Sesja nie znaleziona")

    session = sessions[session_id]
    session_dir = UPLOAD_DIR / session_id

    doc_paths = []
    for doc_file in documents:
        fpath = session_dir / doc_file.filename
        with open(fpath, "wb") as f:
            shutil.copyfileobj(doc_file.file, f)

        if fpath.suffix.lower() == '.zip':
            extract_dir = session_dir / fpath.stem
            extract_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(fpath, 'r') as zf:
                zf.extractall(extract_dir)
            for p in extract_dir.rglob('*'):
                if p.is_file() and p.suffix.lower() in ('.pdf', '.docx', '.png', '.jpg', '.jpeg', '.tiff', '.bmp'):
                    doc_paths.append(str(p))
        elif fpath.suffix.lower() in ('.pdf', '.docx', '.png', '.jpg', '.jpeg', '.tiff', '.bmp'):
            doc_paths.append(str(fpath))

    # Extract and classify
    extraction_results = []
    errors = []
    for dp in doc_paths:
        try:
            text = extract_text(dp)
            extraction_results.append((dp, Path(dp).name, text))
        except Exception as e:
            errors.append({"file": Path(dp).name, "error": str(e)})

    classified = classify_documents_batch(extraction_results)

    session["classified_docs"] = classified
    session["doc_paths"] = doc_paths
    session["status"] = "docs_classified"

    return {
        "session_id": session_id,
        "documents_count": len(doc_paths),
        "classification": [
            {
                "filename": doc.filename,
                "type": DOC_TYPE_LABELS.get(doc.doc_type, doc.doc_type.value),
                "type_id": doc.doc_type.value,
                "confidence": doc.confidence,
                "reason": doc.classification_reason,
            }
            for doc in classified
        ],
        "errors": errors,
    }


@router.post("/compile/step-by-step/reclassify/{session_id}")
async def reclassify_document(session_id: str, request: Request):
    """Override document classification."""
    if session_id not in sessions:
        raise HTTPException(404, "Sesja nie znaleziona")

    body = await request.json()
    filename = body.get("filename")
    new_type = body.get("type_id")

    for doc in sessions[session_id].get("classified_docs", []):
        if doc.filename == filename:
            doc.doc_type = DocumentType(new_type)
            doc.classification_reason = "Ręczna reklasyfikacja przez użytkownika"
            doc.confidence = 1.0
            return {"message": f"Reklasyfikowano {filename} -> {DOC_TYPE_LABELS.get(doc.doc_type, new_type)}"}

    raise HTTPException(404, "Dokument nie znaleziony")


@router.post("/compile/step-by-step/generate/{session_id}")
async def generate_from_session(session_id: str, request: Request):
    """Step 3: Generate lawsuit from classified documents + optional manual data."""
    if session_id not in sessions:
        raise HTTPException(404, "Sesja nie znaleziona")

    session = sessions[session_id]
    classified = session.get("classified_docs", [])
    if not classified:
        raise HTTPException(400, "Brak sklasyfikowanych dokumentów")

    # Accept optional manual overrides
    manual_data = {}
    try:
        manual_data = await request.json()
    except Exception:
        pass

    # Build context
    context_engine = ContextEngine()
    case_ctx = context_engine.build_case_context(classified)

    # Apply manual overrides
    cd = case_ctx.credit_data
    for k, v in manual_data.items():
        if hasattr(cd, k) and v:
            setattr(cd, k, v)

    # Financial validation
    fv_result = None
    try:
        ckk = _parse_float(cd.calkowita_kwota_kredytu)
        kp = _parse_float(cd.kwota_pozyczki)
        prow = _parse_float(cd.prowizja)
        if ckk > 0 and kp > 0 and prow > 0:
            fv = validate_credit(
                calkowita_kwota_kredytu=ckk,
                kwota_pozyczki=kp,
                prowizja=prow,
                ubezpieczenie=_parse_float(cd.ubezpieczenie),
                oprocentowanie=_parse_float(cd.oprocentowanie) / 100 if cd.oprocentowanie and _parse_float(cd.oprocentowanie) > 1 else _parse_float(cd.oprocentowanie),
                liczba_rat=int(_parse_float(cd.liczba_rat, 60)),
                kwota_raty_bank=_parse_float(cd.kwota_raty),
                rrso_bank=_parse_float(cd.rrso_bank),
                data_wyplaty=_parse_date(cd.data_zawarcia_umowy) or datetime.now(),
                dzien_raty=int(_parse_float(cd.dzien_platnosci_raty, 15)),
                zaswiadczenie_odsetki=_parse_float(cd.suma_odsetek_zaplaconych) or None,
                zaswiadczenie_kapital=_parse_float(cd.suma_kapitalu_splaconego) or None,
                zaswiadczenie_prowizja=_parse_float(cd.suma_prowizji_zaplaconej) or None,
            )
            fv_result = serialize_validation(fv)
            case_ctx.financial_validation = fv_result

            cd.odsetki_od_kredytowanych_kosztow = str(fv.odsetki_od_kredytowanych_kosztow) if fv.odsetki_od_kredytowanych_kosztow else None
            cd.hipotetyczna_rata = str(fv.rata_prawidlowa) if fv.rata_prawidlowa else None
            cd.calkowita_kwota_do_zaplaty_prawidlowa = str(fv.calkowita_do_zaplaty_prawidlowa) if fv.calkowita_do_zaplaty_prawidlowa else None
            if fv.rrso_col3:
                cd.rrso_kolumna3 = fv.rrso_col3.rrso_percent
                cd.rrso_kolumna3_roznica = str(fv.roznica_rrso_col3)
            if fv.rrso_col4:
                cd.rrso_kolumna4 = fv.rrso_col4.rrso_percent
                cd.rrso_kolumna4_roznica = str(fv.roznica_rrso_col4)
            if fv.rrso_col5:
                cd.rrso_kolumna5 = fv.rrso_col5.rrso_percent
                cd.rrso_kolumna5_roznica = str(fv.roznica_rrso_col5)
    except Exception:
        pass

    # Generate
    output_filename = f"Pozew_SKD_{session_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
    output_path = str(OUTPUT_DIR / output_filename)

    _, report = generate_lawsuit_autonomous(
        template_path=session["template_path"],
        output_path=output_path,
        case_context=case_ctx,
    )

    filled = sum(1 for r in report if r['status'] == 'filled')
    missing = sum(1 for r in report if r['status'] == 'missing')

    session["output_path"] = output_path
    session["status"] = "completed"

    return {
        "session_id": session_id,
        "status": "completed",
        "fields_filled": filled,
        "fields_missing": missing,
        "missing_documents": [DOC_TYPE_LABELS.get(dt, dt.value) for dt in case_ctx.missing_documents],
        "critical_errors": case_ctx.critical_errors,
        "violations": case_ctx.violations,
        "cross_doc_discrepancies": case_ctx.cross_doc_discrepancies,
        "timeline": case_ctx.timeline,
        "financial_validation": fv_result,
        "extracted_data": _credit_data_to_dict(cd),
        "generation_report": report[:50],
        "download_url": f"/api/download/{session_id}",
    }


@router.post("/answer/{session_id}")
async def answer_questions(session_id: str, request: Request):
    """Human-in-the-loop: user provides answers to pending questions, then regenerate."""
    if session_id not in sessions:
        raise HTTPException(404, "Sesja nie znaleziona")

    session = sessions[session_id]
    body = await request.json()
    answers = body.get("answers", {})

    if not answers:
        raise HTTPException(400, "Brak odpowiedzi")

    # Store answers
    session.setdefault("user_answers", {}).update(answers)

    # Rebuild context with answers
    classified = session.get("classified_docs", [])
    if not classified:
        raise HTTPException(400, "Brak sklasyfikowanych dokumentów")

    context_engine = ContextEngine()
    case_ctx = context_engine.build_case_context(
        classified,
        financial_validation=session.get("financial_validation"),
        user_answers=session["user_answers"],
    )
    cd = case_ctx.credit_data

    # Run financial validation with updated data
    fv_result = session.get("financial_validation")
    try:
        ckk = _parse_float(cd.calkowita_kwota_kredytu)
        kp = _parse_float(cd.kwota_pozyczki)
        prow = _parse_float(cd.prowizja)
        if ckk > 0 and kp > 0 and prow > 0:
            fv = validate_credit(
                calkowita_kwota_kredytu=ckk,
                kwota_pozyczki=kp,
                prowizja=prow,
                ubezpieczenie=_parse_float(cd.ubezpieczenie),
                oprocentowanie=_parse_float(cd.oprocentowanie) / 100 if cd.oprocentowanie and _parse_float(cd.oprocentowanie) > 1 else _parse_float(cd.oprocentowanie),
                liczba_rat=int(_parse_float(cd.liczba_rat, 60)),
                kwota_raty_bank=_parse_float(cd.kwota_raty),
                rrso_bank=_parse_float(cd.rrso_bank),
                data_wyplaty=_parse_date(cd.data_zawarcia_umowy) or datetime.now(),
                dzien_raty=int(_parse_float(cd.dzien_platnosci_raty, 15)),
                zaswiadczenie_odsetki=_parse_float(cd.suma_odsetek_zaplaconych) or None,
                zaswiadczenie_kapital=_parse_float(cd.suma_kapitalu_splaconego) or None,
                zaswiadczenie_prowizja=_parse_float(cd.suma_prowizji_zaplaconej) or None,
            )
            fv_result = serialize_validation(fv)
            case_ctx.financial_validation = fv_result
            context_engine._apply_financial_to_credit_data(case_ctx, fv_result)
    except Exception:
        pass

    # Regenerate document
    output_filename = f"Pozew_SKD_{session_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
    output_path = str(OUTPUT_DIR / output_filename)

    _, report = generate_lawsuit_autonomous(
        template_path=session["template_path"],
        output_path=output_path,
        case_context=case_ctx,
    )

    filled = sum(1 for r in report if r['status'] == 'filled')
    missing = sum(1 for r in report if r['status'] == 'missing')

    session["output_path"] = output_path
    session["status"] = "completed"
    session["financial_validation"] = fv_result

    return {
        "session_id": session_id,
        "status": "completed",
        "fields_filled": filled,
        "fields_missing": missing,
        "pending_questions": [
            {"question_id": q.question_id, "field_name": q.field_name,
             "question_pl": q.question_pl, "options": q.options,
             "severity": q.severity}
            for q in case_ctx.pending_questions
        ],
        "financial_validation": fv_result,
        "extracted_data": _credit_data_to_dict(cd),
        "resolution_log": case_ctx.resolution_log,
        "download_url": f"/api/download/{session_id}",
    }


@router.get("/download/{session_id}")
async def download_document(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Sesja nie znaleziona")

    output_path = sessions[session_id].get("output_path")
    if not output_path or not os.path.exists(output_path):
        raise HTTPException(404, "Dokument nie został jeszcze wygenerowany")

    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=os.path.basename(output_path),
    )


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Sesja nie znaleziona")
    s = sessions[session_id]
    safe = {k: v for k, v in s.items() if k not in ('classified_docs',)}
    return safe


def _credit_data_to_dict(cd: CreditData) -> dict:
    result = {}
    from dataclasses import fields
    for f in fields(cd):
        val = getattr(cd, f.name)
        if val is not None:
            result[f.name] = val
    return result
