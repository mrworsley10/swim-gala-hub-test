import streamlit as st
import streamlit.components.v1 as components
import pdfplumber
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta, time
import urllib3
import random
from supabase import create_client, Client

# --- DEFINE PAGE NAMES GLOBALLY ---
VIEW_COACH = "⏱ Coach Race Info"
VIEW_WALL = "📋 Swimmer Wall Planner"
VIEW_TM = "🚩 TM Marshalling Info"

st.set_page_config(page_title="Swim Gala Hub", layout="wide")

# --- WAKE LOCK: KEEP MOBILE SCREEN ON ---
components.html("""
<script>
async function keepAwake() {
    if ('wakeLock' in navigator) {
        try {
            const wakeLock = await navigator.wakeLock.request('screen');
            console.log('Wake Lock active!');
            document.addEventListener('visibilitychange', async () => {
                if (document.visibilityState === 'visible') {
                    await navigator.wakeLock.request('screen');
                }
            });
        } catch (err) {
            console.error(`${err.name}, ${err.message}`);
        }
    }
}
keepAwake();
</script>
""", height=0, width=0)

# --- SUPABASE CLOUD CONNECTION ---
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_supabase()
except Exception as e:
    st.error(f"Database Connection Failed: {e}")

# --- MODERN CUSTOM CSS ---
st.markdown("""
<style>
    div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child { display: none !important; }
    div[role="radiogroup"] label[data-baseweb="radio"] { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px 15px; margin-bottom: 8px; cursor: pointer; transition: all 0.2s ease; width: 100%; }
    div[role="radiogroup"] label[data-baseweb="radio"]:hover { background-color: #334155; border-color: #facc15; }
    div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked) { background-color: #facc15 !important; border-color: #facc15 !important; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); }
    div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked) p { color: #0b0b0b !important; font-weight: 800 !important; }
    table { white-space: nowrap !important; width: 100%; font-size: 0.9em; }
    th { font-size: 0.85em; text-transform: uppercase; color: #94a3b8; }
    .app-header { background-color: #0b0b0b; border-radius: 12px; padding: 20px 25px; display: grid; grid-template-columns: 1fr 1fr; align-items: center; margin-top: 10px; margin-bottom: 20px; border-bottom: 4px solid #facc15; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    .header-left { text-align: left; }
    .header-right { text-align: right; }
    .view-title { color: #facc15 !important; font-weight: 800; font-size: clamp(1rem, 2.5vw, 1.4rem); text-transform: uppercase; letter-spacing: 1px; margin: 0; line-height: 1.2; }
    .meet-name { color: #ffffff !important; font-weight: 700; font-size: clamp(0.9rem, 2vw, 1.2rem); margin: 0; line-height: 1.2; }
    .sync-status { font-size: clamp(0.7rem, 1.5vw, 0.85rem); margin-top: 4px; font-weight: 600; }
    .sync-live { color: #4ade80 !important; }
    .sync-offline { color: #94a3b8 !important; }
    .kpi-container { display: flex; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }
    .kpi-card { flex: 1; min-width: 140px; background-color: var(--secondary-background-color); border-top: 4px solid #facc15; border-radius: 8px; padding: 15px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .kpi-val { font-size: 2.2em; font-weight: 800; color: var(--text-color) !important; line-height: 1; margin-bottom: 5px; }
    .kpi-val.green { color: #4ade80 !important; }
    .kpi-val.red { color: #ef4444 !important; }
    .kpi-val.orange { color: #f97316 !important; }
    .kpi-label { font-size: 0.75em; color: gray !important; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

if "gala_df" not in st.session_state: st.session_state["gala_df"] = pd.DataFrame()
if "target_df" not in st.session_state: st.session_state["target_df"] = pd.DataFrame()
if "meet_name" not in st.session_state: st.session_state["meet_name"] = "Swim Gala Live"
if "redraw_counter" not in st.session_state: st.session_state["redraw_counter"] = 0
if "room_pin" not in st.session_state: st.session_state["room_pin"] = None
if "last_url" not in st.session_state: st.session_state["last_url"] = ""

st.sidebar.title("Navigation")
page_selection = st.sidebar.radio("Select View", [VIEW_COACH, VIEW_WALL, VIEW_TM])

icon_title = "⏱ COACH" if page_selection == VIEW_COACH else "📋 PLANNER" if page_selection == VIEW_WALL else "🚩 TRACKER"
sync_class = "sync-live" if st.session_state["room_pin"] else "sync-offline"
sync_text = f"🟢 Room: {st.session_state['room_pin']}" if st.session_state["room_pin"] else "⚪ Offline"

st.markdown(f"""
<div class="app-header">
    <div class="header-left"><div class="view-title">{icon_title}</div></div>
    <div class="header-right">
        <div class="meet-name">{st.session_state['meet_name']}</div>
        <div class="sync-status {sync_class}">{sync_text}</div>
    </div>
</div>
""", unsafe_allow_html=True)

def safe_int(val, default=0):
    try: return int(float(val))
    except: return default

def safe_str(val, default=""):
    if pd.isna(val): return default
    return str(val).strip()

def safe_bool(val):
    if pd.isna(val): return False
    return bool(val)

def extract_gender(event_str):
    e_lower = str(event_str).lower()
    return 'F' if 'female' in e_lower or 'girl' in e_lower or 'women' in e_lower else 'M'

def extract_standard_event(event_str):
    m = re.search(r'(\d+m\s+[A-Za-z]+(?:\s+IM)?)', str(event_str), re.IGNORECASE)
    if m: return m.group(1).title().replace('Breaststroke', 'Breast').replace('Breaststrok', 'Breast').replace('Freestyle', 'Free').replace('Backstroke', 'Back').replace('Butterfly', 'Fly').replace('Ind. Medley', 'IM').replace('Ind Medley', 'IM').replace('M ', 'm ').replace(' Im', ' IM').strip()
    return ""

def get_unique_pin():
    try:
        res = supabase.table("live_gala_data").select("room_pin").execute()
        existing_pins = [row["room_pin"] for row in res.data] if res.data else []
    except:
        existing_pins = []
        
    while True:
        new_pin = str(random.randint(10000, 99999))
        if new_pin not in existing_pins:
            return new_pin

def create_room(df, gala_url=""):
    pin = get_unique_pin()
    records = []
    for _, row in df.iterrows():
        records.append({
            "room_pin": pin,
            "gala_url": gala_url,
            "session": safe_int(row.get("Session"), 1),
            "swimmer": safe_str(row.get("Swimmer")),
            "age": safe_str(row.get("Age")),
            "event": safe_str(row.get("Event")),
            "heat": safe_str(row.get("Heat")),
            "lane": safe_int(row.get("Lane"), 0),
            "entry_time": safe_str(row.get("Entry Time")),
            "achieved_time": safe_str(row.get("Achieved Time")),
            "coach_notes": safe_str(row.get("Coach Notes")),
            "checked_in": safe_bool(row.get("Checked In")),
            "checked_out": safe_bool(row.get("Checked Out")),
            "seen_coach": safe_bool(row.get("Seen Coach")),
            "in_marshalling": safe_bool(row.get("In Marshalling")),
            "official_placement": ""
        })
    try:
        batch_size = 100
        for i in range(0, len(records), batch_size):
            supabase.table("live_gala_data").insert(records[i:i+batch_size]).execute()
        return pin, None
    except Exception as e:
        return None, str(e)

def fetch_room(pin):
    try:
        response = supabase.table("live_gala_data").select("*").eq("room_pin", str(pin)).execute()
        data = response.data
        if not data: return pd.DataFrame()
        return pd.DataFrame(data).rename(columns={"session": "Session", "swimmer": "Swimmer", "age": "Age", "event": "Event", "heat": "Heat", "lane": "Lane", "entry_time": "Entry Time", "achieved_time": "Achieved Time", "coach_notes": "Coach Notes", "checked_in": "Checked In", "checked_out": "Checked Out", "seen_coach": "Seen Coach", "in_marshalling": "In Marshalling", "official_placement": "Placement"})
    except Exception as e:
        st.error(f"Failed to pull from cloud: {e}")
        return pd.DataFrame()

def fetch_room_targets(pin):
    try:
        res = supabase.table("target_times").select("*").eq("room_pin", str(pin)).execute()
        if res.data: return pd.DataFrame(res.data).rename(columns={"gender": "Gender", "age": "Age", "event": "Event", "county_time": "County_Time", "regional_time": "Regional_Time"})
    except: pass
    return pd.DataFrame()

def safe_update_db(row_id, field, value):
    if st.session_state.get("room_pin"):
        try: supabase.table("live_gala_data").update({field: value}).eq("id", int(row_id)).execute()
        except: pass

st.sidebar.divider()
st.sidebar.header("☁️ Live Cloud Sync")

if st.session_state.get("room_pin"):
    st.sidebar.success(f"🟢 Connected to Room: **{st.session_state['room_pin']}**")
    if st.sidebar.button("🔄 Refresh Live Data"):
        with st.spinner("Syncing latest data..."):
            st.session_state["gala_df"] = fetch_room(st.session_state["room_pin"])
            st.session_state["target_df"] = fetch_room_targets(st.session_state["room_pin"])
        st.rerun()
    if st.sidebar.button("🚪 Disconnect"):
        st.session_state["room_pin"] = None
        st.session_state["gala_df"] = pd.DataFrame()
        st.session_state["target_df"] = pd.DataFrame()
        st.rerun()
        
    st.sidebar.markdown("---")
    with st.sidebar.expander("🎯 Room Target Times", expanded=False):
        if not st.session_state["target_df"].empty: st.success(f"{len(st.session_state['target_df'])} Targets active.")
        else: st.info("No targets loaded.")
        target_file = st.file_uploader("Upload Targets (CSV)", type=["csv"])
        if target_file and st.button("Link Targets"):
            with st.spinner("Uploading..."):
                try:
                    upload_df = pd.read_csv(target_file)
                    records = [{"room_pin": st.session_state["room_pin"], "gender": safe_str(r.get("Gender")), "age": safe_int(r.get("Age"), -1), "event": safe_str(r.get("Event")), "county_time": safe_str(r.get("County_Time")), "regional_time": safe_str(r.get("Regional_Time"))} for _, r in upload_df.iterrows()]
                    supabase.table("target_times").delete().eq("room_pin", st.session_state["room_pin"]).execute()
                    for i in range(0, len(records), 100): supabase.table("target_times").insert(records[i:i+100]).execute()
                    st.session_state["target_df"] = fetch_room_targets(st.session_state["room_pin"])
                    st.rerun()
                except Exception as e: st.error(f"Upload failed: {e}")
else:
    st.sidebar.info("Sync across devices by creating a new room or rejoining an existing one.")
    
    if not st.session_state["gala_df"].empty and "id" not in st.session_state["gala_df"].columns:
        if st.sidebar.button("🎲 Generate New PIN & Upload Gala"):
            with st.spinner("Securing unique room & uploading data..."):
                original_df = st.session_state["gala_df"].copy()
                pin, err = create_room(st.session_state["gala_df"], st.session_state.get("last_url", ""))
                if pin:
                    new_df = fetch_room(pin)
                    if not new_df.empty:
                        st.session_state["room_pin"] = pin
                        st.session_state["gala_df"] = new_df
                        st.session_state["target_df"] = pd.DataFrame()
                        st.rerun()
                    else:
                        st.sidebar.error("Upload succeeded, but could not read data back.")
                        st.session_state["gala_df"] = original_df 
                else:
                    st.sidebar.error(f"Upload Failed: {err}")
                    st.session_state["gala_df"] = original_df
                    
    st.sidebar.markdown("---")
    join_pin = st.sidebar.text_input("Enter 5-Digit Room PIN to Rejoin:")
    if st.sidebar.button("Join Room") and join_pin:
        with st.spinner("Joining..."):
            new_df = fetch_room(join_pin)
            if not new_df.empty:
                st.session_state["gala_df"] = new_df
                st.session_state["room_pin"] = join_pin
                st.session_state["target_df"] = fetch_room_targets(join_pin)
                st.rerun()
            else: st.sidebar.error("Invalid PIN.")

st.sidebar.divider()
with st.sidebar.expander("🔐 Owner Tools"):
    admin_pin = st.text_input("Enter Owner PIN", type="password")
    if admin_pin == st.secrets.get("ADMIN_PIN", "9999"):
        st.success("Owner Access Granted")
        if st.button("🚨 Wipe All Cloud Rooms"):
            with st.spinner("Clearing database..."):
                try:
                    supabase.table("live_gala_data").delete().gt("id", 0).execute()
                    supabase.table("target_times").delete().gt("id", 0).execute()
                    st.session_state["room_pin"] = None
                    st.session_state["gala_df"] = pd.DataFrame()
                    st.session_state["target_df"] = pd.DataFrame()
                    st.rerun()
                except Exception as e: st.error(f"Failed to clear database: {e}")
    elif admin_pin: st.error("Incorrect PIN")

st.sidebar.divider()
st.sidebar.header("⚙ Gala Settings")
session_start_map = {}
pace_factor = st.sidebar.slider("Heat Timing Speed Factor", 0.8, 1.3, 1.0, 0.05)
st.sidebar.header("Load Data Source")
club_filter = st.sidebar.text_input("Club Keyword", placeholder="e.g. Warrington")
input_method = st.sidebar.radio("Input Method", ["Web Link (URL)", "Upload PDF", "Paste Text"])

# --- ROBUST FETCH FUNCTION ---
def fetch_url_content(url):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9,en-US;q=0.8'
    }
    response = requests.get(url, headers=headers, timeout=20, verify=False)
    response.raise_for_status()
    return response

def extract_meet_name_from_soup(soup):
    if soup.title and soup.title.get_text(strip=True):
        title_text = soup.title.get_text(strip=True)
        if title_text and "sportsystems" not in title_text.lower() and len(title_text) > 3: return title_text
    return None

def is_valid_swimmer_name(name):
    if not name or len(name) < 2: return False
    if not re.search(r'[a-zA-Z]', name): return False
    blocked = {'name', 'swimmer', 'aad', 'lane', 'comp.no', 'comp no', 'comp', 'club', 'event', 'heat', 'entry', 'time', 'place', 'pos'}
    if name.lower().strip() in blocked: return False
    return True

def estimate_heat_duration_seconds(event_str):
    event_lower = str(event_str).lower()
    if '50m' in event_lower: return 90
    elif '100m' in event_lower: return 150
    elif '200m' in event_lower: return 270
    elif '400m' in event_lower: return 480
    elif '800m' in event_lower: return 840
    elif '1500m' in event_lower: return 1320
    return 180

def get_event_num(event_str):
    m = re.search(r'Event\s+(\d+)', str(event_str), re.IGNORECASE)
    return int(m.group(1)) if m else 9999

def infer_session_number(event_str, current_session=1):
    e_num = get_event_num(event_str)
    if e_num != 9999 and e_num >= 100: return e_num // 100
    return current_session

def parse_html_soup(soup, club_keyword):
    entries = []
    current_event, current_heat, current_session = None, "1", 1
    target_keyword = club_keyword.strip().lower() if club_keyword else ""
    for elem in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div', 'tr']):
        text = elem.get_text(strip=True)
        if not text: continue
        session_match = re.search(r'Session\s+(\d+)', text, re.IGNORECASE)
        if session_match: current_session = int(session_match.group(1))
        event_match = re.search(r'(Event\s+\d+.*?)(?=\s+Heat|\n|$)', text, re.IGNORECASE)
        if event_match and elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div']: current_event = event_match.group(1).strip()
        heat_match = re.search(r'Heat(?:\s+Number\s*-\s*|\s+)(\d+)', text, re.IGNORECASE)
        if heat_match and elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div', 'tr']: current_heat = heat_match.group(1)
        
        if elem.name == 'tr' and current_event is not None:
            tds = elem.find_all(['td', 'th'])
            cells = [td.get_text(strip=True) for td in tds]
            row_text = " ".join(cells)
            
            if not target_keyword or target_keyword in row_text.lower():
                if not cells: continue
                lane_str = cells[0].strip()
                if not lane_str.isdigit(): continue
                entry_time = "N/A"
                for i in range(len(cells)-1, 0, -1):
                    val = cells[i].strip()
                    if not val: continue
                    if re.match(r'^[\d\:\.]+$', val) or val.upper() in ["NT", "S/T", "NONE"]:
                        entry_time = val
                        break
                    if target_keyword and target_keyword.lower() in val.lower(): break
                name, age = "", ""
                for i in range(1, len(cells)):
                    val = cells[i].strip()
                    if not val: continue
                    if not name and is_valid_swimmer_name(val):
                        if target_keyword and target_keyword.lower() in val.lower(): continue
                        name = val.title()
                    elif name and not age and val.isdigit() and 7 <= int(val) <= 99: age = val
                if name and lane_str.isdigit():
                    entries.append({"Session": infer_session_number(current_event, current_session), "Swimmer": name, "Age": age, "Event": current_event, "Heat": int(current_heat) if current_heat.isdigit() else current_heat, "Lane": int(lane_str), "Entry Time": entry_time, "Achieved Time": "", "Coach Notes": "", "Checked In": False, "Checked Out": False, "Seen Coach": False, "In Marshalling": False})
    return entries

def parse_text_lines(lines, club_keyword):
    entries = []
    current_event, current_heat, current_session = None, "1", 1
    target_keyword = club_keyword.strip().lower() if club_keyword else ""
    for line in lines:
        line_str = line.strip()
        if not line_str: continue
        session_match = re.search(r'Session\s+(\d+)', line_str, re.IGNORECASE)
        if session_match: current_session = int(session_match.group(1))
        event_match = re.search(r'(Event\s+\d+.*?)(?=\s+Heat|\n|$)', line_str, re.IGNORECASE)
        if event_match: current_event = event_match.group(1).strip()
        heat_match = re.search(r'Heat(?:\s+Number\s*-\s*|\s+)(\d+)', line_str, re.IGNORECASE)
        if heat_match: current_heat = heat_match.group(1)
        if current_event is not None and (not target_keyword or target_keyword in line_str.lower()):
            m = re.search(r'^\s*(\d+)\s+(?:(\d+)\s+)?([A-Za-z\s\-\'\.]+?)\s+(\d{1,2})\s+.*?(?:' + (re.escape(club_keyword) if target_keyword else r'[A-Za-z]+') + r')\s*([\d\:\.]+|S/T|NT)?', line_str, re.IGNORECASE)
            if m:
                lane, name, age, entry_time = m.group(1), m.group(3).strip(), m.group(4), m.group(5) if m.group(5) else "N/A"
                if lane.isdigit() and is_valid_swimmer_name(name):
                    entries.append({"Session": infer_session_number(current_event, current_session), "Swimmer": name.title(), "Age": age, "Event": current_event, "Heat": int(current_heat) if current_heat.isdigit() else current_heat, "Lane": int(lane), "Entry Time": entry_time, "Achieved Time": "", "Coach Notes": "", "Checked In": False, "Checked Out": False, "Seen Coach": False, "In Marshalling": False})
    return entries

def time_to_seconds(t_str):
    if not t_str or str(t_str).strip().upper() in ["N/A", "S/T", "NT", "", "-", "—", "NONE", "DQ", "DNC", "WD", "WITHDRAWN"]: return None
    t_str = re.sub(r'[^\d:\.]', '', str(t_str).strip())
    if not t_str: return None
    try:
        if t_str.isdigit():
            if len(t_str) >= 5: return int(t_str[:-4]) * 60 + int(t_str[-4:-2]) + (int(t_str[-2:]) / 100.0)
            elif len(t_str) >= 3: return int(t_str[:-2]) + (int(t_str[-2:]) / 100.0)
            else: return float(t_str)
        parts = re.split(r'[:\.]', t_str)
        if len(parts) == 3: return float(parts[0]) * 60 + float(parts[1]) + float(parts[2].ljust(2,'0')[:2]) / 100.0
        elif len(parts) == 2:
            ms_val = parts[1].ljust(2,'0')[:2]
            if ":" in t_str or len(parts[0]) < 3: return float(parts[0]) * 60 + float(parts[1]) if ":" in t_str else float(parts[0]) + float(ms_val) / 100.0
            else: return int(parts[0][:-2]) * 60 + int(parts[0][-2:]) + float(ms_val) / 100.0
        elif len(parts) == 1: return float(parts[0])
    except Exception: return None
    return None

def seconds_to_time(sec):
    if sec is None or sec < 0: return "N/A"
    return f"{int(sec // 60)}:{sec % 60:05.2f}" if sec >= 60 else f"{sec % 60:05.2f}"

def format_time_input(t_str):
    if not t_str or str(t_str).strip().lower() in ["", "none", "nan"]: return ""
    sec = time_to_seconds(t_str)
    return seconds_to_time(sec) if sec is not None else str(t_str)

def calculate_variance(achieved_sec, target_sec):
    if achieved_sec is None or target_sec is None: return "N/A"
    diff = achieved_sec - target_sec
    if diff < 0: return f"✅ -{seconds_to_time(abs(diff))}" 
    elif diff > 0: return f"🔺 +{seconds_to_time(abs(diff))}" 
    else: return f"⏸️ 0.00"

def compute_gala_schedule_times(df_input, session_starts, pace):
    if df_input.empty: return df_input
    calc_df = df_input.copy()
    calc_df["Coach Time"], calc_df["Marshalling Time"], calc_df["Est. Race Time"] = "", "", ""
    for sess in sorted(calc_df["Session"].unique()):
        start_t = session_starts.get(sess, time(9, 0) if sess % 2 != 0 else time(14, 0))
        current_dt = datetime.combine(datetime.today(), start_t)
        sess_mask = calc_df["Session"] == sess
        for event in sorted(calc_df[sess_mask]["Event"].unique(), key=get_event_num):
            event_mask = sess_mask & (calc_df["Event"] == event)
            event_rows = calc_df[event_mask].sort_values(by=["_sort_heat", "_sort_lane"])
            max_heat = int(event_rows["_sort_heat"].max()) if not event_rows.empty else 1
            heat_dur = estimate_heat_duration_seconds(event) * pace
            coach_time = (current_dt - timedelta(minutes=20)).strftime("%H:%M")
            for idx, row in event_rows.iterrows():
                heat_offset = (int(row["_sort_heat"]) - 1) * heat_dur if pd.notna(row["_sort_heat"]) else 0
                race_dt = current_dt + timedelta(seconds=heat_offset)
                calc_df.loc[idx, "Coach Time"] = coach_time
                calc_df.loc[idx, "Marshalling Time"] = (race_dt - timedelta(minutes=10)).strftime("%H:%M")
                calc_df.loc[idx, "Est. Race Time"] = race_dt.strftime("%H:%M")
            current_dt += timedelta(seconds=heat_dur * max_heat)
    return calc_df

def get_target_analysis(row, target_df, has_targets):
    ach_sec, ent_sec = time_to_seconds(row.get('Achieved Time')), time_to_seconds(row.get('Entry Time'))
    c_sec, r_sec = None, None
    if has_targets:
        match = target_df[(target_df['Gender'] == extract_gender(row.get('Event', ''))) & (target_df['Age'] == safe_int(row.get('Age'), -1)) & (target_df['Event'].str.lower() == extract_standard_event(row.get('Event', '')).lower())]
        if not match.empty:
            c_sec = time_to_seconds(match.iloc[0].get('County_Time', ""))
            r_sec = time_to_seconds(match.iloc[0].get('Regional_Time', ""))
    if ach_sec is not None:
        res = []
        v = calculate_variance(ach_sec, ent_sec)
        if v and v != "N/A": res.append(f"PB: {v}")
        if has_targets:
            v_c, v_r = calculate_variance(ach_sec, c_sec), calculate_variance(ach_sec, r_sec)
            if v_c and v_c != "N/A": res.append(f"C: {v_c}")
            if v_r and v_r != "N/A": res.append(f"R: {v_r}")
        return " | ".join(res) if res else "Logged"
    else:
        if has_targets:
            res = []
            v_c, v_r = calculate_variance(ent_sec, c_sec), calculate_variance(ent_sec, r_sec)
            if v_c and v_c != "N/A": res.append(f"C: {v_c}")
            if v_r and v_r != "N/A": res.append(f"R: {v_r}")
            return " | ".join(res) if res else "No Targets"
        return ""

# --- SMART TM PLACEMENT SCRAPER ENGINE ---
def scrape_and_update_all_placements(room_pin, gala_url, club_keyword=""):
    if not gala_url or not room_pin: return 0, "Missing Gala URL or Room PIN."
    
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        resp = requests.get(gala_url, headers=headers, verify=False, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        links = [urljoin(gala_url, a['href']) for a in soup.find_all('a', href=True) if 'event' in a['href'].lower() or re.match(r'^\d+\.htm', a['href'])]
        for f in soup.find_all(['frame', 'iframe']):
            if f.get('src'):
                try:
                    fsoup = BeautifulSoup(requests.get(urljoin(gala_url, f.get('src')), headers=headers, verify=False, timeout=5).text, 'html.parser')
                    links.extend([urljoin(gala_url, a['href']) for a in fsoup.find_all('a', href=True)])
                except: continue

        updated_count = 0
        target_club = club_keyword.strip().lower() if club_keyword else ""

        for link in set(links):
            try:
                psoup = BeautifulSoup(requests.get(link, headers=headers, verify=False, timeout=4).text, 'html.parser')
                
                evt_num = ""
                raw_stroke = ""
                is_results = False
                
                for elem in psoup.find_all(['tr', 'pre', 'p', 'div', 'h1', 'h2', 'h3', 'h4']):
                    rows = []
                    if elem.name == 'tr':
                        cells = [td.get_text(strip=True) for td in elem.find_all(['td', 'th'])]
                        rows.append(" ".join(cells))
                    else:
                        for line in elem.get_text(separator='\n').split('\n'):
                            rows.append(line)
                            
                    for row_text in rows:
                        row_text = row_text.strip()
                        if not row_text: continue
                        
                        m_evt = re.search(r'Event\s+(\d+)', row_text, re.IGNORECASE)
                        if m_evt: evt_num = m_evt.group(1)
                            
                        m_stroke = re.search(r'(\d+m\s+[A-Za-z\.]+(?:\s+[A-Za-z]+)?)', row_text, re.IGNORECASE)
                        if m_stroke: raw_stroke = m_stroke.group(1).strip()
                            
                        lower_text = row_text.lower()
                        
                        if re.search(r'\b(place|pos|position|rank)\b', lower_text):
                            is_results = True
                            continue
                        if re.search(r'\blane\b', lower_text) and not re.search(r'\b(place|pos|position|rank)\b', lower_text):
                            is_results = False
                            continue
                            
                        if is_results and (not target_club or target_club in lower_text):
                            m = re.search(r'^\s*(\d+)\.?\s+(?:\d+\s+)?([A-Za-z\-\'\s]+?)\s+\d{1,2}\s+', row_text)
                            if m:
                                place = int(m.group(1))
                                swimmer_name = m.group(2).strip()
                                
                                if place == 1: badge = "🥇 1st"
                                elif place == 2: badge = "🥈 2nd"
                                elif place == 3: badge = "🥉 3rd"
                                else:
                                    if place % 100 in [11, 12, 13]: badge = f"🏅 {place}th"
                                    elif place % 10 == 1: badge = f"🏅 {place}st"
                                    elif place % 10 == 2: badge = f"🏅 {place}nd"
                                    elif place % 10 == 3: badge = f"🏅 {place}rd"
                                    else: badge = f"🏅 {place}th"

                                parts = swimmer_name.split()
                                if len(parts) >= 2:
                                    first_name, last_name = parts[0], parts[-1]
                                    
                                    res = None
                                    
                                    if evt_num:
                                        res = supabase.table("live_gala_data").update({"official_placement": badge})\
                                            .eq("room_pin", str(room_pin))\
                                            .ilike("swimmer", f"%{first_name}%")\
                                            .ilike("swimmer", f"%{last_name}%")\
                                            .ilike("event", f"%Event {evt_num}%")\
                                            .execute()
                                            
                                    if raw_stroke and (not res or not res.data):
                                        res = supabase.table("live_gala_data").update({"official_placement": badge})\
                                            .eq("room_pin", str(room_pin))\
                                            .ilike("swimmer", f"%{first_name}%")\
                                            .ilike("swimmer", f"%{last_name}%")\
                                            .ilike("event", f"%{raw_stroke}%")\
                                            .execute()
                                            
                                    if res and res.data:
                                        updated_count += 1
            except: continue

        return updated_count, None
    except Exception as e: return 0, str(e)

parsed_entries = []
if input_method == "Web Link (URL)":
    url_input = st.sidebar.text_input("SPORTSYSTEMS URL", value=st.session_state["last_url"])
    if url_input and st.sidebar.button("Process URL"):
        st.session_state["last_url"] = url_input
        with st.spinner("Processing..."):
            try:
                visited = set([url_input])
                pages = [url_input]
                resp = fetch_url_content(url_input)
                soup = BeautifulSoup(resp.text, 'html.parser')
                name = extract_meet_name_from_soup(soup)
                if name: st.session_state["meet_name"] = name
                for frame in soup.find_all(['frame', 'iframe']):
                    if frame.get('src'): pages.append(urljoin(url_input, frame.get('src')))
                links = []
                for p in pages:
                    try:
                        p_soup = BeautifulSoup(fetch_url_content(p).text, 'html.parser')
                        parsed_entries.extend(parse_html_soup(p_soup, club_filter))
                        for a in p_soup.find_all('a', href=True):
                            full = urljoin(p, a['href'])
                            if urlparse(full).netloc == urlparse(url_input).netloc and full not in visited and full.lower().endswith(('.htm', '.html')):
                                links.append(full)
                                visited.add(full)
                    except: continue
                for link in links:
                    try: parsed_entries.extend(parse_html_soup(BeautifulSoup(fetch_url_content(link).text, 'html.parser'), club_filter))
                    except: continue
                if parsed_entries:
                    st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()
                    st.session_state["room_pin"] = None
                    st.rerun()
            except Exception as e: st.error(f"Error: {e}")
elif input_method == "Upload PDF":
    up = st.sidebar.file_uploader("Upload PDF", type=["pdf"])
    if up and st.sidebar.button("Process PDF"):
        with st.spinner("Processing..."):
            lines = []
            with pdfplumber.open(up) as pdf:
                for page in pdf.pages:
                    if page.extract_text(): lines.extend(page.extract_text().split("\n"))
            parsed_entries = parse_text_lines(lines, club_filter)
            if parsed_entries: 
                st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()
                st.session_state["room_pin"] = None
                st.rerun()
elif input_method == "Paste Text":
    txt = st.sidebar.text_area("Paste Text", height=200)
    if txt and st.sidebar.button("Process Text"):
        with st.spinner("Processing..."):
            parsed_entries = parse_text_lines(txt.split("\n"), club_filter)
            if parsed_entries: 
                st.session_state["gala_df"] = pd.DataFrame(parsed_entries).drop_duplicates()
                st.session_state["room_pin"] = None
                st.rerun()

df = st.session_state["gala_df"]
if not df.empty:
    df["_sort_heat"] = pd.to_numeric(df["Heat"], errors='coerce').fillna(9999)
    df["_sort_lane"] = pd.to_numeric(df["Lane"], errors='coerce').fillna(9999)
    if "Checked In" not in df.columns: df["Checked In"] = False
    if "Checked Out" not in df.columns: df["Checked Out"] = False
    
    var_entry = []
    for _, row in df.iterrows():
        var_entry.append(calculate_variance(time_to_seconds(row.get("Achieved Time")), time_to_seconds(row.get("Entry Time"))))
    df["Var vs Entry"] = var_entry
    df_final = compute_gala_schedule_times(df, session_start_map, pace_factor)
else: df_final = df


# --- ⏱ COACH RACE INFO VIEW (NEW SWIPE CARD INTERFACE) ---
if page_selection == VIEW_COACH:
    if not df_final.empty:
        # Calculate KPIs
        ach_u, not_u = df_final["Achieved Time"].astype(str).str.upper(), df_final["Coach Notes"].astype(str).str.upper()
        dq, dnc = int((ach_u.str.contains("DQ") | not_u.str.contains("DQ")).sum()), int((ach_u.str.contains("DNC|WD|WITHDRAWN") | not_u.str.contains("DNC|WD|WITHDRAWN")).sum())
        s_done = len(df_final[(df_final["Achieved Time"] != "") & (~ach_u.str.contains("DNC|WD|WITHDRAWN|DQ")) & (~not_u.str.contains("DNC|WD|WITHDRAWN|DQ"))])
        s_rem = max(0, len(df_final) - s_done - dq - dnc)
        
        st.markdown(f"""
        <div class="status-pill"><span class="status-dot">●</span> Live tracking active · {datetime.now().strftime("%H:%M")}</div>
        <div class="kpi-container">
            <div class="kpi-card"><div class="kpi-val">{s_done}</div><div class="kpi-label">SWIMS DONE</div></div>
            <div class="kpi-card"><div class="kpi-val green">{df_final["Var vs Entry"].str.startswith("✅").sum()}</div><div class="kpi-label">FASTER THAN ENTRY</div></div>
            <div class="kpi-card"><div class="kpi-val red">{dq}</div><div class="kpi-label">DISQUALIFIED</div></div>
            <div class="kpi-card"><div class="kpi-val orange">{dnc}</div><div class="kpi-label">WITHDRAWN</div></div>
            <div class="kpi-card"><div class="kpi-val">{s_rem}</div><div class="kpi-label">SWIMS REMAINING</div></div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("### 📱 Poolside Time Logger")
        
        # 1. Filter out withdrawn/DNC swimmers and sort chronologically by session, event number, heat, lane
        live_races = df_final[~df_final["Achieved Time"].astype(str).str.upper().str.contains("DNC|WD|WITHDRAWN")].copy()
        live_races["_event_num"] = live_races["Event"].apply(get_event_num)
        live_races = live_races.sort_values(by=["Session", "_event_num", "_sort_heat", "_sort_lane"]).reset_index(drop=True)
        
        if live_races.empty:
            st.success("All active races have been logged or withdrawn!")
        else:
            # 2. Initialize the playlist index
            if "race_idx" not in st.session_state:
                st.session_state.race_idx = 0
                
            # Ensure index doesn't go out of bounds if data refreshes or decreases
            if st.session_state.race_idx >= len(live_races):
                st.session_state.race_idx = len(live_races) - 1
            if st.session_state.race_idx < 0:
                st.session_state.race_idx = 0

            # 3. Get the current swimmer's data
            current_race = live_races.iloc[st.session_state.race_idx]
            original_id = current_race.get("id", None)
            
            # --- NEW: Calculate the target variance string ---
            target_str = get_target_analysis(current_race, st.session_state["target_df"], not st.session_state["target_df"].empty)
            target_html = f"<div style='margin-top: 8px; color: #4ade80; font-size: 1.1rem; font-weight: bold; background: #0f172a; padding: 6px 12px; border-radius: 8px; display: inline-block;'>{target_str}</div>" if target_str else ""
            
            # 4. Build the Mobile Card UI
            st.markdown(f"""
            <div style="background-color: #1e293b; padding: 20px; border-radius: 12px; border-top: 5px solid #facc15; box-shadow: 0 4px 6px rgba(0,0,0,0.3); text-align: center; margin-bottom: 15px;">
                <h4 style="color: #94a3b8; margin-bottom: 0;">Sess {current_race.get('Session', '')} | Event {current_race.get('Event', '')}</h4>
                <h2 style="color: #ffffff; margin-top: 5px; font-weight: 900; font-size: 2rem;">{current_race.get('Swimmer', '')}</h2>
                <div style="display: flex; justify-content: space-around; margin-top: 15px; color: #cbd5e1; font-size: 1.2rem;">
                    <div><b>Heat:</b> {current_race.get('Heat', '')}</div>
                    <div><b>Lane:</b> {current_race.get('Lane', '')}</div>
                </div>
                <div style="margin-top: 15px; color: #94a3b8; font-size: 1.1rem;">
                    Entry Time: <strong style="color: white;">{current_race.get('Entry Time', 'NT')}</strong>
                </div>
                {target_html}
            </div>
            """, unsafe_allow_html=True)
            
            # 5. The Input Fields
            new_time = st.text_input("⏱ Enter Achieved Time (e.g. 1:05.23, DQ, DNC)", 
                                     value=current_race.get('Achieved Time', ''), 
                                     key=f"time_input_{original_id}_{st.session_state.race_idx}")
            
            coach_notes = st.text_input("📝 Coach Notes (Optional)", 
                                        value=current_race.get('Coach Notes', ''), 
                                        key=f"notes_input_{original_id}_{st.session_state.race_idx}")
            
            # 6. Navigation & Save Buttons
            col1, col2, col3 = st.columns([1, 1, 1])
            
            with col1:
                if st.button("⬅️ Prev", use_container_width=True, disabled=(st.session_state.race_idx == 0)):
                    st.session_state.race_idx -= 1
                    st.rerun()
                    
            with col2:
                # Save button updates the database and the dataframe
                if st.button("💾 Save", type="primary", use_container_width=True):
                    formatted_time = format_time_input(new_time)
                    if original_id is not None:
                        # Update DB
                        safe_update_db(original_id, "achieved_time", formatted_time)
                        safe_update_db(original_id, "coach_notes", coach_notes)
                        # Update local dataframe
                        mask = st.session_state["gala_df"]["id"] == original_id
                        st.session_state["gala_df"].loc[mask, "Achieved Time"] = formatted_time
                        st.session_state["gala_df"].loc[mask, "Coach Notes"] = coach_notes
                        st.success("Saved!")
                    else:
                        st.warning("Upload data to cloud first to save.")
                    
            with col3:
                if st.button("Next ➡️", use_container_width=True, disabled=(st.session_state.race_idx == len(live_races) - 1)):
                    st.session_state.race_idx += 1
                    st.rerun()
    else: 
        st.info("👈 Load data to begin.")


# --- 📋 SWIMMER WALL PLANNER VIEW ---
elif page_selection == VIEW_WALL:
    if not df_final.empty:
        ui, dl = f"## {club_filter.upper()} GALA SCHEDULE\n\n", f"{club_filter.upper()} GALA SCHEDULE\n{'='*65}\n"
        curr = None
        for _, r in df_final.sort_values(by=["Swimmer", "Session", "Event"]).iterrows():
            if r["Swimmer"] != curr:
                curr = r["Swimmer"]
                ui += f"\n### 👤 {curr} *(Age: {r.get('Age', 'N/A')})*\n| Sess | Event | H/L | Entry | Call | Race |\n| :--- | :--- | :--- | :--- | :--- | :--- |\n"
                dl += f"\n{curr.upper()} (Age: {r.get('Age', 'N/A')})\n{'-'*65}\n"
            evt = extract_standard_event(r['Event']) or r['Event']
            ui += f"| {r['Session']} | {evt} | H{r['Heat']}/L{r['Lane']} | {r['Entry Time']} | **{r['Marshalling Time']}** | {r['Est. Race Time']} |\n"
            dl += f"Sess {r['Session']} | {evt:<18} | H{r['Heat']}/L{r['Lane']:<7} | Entry: {r['Entry Time']:<8} | Call: {r['Marshalling Time']:<5} | Race: {r['Est. Race Time']}\n"
        st.markdown(ui)
        st.download_button("Download (.txt)", dl, "wall_schedule.txt")


# --- 🚩 TM MARSHALLING INFO VIEW ---
elif page_selection == VIEW_TM:
    if not df_final.empty:
        
        # --- OFFICIAL PLACEMENTS SYNC BUTTON ---
        st.markdown("### 🏅 Official Results Sync")
        if st.button("🔄 Fetch & Publish Official Placements"):
            if st.session_state.get("room_pin"):
                room_url = st.session_state.get("last_url", "")
                with st.spinner("Scraping official placements from Sportsystems..."):
                    count, err = scrape_and_update_all_placements(st.session_state["room_pin"], room_url, club_filter)
                    if err:
                        st.error(f"Sync error: {err}")
                    elif count == 0:
                        st.warning("No official medals were found yet. Check back when the club uploads results!")
                    else:
                        st.success(f"Successfully published placements for {count} races!")
                        st.session_state["gala_df"] = fetch_room(st.session_state["room_pin"])
                        st.rerun()
            else:
                st.warning("Please connect to a live room first.")
        
        st.divider()

        rc_cfg = {"Swimmer": st.column_config.TextColumn("Swimmer", width="medium"), "Age": st.column_config.TextColumn("Age", width="small")}
        ev_cfg = {"Heat": st.column_config.TextColumn("Heat", width="small"), "Lane": st.column_config.TextColumn("Lane", width="small"), "Swimmer": st.column_config.TextColumn("Swimmer", width="medium"), "Seen Coach": st.column_config.CheckboxColumn("Seen Coach?", width="small"), "In Marshalling": st.column_config.CheckboxColumn("In Marshalling?", width="small")}
        
        for sess in sorted(df_final["Session"].unique()):
            st.markdown(f"<h3>Session {sess}</h3>", unsafe_allow_html=True)
            sess_df = df_final[df_final["Session"] == sess]
            rc_df = sess_df.drop_duplicates(subset=["Swimmer"])[["Swimmer", "Age", "Checked In", "Checked Out"]].sort_values("Swimmer")
            
            with st.expander(f"📝 Roll Call ({rc_df['Checked In'].sum()}/{len(rc_df)})", expanded=True):
                edited_rc = st.data_editor(rc_df, key=f"rc_s{sess}_{st.session_state['redraw_counter']}", disabled=["Swimmer", "Age"], column_config=rc_cfg, hide_index=True, use_container_width=True)
                rc_changes = False
                for _, r in edited_rc.iterrows():
                    mask = (st.session_state["gala_df"]["Session"] == sess) & (st.session_state["gala_df"]["Swimmer"] == r["Swimmer"])
                    if r["Checked In"] != st.session_state["gala_df"].loc[mask, "Checked In"].iloc[0]:
                        st.session_state["gala_df"].loc[mask, "Checked In"] = r["Checked In"]
                        if st.session_state["room_pin"]: supabase.table("live_gala_data").update({"checked_in": bool(r["Checked In"])}).eq("room_pin", st.session_state["room_pin"]).eq("session", sess).eq("swimmer", r["Swimmer"]).execute()
                        rc_changes = True
                    if r["Checked Out"] != st.session_state["gala_df"].loc[mask, "Checked Out"].iloc[0]:
                        st.session_state["gala_df"].loc[mask, "Checked Out"] = r["Checked Out"]
                        if st.session_state["room_pin"]: supabase.table("live_gala_data").update({"checked_out": bool(r["Checked Out"])}).eq("room_pin", st.session_state["room_pin"]).eq("session", sess).eq("swimmer", r["Swimmer"]).execute()
                        rc_changes = True
                if rc_changes: st.session_state['redraw_counter'] += 1; st.rerun()

            for event in sorted(sess_df["Event"].unique(), key=get_event_num):
                edf = sess_df[sess_df["Event"] == event].sort_values(by=["_sort_heat", "_sort_lane"]).copy()
                with st.expander(f"🏊 {event} — Call: {edf.iloc[0]['Coach Time']} ({len(edf)})", expanded=True):
                    edited_tm = st.data_editor(edf[["Heat", "Lane", "Swimmer", "Age", "Coach Time", "Seen Coach", "Marshalling Time", "In Marshalling", "Est. Race Time"]], key=f"tm_s{sess}_{event}_{st.session_state['redraw_counter']}", disabled=["Heat", "Lane", "Swimmer", "Age", "Coach Time", "Marshalling Time", "Est. Race Time"], column_config=ev_cfg, hide_index=True, use_container_width=True)
                    tm_changes = False
                    for _, r in edited_tm.iterrows():
                        mask = (st.session_state["gala_df"]["Session"] == sess) & (st.session_state["gala_df"]["Event"] == event) & (st.session_state["gala_df"]["Swimmer"] == r["Swimmer"]) & (st.session_state["gala_df"]["Heat"].astype(str) == str(r["Heat"]))
                        if r["Seen Coach"] != st.session_state["gala_df"].loc[mask, "Seen Coach"].values[0]:
                            st.session_state["gala_df"].loc[mask, "Seen Coach"] = r["Seen Coach"]
                            if st.session_state["room_pin"]: safe_update_db(st.session_state["gala_df"].loc[mask, "id"].values[0], "seen_coach", bool(r["Seen Coach"]))
                            tm_changes = True
                        if r["In Marshalling"] != st.session_state["gala_df"].loc[mask, "In Marshalling"].values[0]:
                            st.session_state["gala_df"].loc[mask, "In Marshalling"] = r["In Marshalling"]
                            if st.session_state["room_pin"]: safe_update_db(st.session_state["gala_df"].loc[mask, "id"].values[0], "in_marshalling", bool(r["In Marshalling"]))
                            tm_changes = True
                    if tm_changes: st.session_state['redraw_counter'] += 1; st.rerun()