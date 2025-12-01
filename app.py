import os
import io
import streamlit as st
import pdfplumber
import docx
from openai import OpenAI

# --------- CONFIG & SECRETS ---------

# Read secrets (works locally via .streamlit/secrets.toml and on Streamlit Cloud)
PASSCODE = st.secrets.get("APP_PASSCODE")
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    st.error(
        "No OpenAI API key found. "
        "Set OPENAI_API_KEY in .streamlit/secrets.toml (local) or in Streamlit Cloud Secrets."
    )
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)


# --------- AUTH / PASSCODE GATE ---------

def check_password() -> bool:
    """Simple passcode gate using Streamlit session_state + secrets."""

    if PASSCODE is None:
        st.warning(
            "APP_PASSCODE is not set in secrets. "
            "Anyone with the URL can access this app."
        )
        # If you want to *require* a passcode, uncomment next line:
        # st.stop()

    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    def _submit():
        if PASSCODE is None:
            # No passcode configured → treat as always authenticated
            st.session_state["authenticated"] = True
            st.session_state["login_error"] = ""
            return

        if st.session_state.get("passcode_input", "") == PASSCODE:
            st.session_state["authenticated"] = True
            st.session_state["login_error"] = ""
        else:
            st.session_state["authenticated"] = False
            st.session_state["login_error"] = "Incorrect passcode. Please try again."

    if not st.session_state["authenticated"]:
        st.title("AI Discharge Summary Demo")
        st.write("Please enter the passcode to access this demo.")

        st.text_input(
            "Passcode",
            type="password",
            key="passcode_input",
            on_change=_submit,
        )

        if st.session_state.get("login_error"):
            st.error(st.session_state["login_error"])

        return False

    return True


if not check_password():
    st.stop()


# --------- HELPERS: FILE PARSING & LLM CALL ---------

def extract_text_from_file(uploaded_file) -> str | None:
    """Extract plain text from PDF, DOCX, or TXT uploads."""
    if uploaded_file is None:
        return None

    mime = uploaded_file.type

    try:
        # PDF
        if mime == "application/pdf":
            text_pages = []
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    text_pages.append(page_text)
            return "\n\n".join(text_pages).strip()

        # DOCX
        elif mime in [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ]:
            # python-docx can read file-like objects directly
            doc = docx.Document(uploaded_file)
            return "\n".join(p.text for p in doc.paragraphs).strip()

        # Plain text
        elif mime.startswith("text/"):
            return uploaded_file.read().decode("utf-8").strip()

        else:
            return None

    except Exception as e:
        st.error(f"Error reading file: {e}")
        return None


SYSTEM_PROMPT = """
You are a nurse explaining hospital discharge instructions to a patient and their family.

Take the discharge summary below and create a clear, friendly summary for the patient.

Requirements:
- Reading level: around 6th–8th grade.
- Use short sentences and bullet points.
- Avoid medical jargon when possible. If you must use a medical term, explain it in plain language.
- Never change medical facts, medicine names, doses, or dates.
- Preserve all safety-critical information: red-flag symptoms, when to call the clinic,
  when to go to the ER, and follow-up appointments.
- If something important is missing or unclear in the original text, say:
  "This was not clearly explained in your record."

Output structure:
1. Why you were in the hospital
2. What we did for you
3. Your main health problems (in everyday words)
4. Your medicines (what changed, what stayed the same)
5. What you should do at home (diet, activity, monitoring)
6. Warning signs – call your clinic
7. Emergency signs – call 911
8. Your follow-up visits (who, when, and why)
"""


def generate_summary(discharge_text: str) -> str:
    resp = client.chat.completions.create(
        model="gpt-4.1-mini",  # change if you prefer another model
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Discharge summary:\n{discharge_text}"},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content


# --------- MAIN UI ---------

st.set_page_config(page_title="Patient-Friendly Discharge Summary", layout="wide")

st.title("Patient-Friendly Discharge Summary")
st.caption(
    "Demo app: upload a discharge summary or paste the text, and get a simpler explanation "
    "for patients and families. Do not use with real patient data."
)

with st.sidebar:
    st.header("Session")
    if st.button("Log out"):
        st.session_state["authenticated"] = False
        st.experimental_rerun()

    st.markdown("**Input method**")
    input_method = st.radio(
        "",
        options=["Upload file (PDF/DOCX/TXT)", "Paste text"],
        index=0,
    )

# Main layout: left = input, right = output
col_input, col_output = st.columns(2)

with col_input:
    st.subheader("Discharge Summary Input")

    discharge_text = ""

    if input_method == "Upload file (PDF/DOCX/TXT)":
        uploaded_file = st.file_uploader(
            "Upload a discharge summary file",
            type=["pdf", "docx", "txt"],
        )
        if uploaded_file is not None:
            extracted = extract_text_from_file(uploaded_file)
            if extracted:
                st.success("File uploaded and text extracted.")
                discharge_text = st.text_area(
                    "Extracted text (you can edit before summarizing):",
                    value=extracted,
                    height=300,
                )
            else:
                st.error("Could not extract text from this file.")
    else:
        discharge_text = st.text_area(
            "Paste the discharge summary here:",
            height=300,
            placeholder="Paste hospital discharge summary / instructions text…",
        )

    generate_clicked = st.button("Generate patient-friendly summary", type="primary")

with col_output:
    st.subheader("Patient-Friendly Summary")

    if generate_clicked:
        if not discharge_text.strip():
            st.error("Please provide some discharge text first.")
        else:
            with st.spinner("Generating summary…"):
                try:
                    summary = generate_summary(discharge_text.strip())
                    st.markdown(summary)
                except Exception as e:
                    st.error(f"Error while calling the language model: {e}")
    else:
        st.info("Upload or paste a discharge summary, then click the button to generate a summary.")