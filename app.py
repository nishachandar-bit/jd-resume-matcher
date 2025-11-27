# JD-Resume-Matcher Streamlit app (with experience parsing & weighted scoring)
# Save as app.py
# Requirements: streamlit pandas openpyxl python-docx pdfminer.six rapidfuzz

import streamlit as st
import pandas as pd
import io
import re
from docx import Document
from pdfminer.high_level import extract_text as pdf_extract_text
from rapidfuzz import fuzz

st.set_page_config(page_title="JD ↔ Resume Matcher", layout="wide")

st.title("JD ↔ Resume Matcher (with experience parsing)")
st.markdown("Upload a Job Description (PDF / DOCX / TXT) and multiple resumes; the app will extract required years per skill, parse years from resumes, and compute weighted match scores.")

# ----------------- helpers -----------------

def read_text_file(uploaded):
    data = uploaded.read()
    try:
        return data.decode('utf-8')
    except Exception:
        return data.decode('latin-1', errors='ignore')

def read_pdf(uploaded):
    try:
        uploaded.seek(0)
        return pdf_extract_text(uploaded)
    except Exception as e:
        st.warning(f"PDF parsing warning: {e}")
        return ""

def read_docx(uploaded):
    try:
        uploaded.seek(0)
        doc = Document(uploaded)
        parts = [p.text for p in doc.paragraphs]
        return "\n".join(parts)
    except Exception as e:
        st.warning(f"DOCX parsing warning: {e}")
        return ""

def normalize_text(text):
    text = re.sub(r'\s+', ' ', text or '')
    return text.strip()

# parse numbers / ranges
def parse_years_from_text(s):
    if not s:
        return None
    s = s.strip()
    # range like 3-5 -> take upper bound
    m = re.search(r'(\d+)\s*-\s*(\d+)', s)
    if m:
        return int(m.group(2))
    m = re.search(r'(\d+)\+?', s)
    if m:
        return int(m.group(1))
    return None

# extract required experience for a skill from JD text
def extract_required_experience_for_skill(jd_text, skill):
    if not jd_text or not skill:
        return None
    jd_low = jd_text.lower()
    skill_low = re.escape(skill.lower())
    # pattern 1: "minimum 5 years ... in TOSCA" or "at least 5 years of experience in TOSCA"
    m = re.search(rf'(?:minimum|at least|required|needs?|must have|experience of)\s+(\d+)\s*(?:\+)?\s*(?:years|yrs|y)\b.*?(?:in|with)?\s*(?:{skill_low})', jd_low)
    if m:
        return int(m.group(1))
    # pattern 2: "TOSCA (5+ years)" or "TOSCA - 5 years"
    m = re.search(rf'(?:{skill_low}).{{0,60}}?(\d+\+?\s*(?:years|yrs|y))', jd_low)
    if m:
        return parse_years_from_text(m.group(1))
    # pattern 3: "5 years of experience in TOSCA"
    m = re.search(rf'(\d+\+?\s*(?:years|yrs|y)).{{0,60}}?(?:in|with)\s+{skill_low}', jd_low)
    if m:
        return parse_years_from_text(m.group(1))
    return None

# extract years for a skill from a resume
def extract_years_for_skill_from_resume(res_text, skill):
    if not res_text or not skill:
        return None
    res_low = res_text.lower()
    skill_low = re.escape(skill.lower())
    years_found = []
    # search small windows containing the skill
    for m in re.finditer(rf'(.{{0,60}}{skill_low}.{{0,60}})', res_low):
        window = m.group(0)
        # patterns like "5 years", "4+ yrs", "3-5 years"
        m2 = re.search(r'(\d+\s*-\s*\d+|\d+\+?)(?=\s*(?:years|yrs|y))', window)
        if m2:
            y = parse_years_from_text(m2.group(1))
            if y is not None:
                years_found.append(y)
        else:
            m3 = re.search(r'(\d+\s*-\s*\d+|\d+\+?)\s*(?:years|yrs|y)\s*(?:of\s+experience)?', window)
            if m3:
                y = parse_years_from_text(m3.group(1))
                if y:
                    years_found.append(y)
    # fallback: global search for "X years of experience" and assume applies (less precise)
    if not years_found:
        m4 = re.search(r'(\d+\s*-\s*\d+|\d+\+?)\s*(?:years|yrs|y)\s*(?:of\s+experience)?', res_low)
        if m4:
            y = parse_years_from_text(m4.group(1))
            if y:
                years_found.append(y)
    if years_found:
        return max(years_found)
    return None

# presence check (existing fuzzy logic)
def has_skill(text, skill):
    if not skill:
        return False
    text_low = (text or "").lower()
    skill_low = skill.lower()
    if skill_low in text_low:
        return True
    words = [w for w in re.split(r'\W+', skill_low) if w]
    if words and all(w in text_low for w in words if len(w) >= 2):
        return True
    try:
        score = fuzz.partial_ratio(skill_low, text_low)
        return score >= 80
    except Exception:
        return False

# ----------------- UI -----------------
with st.sidebar:
    st.header('Options')
    jd_file = st.file_uploader('Upload JD (PDF / DOCX / TXT)', type=['pdf','docx','txt'], key='jd')
    resume_files = st.file_uploader('Upload Resumes (PDF / DOCX / TXT) - select multiple', type=['pdf','docx','txt'], accept_multiple_files=True, key='resumes')
    min_match = st.slider('Minimum Match % to show', 0, 100, 50)
    use_master = st.checkbox('Use built-in master skills list', value=True)
    st.markdown('---')
    st.markdown('Matching: presence (60%) + experience fulfillment (40%) when JD specifies years.')

if not jd_file:
    st.info('Please upload a JD to start.')
    st.stop()

# read JD text
jd_file.seek(0)
if jd_file.name.lower().endswith('.pdf'):
    jd_text = read_pdf(jd_file)
elif jd_file.name.lower().endswith('.docx'):
    jd_text = read_docx(jd_file)
else:
    jd_text = read_text_file(jd_file)

jd_text = normalize_text(jd_text)
if not jd_text:
    st.error('Could not extract text from the JD file.')
    st.stop()

st.subheader('Job Description (extracted text)')
st.text_area('JD preview (editable)', value=jd_text, height=200, key='jd_preview')
jd_text = st.session_state['jd_preview']

# initial skill extraction (simple heuristics + master list)
MASTER_SKILLS = [
    'Java','Spring Boot','Spring','Hibernate','SQL','MySQL','PostgreSQL','Oracle','NoSQL',
    'MongoDB','Docker','Kubernetes','AWS','Azure','GCP','CI/CD','Jenkins','Git','SVN','Bitbucket',
    'Microservices','REST','SOAP','Agile','Scrum','Linux','Python','Node.js','React','Angular',
    'CSS','HTML','TypeScript','Redis','Kafka','RabbitMQ','Elasticsearch','Spark','Hadoop','TOSCA'
]

def extract_skill_candidates(jd_text):
    found = []
    low = (jd_text or "").lower()
    for s in MASTER_SKILLS:
        if s.lower() in low and s not in found:
            found.append(s)
    caps = re.findall(r'\b([A-Z][A-Za-z0-9+\-#.]{1,}(?:\s+[A-Z][A-Za-z0-9+\-#.]{1,}){0,2})\b', jd_text)
    for c in caps:
        if len(c.split()) <= 4 and c.lower() not in [x.lower() for x in found]:
            found.append(c)
    seen = set()
    res = []
    for x in found:
        if x.lower() not in seen:
            seen.add(x.lower())
            res.append(x)
    return res

candidates = extract_skill_candidates(jd_text)
if use_master:
    for s in MASTER_SKILLS:
        if s.lower() in jd_text.lower() and s not in candidates:
            candidates.append(s)

st.subheader('Deconstructed Skills / Keywords')
skills_input = st.text_area('Edit skill list (one per line).', value='\n'.join(candidates), height=200)
skills = [s.strip() for s in skills_input.splitlines() if s.strip()]

# extract required years per skill from JD
skill_requirements = {}
for skl in skills:
    req = extract_required_experience_for_skill(jd_text, skl)
    skill_requirements[skl] = req  # may be None

if not resume_files:
    st.warning('Upload resumes in the sidebar to run matching.')
    st.stop()

rows = []
for uploaded in resume_files:
    try:
        uploaded.seek(0)
        # parse text based on extension
        if uploaded.name.lower().endswith('.pdf'):
            res_text = read_pdf(uploaded)
        elif uploaded.name.lower().endswith('.docx'):
            res_text = read_docx(uploaded)
        else:
            res_text = read_text_file(uploaded)
        res_text = normalize_text(res_text)
    except Exception as e:
        st.warning(f"Error parsing {uploaded.name}: {e}")
        res_text = ""

    matched_info = {}
    skill_scores = []
    for skl in skills:
        present = has_skill(res_text, skl)
        years = extract_years_for_skill_from_resume(res_text, skl)
        req = skill_requirements.get(skl)
        req_satisfied = ''
        score = 0.0
        # scoring logic
        if req is not None:
            # JD specified years
            if years is not None:
                req_satisfied = 'Yes' if years >= req else 'No'
                exp_ratio = min(years / req, 1.0)
            else:
                # no explicit years in resume
                req_satisfied = 'No'  # conservative
                exp_ratio = 0.0
            presence_val = 1.0 if present else 0.0
            score = 0.6 * presence_val + 0.4 * exp_ratio
        else:
            # no requirement given in JD: presence is sufficient
            presence_val = 1.0 if present else 0.0
            score = presence_val  # 1 or 0

        skill_scores.append(score)
        matched_info[f"{skl}_presence"] = 'Yes' if present else 'No'
        matched_info[f"{skl}_years"] = f"{years}y" if years is not None else ''
        matched_info[f"{skl}_req"] = f"{req}y" if req is not None else ''
        matched_info[f"{skl}_req_satisfied"] = req_satisfied
        matched_info[f"{skl}_score_%"] = round(score * 100, 2)

    overall_pct = round((sum(skill_scores) / len(skill_scores)) * 100, 2) if skills else 0.0
    row = {'Resume': uploaded.name, 'Match %': overall_pct}
    row.update(matched_info)
    rows.append(row)

# Build dataframe with a stable columns order: Resume, Match %, then per-skill groups
cols = ['Resume', 'Match %']
for skl in skills:
    cols += [f"{skl}_presence", f"{skl}_years", f"{skl}_req", f"{skl}_req_satisfied", f"{skl}_score_%"]

df = pd.DataFrame(rows)
for c in cols:
    if c not in df.columns:
        df[c] = ''
df = df[cols]

st.subheader('Match Results')
st.dataframe(df)

filtered = df[df['Match %'] >= min_match]
st.markdown(f"**{len(filtered)}** resumes meet the minimum match of {min_match}%")
st.dataframe(filtered)

# export to excel
output = io.BytesIO()
with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df.to_excel(writer, index=False, sheet_name='JD Match Analysis')
output.seek(0)

st.download_button(
    'Download results as Excel',
    data=output,
    file_name='jd_resume_match_results.xlsx',
    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
)

st.markdown('---')
st.markdown('Notes:')
st.markdown('- Scoring: presence = 60% and experience fulfillment = 40% when JD specifies years.')
st.markdown('- If JD does not specify years for a skill, presence alone counts as match (1.0).')
st.markdown('- The extractor looks for numeric mentions near each skill in the resume; it relies on explicit numbers (e.g., \"5 years\").')

