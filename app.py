# Simplified JD ↔ Resume Matcher
# Save as app.py and run: streamlit run app.py
# Requirements: streamlit pandas openpyxl python-docx pdfminer.six rapidfuzz

import streamlit as st
import pandas as pd
import io, re, json
from docx import Document
from pdfminer.high_level import extract_text as pdf_extract_text
from rapidfuzz import fuzz

st.set_page_config(page_title="JD ↔ Resume Matcher (Simple UI)", layout="wide")

# ---------------- Helpers ----------------
def read_text_file(uploaded):
    data = uploaded.read()
    try:
        return data.decode("utf-8", errors="ignore")
    except:
        try:
            return data.decode("latin-1", errors="ignore")
        except:
            return ""

def read_docx(uploaded):
    try:
        uploaded.seek(0)
        doc = Document(uploaded)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""

def read_pdf(uploaded):
    try:
        uploaded.seek(0)
        return pdf_extract_text(uploaded)
    except Exception:
        return ""

def extract_text_any(uploaded):
    name = getattr(uploaded, "name", "")
    if name.lower().endswith(".pdf"):
        return read_pdf(uploaded)
    if name.lower().endswith(".docx"):
        return read_docx(uploaded)
    return read_text_file(uploaded)

# normalization helpers
NOISE_RE = re.compile(r'\b(exp|exp\.|experience|expertise|minimum|should|years|yrs)\b', re.I)
PUNC_RE = re.compile(r'[\(\)\[\]\-_:,\/]+')

def normalize_skill_label(s):
    if not s:
        return ""
    x = s.strip()
    x = NOISE_RE.sub(" ", x)
    x = PUNC_RE.sub(" ", x)
    x = re.sub(r'\s+', ' ', x).strip()
    return x

def parse_skill_line(line):
    """
    Accept lines like:
      TOSCA (5)
      TOSCA|5
      CI/CD
    Returns (skill_normalized, required_years_or_None)
    """
    if not line or not line.strip():
        return None, None
    raw = line.strip()
    # look for (N) or |N patterns
    m = re.search(r'\(?\b(\d{1,2})\b\)?', raw)
    years = None
    # prefer explicit separators like | or ( )
    m_pipe = re.search(r'\|\s*(\d{1,2})', raw)
    m_paren = re.search(r'\(\s*(\d{1,2})\s*\)', raw)
    if m_pipe:
        years = int(m_pipe.group(1))
        skill = raw.split('|',1)[0].strip()
    elif m_paren:
        years = int(m_paren.group(1))
        skill = re.sub(r'\(\s*\d{1,2}\s*\)', '', raw).strip()
    else:
        # If a number exists anywhere, take it (less preferred)
        if m:
            years = int(m.group(1))
            skill = re.sub(r'\d+', '', raw).strip()
        else:
            skill = raw
    skill_norm = normalize_skill_label(skill)
    return skill_norm, years

def has_skill(text, skill, synonyms=None, strict=True):
    """
    Conservative presence check:
      - substring or synonyms match
      - whole-token matching for short tokens (strict)
      - optional fuzzy for longer phrases (not used when strict True)
    """
    if not text or not skill:
        return False
    t = text.lower()
    s = skill.lower().strip()
    candidates = [s]
    if synonyms:
        candidates += [v.lower() for v in synonyms]
    for c in candidates:
        if c and c in t:
            return True
    # token whole-word check
    tokens = [w for w in re.split(r'\W+', s) if w]
    if tokens and all(re.search(rf'\b{re.escape(tok)}\b', t) for tok in tokens):
        return True
    # fallback fuzzy only for longer phrases and when strict is False
    if not strict and len(s) > 3:
        try:
            score = fuzz.partial_ratio(s, t)
            return score >= 85
        except:
            return False
    return False

def extract_years_near(text, skill_terms, window=120):
    """
    Search for numeric years near occurrences of any skill_term.
    """
    t = text.lower()
    years_found = []
    for term in skill_terms:
        for m in re.finditer(re.escape(term.lower()), t):
            start = max(0, m.start()-window)
            end = min(len(t), m.end()+window)
            window_text = t[start:end]
            found = re.findall(r'(\d+\s*[-–]\s*\d+|\d+\+?)(?:\s*(?:years|yrs|y))', window_text)
            for g in found:
                if "-" in g:
                    nums = re.findall(r'(\d+)', g)
                    if nums:
                        years_found.append(int(nums[-1]))
                else:
                    n = re.search(r'(\d+)', g)
                    if n:
                        years_found.append(int(n.group(1)))
    if years_found:
        return max(years_found)
    # fallback to any years in resume
    m2 = re.findall(r'(\d+\s*[-–]\s*\d+|\d+\+?)(?:\s*(?:years|yrs|y))', t)
    for g in m2:
        if "-" in g:
            nums = re.findall(r'(\d+)', g)
            if nums:
                years_found.append(int(nums[-1]))
        else:
            n = re.search(r'(\d+)', g)
            if n:
                years_found.append(int(n.group(1)))
    return max(years_found) if years_found else None

# simple default synonyms map to help short tokens (can be extended later)
DEFAULT_SYNONYMS = {
    "ci/cd": ["ci/cd","ci cd","continuous integration","continuous delivery","jenkins","pipeline","devops"],
    "tosca": ["tosca","tricentis tosca","tricentis"],
    "loadrunner": ["loadrunner","performance center","vu gen","vugen","vugen scripting"]
}

# ---------------- UI ----------------
st.title("JD ↔ Resume Matcher — Simple UI")
st.markdown("Use the two boxes below to provide Mandatory (must-have) skills and Good-to-have skills. Use `(N)` or `|N` to indicate required years, e.g., `TOSCA (5)` or `TOSCA|5`.")

col1, col2 = st.columns([1,1])

with col1:
    st.header("1) Upload JD")
    jd_file = st.file_uploader("Upload JD (PDF/DOCX/TXT)", type=["pdf","docx","txt"], key="jd_in")
    auto_fill_btn = st.button("Auto-fill Mandatory / Good-to-have from JD")
    st.markdown("**JD preview (editable)**")
    jd_preview = st.text_area("JD text", value="", height=200, key="jd_preview")

with col2:
    st.header("2) Upload Resumes")
    resumes = st.file_uploader("Upload Resumes (PDF/DOCX/TXT) - select multiple", type=["pdf","docx","txt"], accept_multiple_files=True, key="resumes_in")
    st.info("Prefer DOCX or text-based PDFs. For scanned PDFs do OCR externally.")

st.markdown("---")
st.header("3) Skills (edit then Run Matching)")
left_box, right_box = st.columns([1,1])

# default placeholders
mandatory_placeholder = "TOSCA (5)\nPerformance Testing (6)\nLoadRunner"
good_placeholder = "Dynatrace\nSplunk\nCI/CD"

with left_box:
    st.subheader("Mandatory / Must-have (one per line)")
    st.caption("Use `(N)` or `|N` to indicate required years. Example: TOSCA (5) or Performance Testing|6")
    mandatory_text = st.text_area("Mandatory skills", value=mandatory_placeholder, height=200, key="mandatory_area")

with right_box:
    st.subheader("Good-to-have / Nice-to-have (one per line)")
    st.caption("These are optional and contribute to the 20% bucket.")
    good_text = st.text_area("Good-to-have skills", value=good_placeholder, height=200, key="good_area")

st.markdown("---")
st.header("4) Matching Controls")
presence_weight = st.slider("Presence weight (%) (presence vs experience for a skill)", 40, 90, 60)
strict_short_tokens = st.checkbox("Strict matching for short tokens (avoid fuzzy for acronyms)", value=True)
run_btn = st.button("Run Matching", type="primary")

# Auto-fill logic: extract simple candidates from JD
if auto_fill_btn and jd_file:
    extracted = ""
    if jd_file.name.lower().endswith(".pdf"):
        extracted = read_pdf(jd_file)
    elif jd_file.name.lower().endswith(".docx"):
        extracted = read_docx(jd_file)
    else:
        extracted = read_text_file(jd_file)
    extracted = extracted or ""
    st.session_state['jd_preview'] = extracted
    # simple heuristics: pick master words and capitalized phrases
    master = ["TOSCA","CI/CD","LoadRunner","Dynatrace","Splunk","Performance Testing","Mainframe"]
    found = []
    for m in master:
        if m.lower() in extracted.lower():
            found.append(m)
    caps = re.findall(r'\b([A-Z][A-Za-z0-9+\-#.]{1,}(?:\s+[A-Z][A-Za-z0-9+\-#.]{1,}){0,2})\b', extracted)
    for c in caps:
        if len(c.split())<=4 and c not in found:
            found.append(c)
    # populate text boxes: first half mandatory if contains "minimum" or "required" near phrase
    mand = []
    good = []
    for c in found:
        # check if 'minimum' or 'years' near phrase -> put in mandatory
        pat = re.search(rf'(?:minimum|at least|required).{{0,60}}{re.escape(c)}', extracted, re.I)
        if pat:
            mand.append(c)
        else:
            # default: some go to good-to-have
            good.append(c)
    if mand:
        st.session_state['mandatory_area'] = "\n".join([f"{m}" for m in mand]) + ("\n" + st.session_state.get('mandatory_area','') if st.session_state.get('mandatory_area') else "")
    if good:
        st.session_state['good_area'] = "\n".join([g for g in good]) + ("\n" + st.session_state.get('good_area','') if st.session_state.get('good_area') else "")
    st.success("Auto-fill done — edit lists if needed, then run matching.")

# Parse skill lists
def parse_list(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = []
    for ln in lines:
        skill, yrs = parse_skill_line(ln)
        out.append({"skill":skill, "req":yrs})
    return out

if run_btn:
    if not jd_file:
        st.error("Please upload a JD before running.")
    elif not resumes:
        st.error("Please upload at least one resume before running.")
    else:
        # final skill arrays
        mandatory_skills = parse_list(mandatory_text)
        good_skills = parse_list(good_text)
        # synonyms use DEFAULT_SYNONYMS if term exists; not editable in this simple UI
        synonyms = DEFAULT_SYNONYMS
        pres_w = presence_weight/100.0
        exp_w = 1.0 - pres_w
        results = []
        for up in resumes:
            fname = up.name
            txt = extract_text_any(up) or ""
            row = {"Resume": fname}
            mand_scores = []
            good_scores = []
            # mandatory
            for item in mandatory_skills:
                name = item['skill']
                req = item['req']
                syns = synonyms.get(name.lower(), [])
                present = has_skill(txt, name, synonyms=syns, strict=strict_short_tokens)
                years = extract_years_near(txt, [name]+syns) if present else None
                if req:
                    if present and years is not None:
                        exp_ratio = min(years / req, 1.0)
                        score = pres_w*1.0 + exp_w*exp_ratio
                    elif present and years is None:
                        score = pres_w*1.0 + exp_w*0.0
                    else:
                        score = 0.0
                else:
                    score = 1.0 if present else 0.0
                row[f"{name}_presence"] = "Yes" if present else "No"
                row[f"{name}_years"] = f"{years}y" if years else ""
                row[f"{name}_req"] = f"{req}y" if req else ""
                row[f"{name}_score_%"] = round(score*100,2)
                mand_scores.append(score)
            # good-to-have
            for item in good_skills:
                name = item['skill']
                req = item['req']
                syns = synonyms.get(name.lower(), [])
                present = has_skill(txt, name, synonyms=syns, strict=strict_short_tokens)
                years = extract_years_near(txt, [name]+syns) if present else None
                if req:
                    if present and years is not None:
                        exp_ratio = min(years / req, 1.0)
                        score = pres_w*1.0 + exp_w*exp_ratio
                    elif present and years is None:
                        score = pres_w*1.0 + exp_w*0.0
                    else:
                        score = 0.0
                else:
                    score = 1.0 if present else 0.0
                row[f"{name}_presence"] = "Yes" if present else "No"
                row[f"{name}_years"] = f"{years}y" if years else ""
                row[f"{name}_req"] = f"{req}y" if req else ""
                row[f"{name}_score_%"] = round(score*100,2)
                good_scores.append(score)
            # aggregate: Mandatory = 80%, Good = 20%
            mand_avg = sum(mand_scores)/len(mand_scores) if mand_scores else 0.0
            good_avg = sum(good_scores)/len(good_scores) if good_scores else 0.0
            overall = round((mand_avg*0.8 + good_avg*0.2)*100,2)
            row["Match %"] = overall
            results.append(row)
        df = pd.DataFrame(results)
        st.success("Matching complete — preview below:")
        st.dataframe(df)
        # excel export
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='JD Match Analysis')
        output.seek(0)
        st.download_button("Download Excel", data=output, file_name="jd_match_results_simple.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.markdown("---")
st.caption("If you want synonyms editing, stricter controls, or persistence across sessions, I can add that next.")
