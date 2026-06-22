# ⚖️ Generator Pozwów SKD

Automatyczne generowanie pozwów o Sankcję Kredytu Darmowego z dokumentacji klienta.

---

## 🚀 Deployment — Jak uruchomić aplikację w internecie

Poniżej dwie metody. Obie dadzą Ci publiczny link HTTPS do udostępnienia zespołowi.

---

### METODA 1: Streamlit Community Cloud (DARMOWA, najłatwiejsza)

#### Krok 1: Utwórz konto na GitHub
1. Wejdź na https://github.com i kliknij **Sign up**.
2. Podaj email, hasło, nazwę użytkownika. Potwierdź email.

#### Krok 2: Utwórz repozytorium i wgraj pliki
1. Na GitHub kliknij zielony przycisk **New** (nowe repozytorium).
2. Nazwa: `skd-generator`, Visibility: **Private**, kliknij **Create repository**.
3. Na stronie repozytorium kliknij **uploading an existing file**.
4. Przeciągnij CAŁY folder `skd-generator` (wszystkie pliki) do okna uploadu.
5. Kliknij **Commit changes**.

> **WAŻNE:** Upewnij się, że plik `streamlit_app.py` jest w głównym katalogu repozytorium (nie w podfolderze).

#### Krok 3: Połącz ze Streamlit Cloud
1. Wejdź na https://share.streamlit.io i zaloguj się kontem GitHub.
2. Kliknij **New app**.
3. Wybierz:
   - **Repository:** `twoja-nazwa/skd-generator`
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
4. Kliknij **Advanced settings** (ważne!).
5. W polu **Secrets** wklej:
   ```
   ANTHROPIC_API_KEY = "sk-ant-api03-TWÓJ-KLUCZ-TUTAJ"
   ```
   (Klucz API Anthropic jest opcjonalny — bez niego aplikacja działa w trybie regex.)
6. W polu **Python version** wybierz `3.11`.
7. Kliknij **Deploy!**

#### Krok 4: Gotowe!
- Po 3–5 minutach otrzymasz link: `https://twoja-nazwa-skd-generator.streamlit.app`
- Ten link możesz wysłać współpracownikom — działa w każdej przeglądarce.

---

### METODA 2: Render.com (DARMOWA, lepsza dla dużych plików)

Render obsługuje Docker — OCR skanów działa lepiej niż na Streamlit Cloud.

#### Krok 1: Utwórz konto na Render
1. Wejdź na https://render.com i kliknij **Get Started for Free**.
2. Zaloguj się kontem GitHub (najłatwiej).

#### Krok 2: Utwórz repozytorium GitHub
(Tak samo jak w Metodzie 1, kroki 1–2.)

#### Krok 3: Utwórz Web Service na Render
1. Na Render kliknij **New** → **Web Service**.
2. Połącz z GitHub i wybierz repozytorium `skd-generator`.
3. Ustawienia:
   - **Name:** `skd-generator`
   - **Region:** `Frankfurt (EU)` (najbliższy do Polski)
   - **Runtime:** `Docker`
   - **Instance Type:** `Starter` (darmowy) lub `Standard` (7$/mies, szybszy OCR)
4. W sekcji **Environment Variables** kliknij **Add Environment Variable**:
   - **Key:** `ANTHROPIC_API_KEY`
   - **Value:** `sk-ant-api03-TWÓJ-KLUCZ-TUTAJ`
5. Kliknij **Create Web Service**.

#### Krok 4: Gotowe!
- Po 5–10 minutach (budowanie Dockera) otrzymasz link: `https://skd-generator.onrender.com`
- OCR skanów działa w pełni (Tesseract + Poppler zainstalowane w kontenerze Docker).

---

## 💻 Uruchomienie lokalne (dla programistów)

```bash
# Zainstaluj Tesseract i Poppler (macOS)
brew install tesseract tesseract-lang poppler

# Zainstaluj zależności Python
cd skd-generator
pip install -r requirements.txt

# Uruchom
streamlit run streamlit_app.py

# Opcjonalnie: klucz API
export ANTHROPIC_API_KEY="sk-ant-api03-..."
streamlit run streamlit_app.py
```

Aplikacja otworzy się na http://localhost:8501.

---

## 🔒 Bezpieczeństwo klucza API

- **NIGDY** nie wpisuj klucza API bezpośrednio w kodzie.
- Na Streamlit Cloud: wklej w **Secrets** (ustawienia aplikacji).
- Na Render: dodaj jako **Environment Variable**.
- Lokalnie: `export ANTHROPIC_API_KEY="..."` w terminalu.
- Klucz jest **opcjonalny** — bez niego aplikacja działa w trybie automatycznym (regex + golden rules). Z kluczem dodaje analizę AI naruszeń art. 30 u.k.k.

---

## 📁 Obsługiwane dokumenty

| Dokument | Format | Wymagany? |
|----------|--------|-----------|
| Ankieta klienta | DOCX | ✅ Tak |
| Excel RRSO (obliczenia) | XLSX | ✅ Tak |
| Wyliczenie Gofin | PDF | ✅ Tak |
| Zaświadczenie bankowe | PDF (skan) | ✅ Tak |
| Wezwanie do zapłaty | PDF (skan) | ✅ Tak |
| Oświadczenie SKD | PDF (skan) | Zalecane |
| Wniosek o zaświadczenie | PDF | Zalecane |
| Umowa kredytowa | PDF (skan) | Opcjonalne* |

*Dane z umowy są automatycznie wyciągane z Excel RRSO i zaświadczenia bankowego.

---

## ⚙️ Jak to działa

1. **OCR**: Skanowane PDF-y są przetwarzane przez Tesseract z polskim słownikiem.
2. **Klasyfikacja**: System automatycznie rozpoznaje typ każdego dokumentu (umowa, zaświadczenie, wezwanie...).
3. **Ekstrakcja**: Dane wyciągane z 7+ źródeł: ankieta, Excel, Gofin, zaświadczenie OCR, wezwanie OCR, wnioski, nazwy plików.
4. **Golden Rules**: Deterministyczne reguły prawne obliczają WPS, opłatę, RRSO, hipotetyczną ratę.
5. **Generowanie**: Szablon pozwu wypełniany jest danymi z żółtym podświetleniem (python-docx).
