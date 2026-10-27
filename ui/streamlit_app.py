"""The Streamlit entry point: two pages, asking questions and the measured results.

Start the API first (`uv run anlagen-copilot-api`), then the pages with
`uv run --extra ui streamlit run ui/streamlit_app.py`. The results page reads only the
run records and needs neither the API nor the database.
"""

import streamlit as st

st.set_page_config(page_title="Anlagen-Copilot", page_icon="⚙️", layout="wide")
st.navigation(
    [
        st.Page("fragen.py", title="Fragen", icon="💬", default=True),
        st.Page("ergebnisse.py", title="Ergebnisse", icon="📊"),
    ]
).run()
