"""
Streamlit Dashboard for Myntra Discovery Engine.
Visualizes the weekly opportunity areas and allows PMs to add 'So What' notes.
"""

import os
import sys
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

# ---------------------------------------------------------
# Sidebar Controls
# ---------------------------------------------------------
st.sidebar.header("Controls")

time_toggle = st.sidebar.radio(
    "Time Period",
    options=["This Week", "All Time (Cumulative)"],
    index=0
)

filter_question = st.sidebar.selectbox(
    "View by Question / Topic",
    options=[
        "All questions",
        "What prevents a purchase?",
        "Why do users wishlist?",
        "What uncertainties remain?",
        "What causes purchase postponement?",
        "How do users compare products?",
        "What info do users seek elsewhere?",
        "Is wishlist a bookmark or a cart?",
        "Unmet Needs",
        "User Segments",
        "Fit and Size Signals",
        "Price Signals",
        "Quality Signals"
    ]
)

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

# ---------------------------------------------------------
# Data Processing & Filtering
# ---------------------------------------------------------
df_filtered = df_board.copy()

# Filter by question
if filter_question != "All questions":
    target_field = question_map[filter_question]
    df_filtered = df_filtered[df_filtered["theme_field"] == target_field]

# Adjust for All Time vs This Week
if time_toggle == "All Time (Cumulative)":
    # Use cumulative count
    df_filtered["display_count"] = df_filtered["cumulative_count"]
    # Re-calculate score: cumulative_count * severity
    df_filtered["display_score"] = df_filtered["display_count"] * df_filtered["severity"]
    # Re-rank
    df_filtered = df_filtered.sort_values(by="display_score", ascending=False).reset_index(drop=True)
    df_filtered["display_rank"] = df_filtered.index + 1
else:
    df_filtered["display_count"] = df_filtered["frequency"]
    df_filtered["display_score"] = df_filtered["score"]
    df_filtered["display_rank"] = df_filtered["rank"]
    df_filtered = df_filtered.sort_values(by="display_rank", ascending=True).reset_index(drop=True)

# ---------------------------------------------------------
# Dashboard Body
# ---------------------------------------------------------

st.subheader(f"Opportunity Areas ({len(df_filtered)})")

if df_filtered.empty:
    st.info("No themes found for this filter.")

for _, row in df_filtered.iterrows():
    theme_key = row["theme_key"]
    theme_field = str(row.get("theme_field", "")).replace("_", " ").title()
    theme_value = str(row.get("theme_value", "")).replace("_", " ").title()
    human_theme = f"{theme_field}: {theme_value}"
    
    # Trend arrow
    if row["trend"] == "rising":
        trend_arrow = "↑"
        trend_color = "red"
    elif row["trend"] == "falling":
        trend_arrow = "↓"
        trend_color = "green"
    else:
        trend_arrow = "→"
        trend_color = "gray"
        
    with st.container():
        st.markdown(f"""
        <div class="opp-card">
            <div style="display: flex; justify-content: space-between; align-items: baseline;">
                <h3>#{int(row['display_rank'])} {human_theme} {'<span class="priority-badge">PRIORITY</span>' if row.get('priority') and time_toggle == 'This Week' else ''}</h3>
                <div style="text-align: right;">
                    <span style="font-size: 1.2em; font-weight: bold; color: {trend_color};">{trend_arrow}</span>
                    <span style="margin-left: 10px; font-weight: 500;">Score: {row['display_score']:.1f}</span>
                </div>
            </div>
            <div style="color: #6c757d; margin-bottom: 16px;">
                <strong>Mentions:</strong> {int(row['display_count'])} | 
                <strong>Severity:</strong> {row['severity']:.1f}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2 = st.columns([3, 2])
        
        with col1:
            st.markdown("**Representative Quotes**")
            # Fetch quotes for this theme
            theme_quotes = df_quotes[df_quotes["theme_key"] == theme_key]
            if not theme_quotes.empty:
                for idx, q_row in theme_quotes.head(3).iterrows():
                    source = q_row.get("source", "Unknown")
                    st.info(f"*{q_row['raw_text']}* — ({source})")
            else:
                st.write("No quotes available.")
                
        with col2:
            st.markdown("**'So What' Analysis**")
            # Editable note field
            note_key = f"note_{theme_key}"
            current_note = row.get("so_what", "")
            
            # Using a form to avoid rerun on every keystroke
            with st.form(key=f"form_{theme_key}"):
                new_note = st.text_area("Product Manager Notes:", value=current_note, key=note_key, height=150)
                submit_button = st.form_submit_button(label='Save Note')
                
                if submit_button:
                    try:
                        upsert_opportunity_note(theme_key, new_note)
                        st.success("Note saved!")
                        # Clear cache so it reloads on next interaction
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"Failed to save note: {e}")
        
        st.markdown("<br>", unsafe_allow_html=True)

# ---------------------------------------------------------
# Guarded AI Chat Interface
# ---------------------------------------------------------
st.divider()
st.header("💬 Ask the Discovery Engine")
st.caption("Ask specific questions about user behaviors, segments, or product outcomes.")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# React to user input
if prompt := st.chat_input("E.g., What is the biggest blocker for users buying fashion on Myntra?"):
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
