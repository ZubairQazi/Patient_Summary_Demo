import os
import streamlit as st
from openai import OpenAI

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

PASSCODE = st.secrets.get("APP_PASSCODE")  # stored in Streamlit secrets


def check_password():
    """Return True if the user entered the correct passcode."""

    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    def _submit():
        # Compare against the secret
        if st.session_state["passcode_input"] == PASSCODE:
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

        # Stop running the rest of the app until authenticated
        return False

    return True


if not check_password():
    st.stop()

SYSTEM_PROMPT = """
You are a nurse explaining hospital discharge instructions to a patient and their family.
Use simple language (6th–8th grade level). Keep medical facts accurate.
Never change medicine names or doses.
"""

st.title("Patient-Friendly Discharge Summary")

input_text = st.text_area("Paste the discharge information here:", height=300)

if st.button("Generate Summary"):
    if not input_text.strip():
        st.error("Please paste a discharge summary.")
    else:
        with st.spinner("Generating..."):
            resp = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": input_text},
                ]
            )
            st.subheader("Patient Summary")
            st.write(resp.choices[0].message.content)