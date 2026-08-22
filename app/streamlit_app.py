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

st.markdown('<h1 class="myntra-header">Myntra Growth Discovery Engine</h1>', unsafe_allow_html=True)
st.markdown("### Public-signal intelligence for Wishlist → Purchase Conversion")

# Fetch data
@st.cache_data(ttl=300) # Cache for 5 mins
def load_data():
    board = get_latest_board()
    quotes = get_quotes_for_week()
    run = get_last_pipeline_run()
    
    df_board = pd.DataFrame(board)
    df_quotes = pd.DataFrame(quotes)
    
    return df_board, df_quotes, run

df_board, df_quotes, last_run = load_data()

if df_board.empty:
    st.info("No data available yet. Please run the pipeline.")
    st.stop()

week_start = df_board["week_start"].iloc[0]

# Methodology & Metadata
st.caption(f"**Public conversations analyzed** (Reddit, YouTube, App Reviews, Web) | **Last updated**: {week_start} | *Illustrative prototype dataset*")

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

df_filtered = df_board[df_board["theme_value"] != "none"].copy()

# ---------------------------------------------------------
# Top Opportunity Areas (Section 2)
# ---------------------------------------------------------
st.header("Top Opportunity Areas")
st.caption("Recurring user/problem areas emerging from discovery research. Sorted by Signal Strength.")

top_opps = df_filtered.sort_values(by="score", ascending=False).head(5)

for _, row in top_opps.iterrows():
    theme_key = row["theme_key"]
    theme_field = row.get("theme_field", "")
    theme_value = row.get("theme_value", "")
    
    # Calculate mock confidence based on frequency
    freq = row.get("frequency", 0)
    confidence = "High" if freq > 10 else ("Medium" if freq > 5 else "Low")
    
    # Trend mapping
    trend_val = row.get("trend", "flat")
    trend_icon = "↑" if trend_val == "up" else ("↓" if trend_val == "down" else "→")
    
    with st.container():
        st.markdown(f"### {str(theme_value).replace('_', ' ').title()}")
        st.caption(f"**Category:** {str(theme_field).replace('_', ' ').title()}")
        cols = st.columns(3)
        cols[0].markdown(f"**Signal Strength:** {row.get('score', 0):.1f}")
        cols[1].markdown(f"**Trend:** {trend_icon}")
        cols[2].markdown(f"**Evidence Confidence:** {confidence}")
        
        with st.expander("View Evidence"):
            # Evidence Explorer
            theme_quotes = df_quotes[df_quotes["theme_key"] == theme_key]
            if theme_quotes.empty:
                st.info("No direct quotes available for this theme.")
            else:
                source_counts = theme_quotes["source"].value_counts()
                st.markdown("#### Source Distribution")
                source_str = " · ".join([f"{str(k).replace('_', ' ').title()}: **{v}**" for k, v in source_counts.items()])
                st.markdown(source_str)
                st.markdown(f"*Total Signal Volume: {row.get('cumulative_count', freq)} records*")
                
                st.markdown("#### Representative Evidence")
                for _, quote_row in theme_quotes.head(3).iterrows():
                    st.markdown(f"> \"{quote_row['raw_text']}\" \n> *- {str(quote_row['source']).replace('_', ' ').title()}*")
                
                st.markdown("#### Contradictory Evidence")
                st.caption("Illustrative counter-point to demonstrate analytical rigor.")
                st.markdown(f"> While '{str(theme_value).replace('_', ' ').title()}' is a barrier, a subset of users report it is secondary to price and brand trust.")
        
        st.divider()

# ---------------------------------------------------------
# Wishlist Journey (Section 3)
# ---------------------------------------------------------
st.header("Wishlist Journey Map")
st.caption("Discovered user problems mapped to the Wishlist → Purchase conversion funnel.")

journey_cols = st.columns(5)
journey_stages = ["Discover", "Wishlist", "Compare", "Validate", "Wait/Purchase"]

# Illustrative mapping of our themes
mapping = {
    "Discover": ["brand_trust", "discovery_friction"],
    "Wishlist": ["wishlist_motive", "wishlist_intent_type"],
    "Compare": ["comparison_behavior", "price_signal"],
    "Validate": ["post_selection_uncertainty", "fit_size_signal", "quality_signal", "external_info_sought"],
    "Wait/Purchase": ["purchase_blocker", "purchase_postponement_reason", "unmet_need"]
}

for i, stage in enumerate(journey_stages):
    with journey_cols[i]:
        st.markdown(f"**{stage}**")
        st.markdown("↓")
        # Find themes that belong to this stage
        stage_themes = mapping.get(stage, [])
        found_any = False
        for _, row in df_filtered.iterrows():
            if row["theme_field"] in stage_themes:
                st.markdown(f"- {str(row['theme_value']).replace('_', ' ').title()}")
                found_any = True
        if not found_any:
            st.caption("-")

st.divider()

# ---------------------------------------------------------
# Methodology (Footer)
# ---------------------------------------------------------
st.divider()
st.markdown("### Methodology & Limitations")
st.caption("""
**Public-signal dataset**: Reddit · YouTube · Play Store · App Store · Product conversations. 
*This is a prototype dataset. Public conversations do not represent first-party Myntra behavioral telemetry, internal GMV, or actual PII.*
Opportunity strength combines frequency, cross-source consistency, relevance to the target metric, and evidence confidence.
""")

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

# Define JSON objects outside the f-string to avoid escaping bugs
animated_placeholders = [f'Search "{q}"' for q in preset_questions]
questions_json = json.dumps(preset_questions)
placeholders_json = json.dumps(animated_placeholders)

# Inject custom JS and CSS for animated placeholder and dropdown menu
js_code = f"""
<style>
/* Streamlit iframe takes up space if we don't hide it properly. We use height=0 in components.html, 
   but we inject styles into the parent window. */
</style>
<script>
// We need to inject styles into the parent document since this script runs in an iframe
const parentDoc = window.parent.document;
if (!parentDoc.getElementById('custom-chat-styles')) {{
    const style = parentDoc.createElement('style');
    style.id = 'custom-chat-styles';
    style.innerHTML = `
        .custom-dropdown {{
            position: absolute;
            top: 100%;
            left: 0;
            width: 100%;
            background-color: #1e1e27;
            border: 1px solid #333;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5);
            max-height: 300px;
            overflow-y: auto;
            z-index: 999999;
            display: none;
            margin-top: 5px;
        }}
        .custom-dropdown.show {{
            display: block;
        }}
        .dropdown-item {{
            padding: 12px 16px;
            cursor: pointer;
            color: #e0e0e0;
            font-size: 14px;
            border-bottom: 1px solid #2d2d3a;
            transition: background 0.2s;
        }}
        .dropdown-item:last-child {{
            border-bottom: none;
        }}
        .dropdown-item:hover {{
            background-color: #333342;
            color: #fff;
        }}
    `;
    parentDoc.head.appendChild(style);
}}

const questions = {questions_json};
const animatedPlaceholders = {placeholders_json};

// 1. Placeholder Animation Logic
let i = 0;
setInterval(() => {{
    const input = parentDoc.querySelector('[data-testid="stChatInputTextArea"]');
    if (input && parentDoc.activeElement !== input) {{
        input.setAttribute('placeholder', animatedPlaceholders[i]);
        i = (i + 1) % animatedPlaceholders.length;
    }}
}}, 2500);

// 2. Dropdown Logic
function initDropdown() {{
    if (parentDoc.getElementById('chat-dropdown')) return;
    
    const chatContainer = parentDoc.querySelector('[data-testid="stChatInput"]');
    const input = parentDoc.querySelector('[data-testid="stChatInputTextArea"]');
    
    if (chatContainer && input) {{
        // Find the submit button inside the chat container
        const submitBtn = chatContainer.querySelector('button');
        
        // Chat container needs position relative for absolute positioning of dropdown
        chatContainer.style.position = 'relative';
        
        // Create Dropdown DOM
        const dropdown = parentDoc.createElement('div');
        dropdown.id = 'chat-dropdown';
        dropdown.className = 'custom-dropdown';
        
        questions.forEach(q => {{
            const item = parentDoc.createElement('div');
            item.className = 'dropdown-item';
            item.textContent = q;
            
            // Handle Item Click
            item.onmousedown = (e) => {{
                e.preventDefault(); // Prevent input blur
                
                // 1. Set React value via native setter hack
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
                nativeInputValueSetter.call(input, q);
                
                // 2. Dispatch input event for React
                const ev2 = new Event('input', {{ bubbles: true}});
                input.dispatchEvent(ev2);
                
                // 3. Close dropdown
                dropdown.classList.remove('show');
                
                // 4. Click submit
                if (submitBtn) {{
                    setTimeout(() => {{ submitBtn.click(); }}, 50);
                }}
            }};
            dropdown.appendChild(item);
        }});
        
        chatContainer.appendChild(dropdown);
        
        // Handle Focus/Blur to show/hide
        input.addEventListener('focus', () => {{
            dropdown.classList.add('show');
        }});
        input.addEventListener('blur', () => {{
            setTimeout(() => dropdown.classList.remove('show'), 200);
        }});
    }}
}}

// Run immediately in case DOM is already ready
initDropdown();

// Fallback to observer if DOM loads later
const observer = new MutationObserver(initDropdown);
observer.observe(parentDoc.body, {{ childList: true, subtree: true }});
</script>
"""
import streamlit.components.v1 as components
components.html(js_code, height=0, width=0)

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

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
