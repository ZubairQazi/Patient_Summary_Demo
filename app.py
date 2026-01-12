import os
import io
from typing import Optional
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

def extract_text_from_file(uploaded_file) -> Optional[str]:
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


# Chat prompt focuses on answering questions about the provided discharge text.
CHAT_SYSTEM_PROMPT = """
You are a nurse answering patient and family questions about the discharge summary below.

Rules:
- Answer only using information present in the discharge summary.
- If the answer is not in the summary or is unclear, say:
  "This was not clearly explained in your record."
- Keep responses clear, short, and friendly.
- Avoid medical jargon when possible; if you must use it, explain it plainly.
"""


def generate_chat_response(discharge_text: str, messages: list[dict]) -> str:
    context_message = {
        "role": "user",
        "content": f"Discharge summary:\n{discharge_text}",
    }
    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            context_message,
            *messages,
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content


# --------- MAIN UI ---------

st.set_page_config(page_title="Patient-Friendly Discharge Summary", layout="wide")

if "summary_text" not in st.session_state:
    st.session_state["summary_text"] = ""
if "summary_source" not in st.session_state:
    st.session_state["summary_source"] = ""
if "chat_messages" not in st.session_state:
    st.session_state["chat_messages"] = []

header_left, header_right = st.columns([0.8, 0.2])
with header_left:
    st.title("Patient-Friendly Discharge Summary")
with header_right:
    if st.session_state["summary_text"]:
        if st.button("Start new summary", type="primary"):
            st.session_state["summary_text"] = ""
            st.session_state["summary_source"] = ""
            st.session_state["chat_messages"] = []
st.caption(
    "Demo app: upload a discharge summary or paste the text, and get a simpler explanation "
    "for patients and families. Do not use with real patient data."
)


with st.sidebar:
    st.header("Session")
    if st.button("Log out"):
        st.session_state["authenticated"] = False
        st.experimental_rerun()

    if st.session_state["summary_text"]:
        if st.button("Start a new summary"):
            st.session_state["summary_text"] = ""
            st.session_state["summary_source"] = ""
            st.session_state["chat_messages"] = []

# Main layout: input first, then summary + chat take the full page
discharge_text = ""

if not st.session_state["summary_text"]:
    st.subheader("Discharge Summary Input")

    st.markdown("**Input method**")
    input_method = st.radio(
        "",
        options=["Upload file (PDF/DOCX/TXT)", "Paste text"],
        index=0,
        horizontal=True,
    )

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
    if generate_clicked:
        if not discharge_text.strip():
            st.error("Please provide some discharge text first.")
        else:
            with st.spinner("Generating summary…"):
                try:
                    summary = generate_summary(discharge_text.strip())
                    st.session_state["summary_text"] = summary
                    st.session_state["summary_source"] = discharge_text.strip()
                    st.session_state["chat_messages"] = []
                    st.success("Summary generated. Ask questions below.")
                except Exception as e:
                    st.error(f"Error while calling the language model: {e}")

if st.session_state["summary_text"]:
    st.subheader("Patient-Friendly Summary")
    st.markdown(st.session_state["summary_text"])

    st.divider()
    st.subheader("Chat About This Discharge Summary")

    st.markdown(
        """
        <style>
        .chat-fade-in { animation: fadeInUp 0.5s ease-out; }
        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        </style>
        <div class="chat-fade-in">
        """,
        unsafe_allow_html=True,
    )

    if st.button("Clear chat"):
        st.session_state["chat_messages"] = []

    for message in st.session_state["chat_messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_prompt = st.chat_input("Ask a question about the discharge summary")
    if user_prompt:
        st.session_state["chat_messages"].append(
            {"role": "user", "content": user_prompt}
        )
        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    reply = generate_chat_response(
                        st.session_state["summary_source"],
                        st.session_state["chat_messages"],
                    )
                    st.markdown(reply)
                    st.session_state["chat_messages"].append(
                        {"role": "assistant", "content": reply}
                    )
                except Exception as e:
                    st.error(f"Error while calling the language model: {e}")

    st.markdown("</div>", unsafe_allow_html=True)
