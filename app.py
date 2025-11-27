# JD-Resume-Matcher Streamlit app
# Save this file as `app.py` and run: `streamlit run app.py`
# Requirements (pip install): streamlit pandas openpyxl python-docx PyPDF2 fuzzywuzzy[speedup]
# Optional (better matching): pip install rapidfuzz

import streamlit as st
import pandas as pd
import io
import re
from collections import Counter
from pdfminer.high_level import extract_text as pdf_extract_text
from docx import Document
from rapidfuzz import fuzz

st.set_page_config(page_title="JD ↔ Resume Matcher", layout="wide")

st.title("JD ↔ Resume Matcher")
st.markdown("Upload a Job Description (PDF / DOCX / TXT) and multiple resumes; the app will deconstruct the JD into skills/keywords, match resumes to those skills, and export results in the Excel format like your template.")

# ----------------- helpers -----------------

def read_text_file(uploaded):
    data = uploaded.read()
    try:
        return data.decode('utf-8')
    except Exception:
        return data.decode('latin-1', errors='ignore')


def read_pdf(uploaded):
    # pdfminer expects a file path or file-like object; we have BytesIO so pass it directly
    try:
        uploaded.seek(0)
        return pdf_extract_text(uploaded)
    except Exception as e:
        st.error(f"PDF parsing error: {e}")
        return ""


def read_docx(uploaded):
    uploaded.seek(0)
    doc = Document(uploaded)
    parts = []
    for p in doc.paragraphs:
        parts.append(p.text)
    return '\n'.join(parts)


def normalize_text(text):
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# small master skills list (expandable)
MASTER_SKILLS = [
    'Java','Spring Boot','Spring','Hibernate','SQL','MySQL','PostgreSQL','Oracle','NoSQL',
    'MongoDB','Docker','Kubernetes','AWS','Azure','GCP','CI/CD','Jenkins','Git','SVN','Bitbucket',
    'Microservices','REST','SOAP','Hibernate','Agile','Scrum','Linux','Python','Node.js','React',
    'Angular','CSS','HTML','TypeScript','Redis','Kafka','RabbitMQ','Elasticsearch','Spark','Hadoop'
]


def extract_skill_candidates(jd_text):
    # 1) find known skills from master list
    found = []
    text_low = jd_text.lower()
    for s in MASTER_SKILLS:
        if s.lower() in text_low:
            found.append(s)
    # 2) heuristics: Capitalized multi-word tokens that look like tech names
    caps = re.findall(r'\b([A-Z][A-Za-z0-9+\-#.]{1,}(?:\s+[A-Z][A-Za-z0-9+\-#.]{1,}){0,2})\b', jd_text)
    # filter and add if not duplicates
    for c in caps:
        if len(c.split()) <= 4 and c.lower() not in [x.lower() for x in found]:
            found.append(c)
    # 3) frequency-based: pick top nouns/phrases (simple)
    # return unique preserving order
    seen = set()
    res = []
    for x in found:
        key = x.lower()
        if key not in seen:
            seen.add(key)
            res.append(x)
    return res


def parse_resume(file_obj, filename):
    name = filename
    text = ''
    if filename.lower().endswith('.pdf'):
        text = read_pdf(file_obj)
    elif filename.lower().endswith('.docx'):
        text = read_docx(file_obj)
    elif filename.lower().endswith('.txt'):
        text = read_text_file(file_obj)
    else:
        # try text
        try:
            text = read_text_file(file_obj)
        except Exception:
            text = ''
    return normalize_text(text)

# fuzzy contains to allow small variations

def has_skill(text, skill):
    if not skill:
        return False
    text_low = text.lower()
    skill_low = skill.lower()
    # direct substring
    if skill_low in text_low:
        return True
    # fuzzy token ratio
    # check occurrences of words from skill
    words = skill_low.split()
    if all(w in text_low for w in words if len(w)>=2):
        return True
    # fallback fuzzy
    score = fuzz.partial_ratio(skill_low, text_low)
    return score >= 80

# ----------------- UI -----------------

with st.sidebar:
    st.header('Options')
    jd_file = st.file_uploader('Upload JD (PDF / DOCX / TXT)', type=['pdf','docx','txt'], key='jd')
    resume_files = st.file_uploader('Upload Resumes (PDF / DOCX / TXT) - you can select multiple', type=['pdf','docx','txt'], accept_multiple_files=True, key='resumes')
    min_match = st.slider('Minimum Match % to show/highlight', 0, 100, 50)
    use_master = st.checkbox('Use built-in master skills list (adds common skills)', value=True)
    st.markdown('---')
    st.markdown('How matching works: the app extracts candidate skills from the JD, then checks each resume for those skills (substring + fuzzy checks). Match % = matched_skills / total_jd_skills.')

if not jd_file:
    st.info('Please upload a JD to start. Use the sidebar file uploader.')
    st.stop()

# read JD
jd_file.seek(0)
if jd_file.type == 'application/pdf' or jd_file.name.lower().endswith('.pdf'):
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

# extract skills
candidates = extract_skill_candidates(jd_text)
if use_master:
    # merge master skills that are mentioned
    for s in MASTER_SKILLS:
        if s.lower() in jd_text.lower() and s not in candidates:
            candidates.append(s)

if not candidates:
    st.warning('No skill candidates found automatically. Add skills manually below.')

st.subheader('Deconstructed Skills / Keywords')
skills_input = st.text_area('Edit skill list (one per line). The matching will use these skills in this order.', value='\n'.join(candidates), height=200)
skills = [s.strip() for s in skills_input.splitlines() if s.strip()]

if not resume_files:
    st.warning('Upload one or more resumes to perform matching (sidebar).')
    st.stop()

# parse resumes and match
rows = []
for uploaded in resume_files:
    try:
        uploaded.seek(0)
        text = parse_resume(uploaded, uploaded.name)
    except Exception as e:
        st.error(f"Error parsing {uploaded.name}: {e}")
        text = ''
    matched = {}
    match_count = 0
    for skl in skills:
        present = has_skill(text, skl)
        matched[skl] = 'Yes' if present else 'No'
        if present: match_count += 1
    total = len(skills) if len(skills)>0 else 1
    match_pct = round((match_count/total)*100,2)
    rows.append({'Resume': uploaded.name, 'Match %': match_pct, **matched})

# create dataframe with columns matching template order
cols = ['Resume','Match %'] + skills
df = pd.DataFrame(rows)
# ensure missing columns filled
for c in cols:
    if c not in df.columns:
        df[c] = ''
df = df[cols]

st.subheader('Match Results')
st.dataframe(df)

# filtering
filtered = df[df['Match %']>=min_match]
st.markdown(f'**{len(filtered)}** resumes meet the minimum match of {min_match}%')
st.dataframe(filtered)

# export to excel
output = io.BytesIO()
with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df.to_excel(writer, index=False, sheet_name='JD Match Analysis')
output.seek(0)

st.download_button('Download results as Excel', data=output, file_name='jd_resume_match_results.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

st.markdown('---')
st.markdown('Notes:')
st.markdown('- This is a first-pass keyword-based matcher. For better accuracy, consider adding a curated skill list, using an ontology of skills, or upgrading matching to semantic matching with embeddings (OpenAI/other).')
st.markdown('- The app attempts to extract text from PDFs and DOCX but results depend on file content (images/scanned PDFs will not have text unless OCR is run).')


