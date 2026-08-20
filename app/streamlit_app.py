"""
Streamlit Dashboard for Myntra Discovery Engine.
Visualizes the weekly opportunity areas and allows PMs to add 'So What' notes.
"""

import os
import sys
import json
import streamlit as st
import pandas as pd
from datetime import datetime

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db.supabase_client import (
    get_latest_board,
    get_quotes_for_week,
    get_last_pipeline_run,
    upsert_opportunity_note
)
from app.ai_insights import generate_executive_synthesis, ask_the_engine

st.set_page_config(
    page_title="Myntra Discovery Engine",
    page_icon="🛍️",
    layout="wide"
)

# ---------------------------------------------------------
# UI Header & Styles
# ---------------------------------------------------------
st.markdown("""
<style>
    .myntra-header {
        color: #ff3f6c;
        font-family: 'Inter', sans-serif;
        font-weight: 800;
        letter-spacing: -0.5px;
    }
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        border-left: 4px solid #ff3f6c;
    }
    .opp-card {
        background-color: white;
        border: 1px solid #e9ecef;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 16px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .priority-badge {
        background-color: #ff3f6c;
        color: white;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.8em;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="myntra-header">🛍️ Myntra Discovery Engine</h1>', unsafe_allow_html=True)

# Fetch data
@st.cache_data(ttl=300) # Cache for 5 mins
def load_data():
    board = get_latest_board()
    quotes = get_quotes_for_week()
    run = get_last_pipeline_run()
    return pd.DataFrame(board), pd.DataFrame(quotes), run

df_board, df_quotes, last_run = load_data()

if df_board.empty:
    st.info("No data available yet. Please run the pipeline.")
    st.stop()

week_start = df_board["week_start"].iloc[0]

# Display run metadata
if last_run:
    st.caption(f"Data as of Week: **{week_start}** | Last Pipeline Run: {last_run.get('finished_at', 'In Progress')} ({last_run.get('status', 'N/A')})")

st.divider()

# ---------------------------------------------------------
# AI Executive Synthesis
# ---------------------------------------------------------
st.markdown("## 🧠 AI Executive Synthesis")
st.markdown("*Decomposing Wishlist → Purchase Conversion*")

@st.cache_data(ttl=3600) # Cache the synthesis for 1 hour to save API tokens
def get_cached_synthesis(week, _df_board, _df_quotes):
    return generate_executive_synthesis(_df_board, _df_quotes, week)

with st.spinner("Synthesizing this week's data..."):
    synthesis = get_cached_synthesis(week_start, df_board, df_quotes)
    st.info(synthesis)

st.divider()



# Map human-readable questions to fields
question_map = {
    "What prevents a purchase?": "purchase_blocker",
    "Why do users wishlist?": "wishlist_motive",
    "What uncertainties remain?": "post_selection_uncertainty",
    "What causes purchase postponement?": "purchase_postponement_reason",
    "How do users compare products?": "comparison_behavior",
    "What info do users seek elsewhere?": "external_info_sought",
    "Is wishlist a bookmark or a cart?": "wishlist_intent_type",
    "Unmet Needs": "unmet_need",
    "User Segments": "segment_signal",
    "Fit and Size Signals": "fit_size_signal",
    "Price Signals": "price_signal",
    "Quality Signals": "quality_signal"
}

df_filtered = df_board.copy()

# ---------------------------------------------------------
# Dashboard Body (Removed Opportunity Areas per request)
# ---------------------------------------------------------

# ---------------------------------------------------------
# Guarded AI Chat Interface
# ---------------------------------------------------------
st.divider()
st.header("💬 Ask the Discovery Engine")
st.caption("Ask specific questions about user behaviors, segments, or product outcomes.")

preset_questions = [
    "Why do users add fashion products to their wishlist?",
    "What prevents wishlisted products from eventually being purchased?",
    "What uncertainties remain after users have identified a product they like?",
    "What causes users to postpone a purchase?",
    "How do users compare multiple shortlisted products?",
    "What information do users seek outside Myntra/AJIO before purchasing?",
    "What role do fit, size, styling, price, reviews, occasion and social validation play?",
    "When do users use the wishlist as genuine purchase intent versus simply as a bookmarking mechanism?",
    "How do these behaviors differ across user segments?",
    "What unmet needs emerge consistently across user conversations?"
]

# Inject custom JS for animated placeholder
js_questions = [f'Search "{q}"' for q in preset_questions]
js_code = f"""
<script>
const placeholders = {json.dumps(js_questions)};
let i = 0;
setInterval(() => {{
    const input = window.parent.document.querySelector('.stChatInput textarea');
    if (input && window.parent.document.activeElement !== input) {{
        input.setAttribute('placeholder', placeholders[i]);
        i = (i + 1) % placeholders.length;
    }}
}}, 1000);
</script>
"""
import streamlit.components.v1 as components
components.html(js_code, height=0, width=0)

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Layout for suggested questions
if len(st.session_state.messages) == 0:
    st.markdown("### Suggested Questions")
    cols = st.columns(2)
    for idx, q in enumerate(preset_questions[:4]): # Show first 4
        with cols[idx % 2]:
            if st.button(q, use_container_width=True, key=f"btn_{idx}"):
                st.session_state.messages.append({"role": "user", "content": q})
                with st.spinner("Analyzing data..."):
                    response = ask_the_engine(q, df_board)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# React to user input
if prompt := st.chat_input("Ask a question..."):
    # Display user message in chat message container
    st.chat_message("user").markdown(prompt)
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Call AI
    with st.chat_message("assistant"):
        with st.spinner("Analyzing data..."):
            response = ask_the_engine(prompt, df_board)
            st.markdown(response)
    # Add assistant response to chat history
    st.session_state.messages.append({"role": "assistant", "content": response})
