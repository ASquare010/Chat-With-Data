import base64, io
import pandas as pd
import streamlit as st
import time, uuid, json
from PIL import Image
from src.utils import *
from src.agent import InsightGenerator, ChatOrchestrator

st.set_page_config(
    layout="wide",
    page_title="Chat with Data",
    initial_sidebar_state="collapsed"
)

# ---------- Session State Initialization ---------
if "threads" not in st.session_state:
    st.session_state.threads = {}
if "current_thread_id" not in st.session_state:
    st.session_state.current_thread_id = None


def process_data(uploaded_file, use_saved_insights=True):
    insights_dict = None

    if uploaded_file is not None:
        csv_to_sqlite(csv_file=uploaded_file)
        csv_file_name = os.path.basename(uploaded_file.name)
        file_base = os.path.splitext(csv_file_name)[0]
        json_file_path = os.path.join("temp", f"{file_base}.json")
        
        if use_saved_insights and os.path.exists(json_file_path):
            with open(json_file_path, "r") as file:
                insights_dict = json.load(file)
        else:
            sample_data = run_sql_query("SELECT * FROM data LIMIT 5;")
            column_names = get_column_names()
            db_data = f"column_names: {column_names}, sample_data: {sample_data}"
            
            insights_result = InsightGenerator(db_data).invoke()
            insights_dict = insights_result.get('json_insights')
            
            if insights_dict:
                os.makedirs("temp", exist_ok=True)
                with open(json_file_path, "w") as file:
                    json.dump(insights_dict, file, indent=4)
                st.toast("New insights generated and saved!", icon="✅")
                    
        return insights_dict 
    return None

def display_summary(summary_raw):
    try:
        summary = json.loads(summary_raw) if isinstance(summary_raw, str) else summary_raw
    except Exception:
        summary = {}
    st.markdown("### Insight:")
    st.success(summary.get('insight', 'N/A'))
    st.markdown("### Direction:")
    st.info(summary.get('direction', 'N/A'))
    st.markdown("### Action:")
    st.error(summary.get('action', 'N/A'))

def display_relevant_columns(cols):
    if isinstance(cols, list):
        for col_dict in cols:
            if isinstance(col_dict, dict):
                for col_name, col_desc in col_dict.items():
                    st.markdown(f"- **{col_name}:** _{col_desc}_")

def display_sql_results(pairs, relation_columns):
    if not isinstance(pairs, list):
        return
    for i, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            continue
        st.markdown(f"**Query {i+1}:**")
        st.code(pair.get('sql_query', 'N/A'), language='sql')
        db_result = pair.get('db_result', [])
        if not db_result:
            continue
        try:
            if isinstance(db_result, list) and (not db_result or all(isinstance(row, (dict, list, tuple)) for row in db_result)):
                processed_result = []
                if db_result and isinstance(db_result[0], (list, tuple)):
                    col_names = []
                    if relation_columns and isinstance(relation_columns, list):
                        for c_dict in relation_columns:
                            if isinstance(c_dict, dict):
                                col_names.extend(list(c_dict.keys()))
                    if len(col_names) < len(db_result[0]):
                        col_names.extend([f"col_{j}" for j in range(len(col_names), len(db_result[0]))])
                    processed_result = [dict(zip(col_names, row)) for row in db_result]
                elif db_result and isinstance(db_result[0], dict):
                    processed_result = [
                        {k: (None if v is Ellipsis else v) for k, v in row.items()}
                        for row in db_result
                    ]
                if processed_result and isinstance(processed_result[0], dict):
                    df_result = pd.DataFrame(processed_result)
                    for col in df_result.select_dtypes(include=['object']).columns:
                        df_result[col] = df_result[col].apply(lambda x: str(x) if isinstance(x, bool) else x)
                    st.dataframe(df_result, hide_index=True, use_container_width=True)
                elif processed_result:
                    st.write(processed_result)
            else:
                st.code(json.dumps(db_result, indent=2), language='json')
        except Exception:
            try:
                st.code(json.dumps(db_result, indent=2), language='json')
            except Exception:
                st.code(str(db_result))

def display_insights_in_column(insights_json):
    for insight_key, insight_data in insights_json.items():
        with st.expander(f"{insight_key}", expanded=False):
            st.markdown(f"## Details:\n{insight_data.get('insight_details', 'N/A')}")
            tab1, tab2 = st.tabs(["Summary & Recommendations", "Technical Details"])

            with tab1:
                display_summary(insight_data.get('insight_summary', {}))
            with tab2:
                st.markdown("**Relevant Columns:**")
                display_relevant_columns(insight_data.get('relation_columns', []))
                st.markdown("---")
                st.markdown("**Analysis & Results:**")
                display_sql_results(insight_data.get('sql_results_pair', []), insight_data.get('relation_columns', []))
        
def display_chatbot(thread_data,chat_bot):
    MESSAGE_CONTAINER_HEIGHT = 650
    message_container = st.container(height=MESSAGE_CONTAINER_HEIGHT)
    with message_container:
        messages = thread_data.get("messages", [])
        if not messages:
            st.info("Start the conversation by typing below!")

        for message in messages:
            role = message.get("role")
            content = message.get("content")
            image_b64 = message.get("image")

            if not role or not content:
                st.warning("Skipping incomplete message.")
                continue

            with st.chat_message(role):
                st.markdown(content)
                if image_b64:
                    try:
                        image_data = base64.b64decode(image_b64)
                        image = Image.open(io.BytesIO(image_data))
                        st.image(image, caption="Chatbot Visualization")
                    except Exception as e:
                        st.error(f"⚠️ Could not display image")

    if prompt := st.chat_input("Ask about these insights..."):

        if "messages" not in thread_data:
            thread_data["messages"] = []
        thread_data["messages"].append({"role": "user", "content": prompt})

        try:
            with st.spinner("Thinking..."):
                message_text , image_base64, _ = chat_bot.invoke(prompt)

            thread_data["messages"].append({
                "role": "assistant",
                "content": message_text,
                "image": image_base64
            })

        except Exception as e:
            st.error(f"Error getting response: {e}")
            thread_data["messages"].append({
                "role": "assistant",
                "content": f"Sorry, I encountered an error: {e}"
            })
        st.rerun()

def init_state():
    st.header("Start a New Analysis Thread")
    st.write("Upload a CSV file to begin analyzing your data and generate insights.")

    uploaded_file = st.file_uploader("Choose a CSV file", type=["csv"], label_visibility="collapsed")
    if uploaded_file is not None:
        use_saved = st.checkbox("Use cached insights", value=True)
        
        if st.button(f"Process {uploaded_file.name}", type="primary"):
            with st.spinner("Processing data..."):
                insights_json = process_data(uploaded_file, use_saved_insights=use_saved)
                if insights_json:
                    sample_data = run_sql_query("SELECT * FROM data LIMIT 5;")
                    column_names = get_column_names()
                    metadata = f"column_names: {column_names}, sample_data: {sample_data}"
                    chat_bot = ChatOrchestrator(metadata, insights_json)
                    
                    new_thread_id = str(uuid.uuid4())
                    assistant_msg = f"✅ Data from '{uploaded_file.name}' processed. Insights are ready on the left. Ask me anything about them!"
                    st.session_state.threads[new_thread_id] = {
                        "title": f"{uploaded_file.name}",
                        "insights": insights_json,
                        "messages": [{"role": "assistant", "content": assistant_msg}],
                        "chat_bot": chat_bot
                    }
                    st.session_state.current_thread_id = new_thread_id
                    st.rerun()

def main_ui():
    with st.sidebar:
        st.title("💬 Data Chats")
        st.divider()
        if st.button("+ New Thread", use_container_width=True):
            st.session_state.current_thread_id = None
            st.rerun()
        thread_ids = list(st.session_state.threads.keys())
        thread_ids.reverse()
        if not thread_ids:
            st.caption("No threads yet. Start a new one!")
        else:
            for thread_id in thread_ids:
                thread_title = st.session_state.threads[thread_id].get("title", f"Thread {thread_id[:8]}...")
                button_type = "primary" if thread_id == st.session_state.current_thread_id else "secondary"
                if st.button(thread_title, key=f"thread_btn_{thread_id}", use_container_width=True, type=button_type):
                    st.session_state.current_thread_id = thread_id
                    st.rerun()

    if st.session_state.current_thread_id is None:
        init_state()
    else:
        st.header("💬 Data Chat")
        thread_id = st.session_state.current_thread_id
        if thread_id in st.session_state.threads:
            thread_data = st.session_state.threads[thread_id]
            chat_bot = thread_data.get("chat_bot") 

            tab1, tab2 = st.tabs(["💡 Generated Insights", "💬 Chat about Analysis"])

            with tab1:
                    display_insights_in_column(thread_data.get("insights", {}))

            with tab2:
                    display_chatbot(thread_data,chat_bot)
        else:
            st.error("Error: Selected thread not found. Please start a new thread.")
            st.session_state.current_thread_id = None
            time.sleep(2)
            st.rerun()


if __name__ == "__main__":
    main_ui()