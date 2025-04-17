import streamlit as st

# Must be the first Streamlit command
st.set_page_config(
    page_title="STL City 3 Game Participation",
    page_icon="⚽",
    layout="wide"
)

import sqlite3
import os
import requests
from ics import Calendar
from datetime import datetime, timezone, date, timedelta
import pandas as pd
import calendar
import json
import time
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

# Disable insecure request warnings
urllib3.disable_warnings()

# --- CALENDAR CACHE SETTINGS ---
CACHE_FILE = "calendar_cache.json"
CACHE_DURATION = 12 * 3600  # 12 hours in seconds

# --- CALENDAR FETCH SETTINGS ---
import requests.adapters
from requests.packages.urllib3.util.retry import Retry

# Calendar fetch configuration
FETCH_TIMEOUT = 30
RETRY_STRATEGY = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = requests.adapters.HTTPAdapter(max_retries=RETRY_STRATEGY)
http = requests.Session()
http.mount("https://", adapter)
http.mount("http://", adapter)

@st.cache_data(ttl=300)  # 5 minute TTL for parsed events
def parse_calendar_events(calendar_data):
    """Parse calendar data into events (cached separately from raw data)"""
    if not calendar_data:
        return []
    cal = Calendar(calendar_data)
    return list(cal.events)

def fetch_calendar_sync(url):
    """Fetch calendar data synchronously with retries"""
    try:
        response = http.get(
            url,
            timeout=FETCH_TIMEOUT,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/calendar,*/*'
            },
            verify=False  # Disable SSL verification for problematic servers
        )
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to fetch calendar: {str(e)}")

@st.cache_data(ttl=CACHE_DURATION, show_spinner=False)
def get_calendar_events(url):
    """Fetch calendar events with improved error handling and caching"""
    try:
        # Try to fetch new data
        calendar_data = fetch_calendar_sync(url)
        if calendar_data:
            # Save to cache file for backup
            save_calendar_cache(calendar_data)
            return parse_calendar_events(calendar_data)
    except Exception as e:
        st.error(f"Failed to fetch fresh calendar data: {str(e)}")
        
        # Try to load from cache
        cached_data, _ = load_calendar_cache()
        if cached_data:
            st.warning("Using cached data while server is unavailable")
            return parse_calendar_events(cached_data)
        
        # If everything fails, return empty list
        return []

def load_calendar_cache():
    """Load cached calendar data"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
                return cache['data'], True
    except Exception as e:
        st.warning(f"Cache read error: {str(e)}")
    return None, False

def save_calendar_cache(data):
    """Save calendar data to cache file"""
    try:
        cache = {
            'timestamp': time.time(),
            'data': data
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f)
    except Exception as e:
        st.warning(f"Cache write error: {str(e)}")

# Keep existing calendar URL
ical_url = "https://sportsix.sports-it.com/ical/?cid=vetta&id=530739&k=eb6b76bb92bc6e66bdb4cac8357cc495"

# Load calendar without displaying "fetching" message
events = get_calendar_events(ical_url)

# --- SESSION STATE MANAGEMENT ---
if 'user_name' not in st.session_state:
    st.session_state.user_name = None

# --- USER AUTHENTICATION ---
def authenticate_user():
    if st.session_state.user_name is None:
        with st.sidebar:
            st.title("Login")
            name = st.text_input("Enter your name to RSVP:")
            if name:
                st.session_state.user_name = name
                return name
    return st.session_state.user_name

# --- SETUP DATABASE ---
conn = sqlite3.connect("rsvp.db", check_same_thread=False)
c = conn.cursor()

# Create users table if it doesn't exist
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
)
""")
# Create RSVPs table if it doesn't exist
c.execute("""
CREATE TABLE IF NOT EXISTS rsvps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_uid TEXT NOT NULL,
    participation TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
""")
conn.commit()

# --- DATABASE HELPER FUNCTIONS ---
def get_or_create_user(name):
    """Get user id for given name; if not found, create the user."""
    c.execute("SELECT id FROM users WHERE LOWER(name) = LOWER(?)", (name,))
    result = c.fetchone()
    if result:
        return result[0]
    else:
        c.execute("INSERT INTO users (name) VALUES (?)", (name,))
        conn.commit()
        return c.lastrowid

def add_rsvp(user_id, event_uid, participation, timestamp):
    """Insert a new RSVP record."""
    c.execute(
        "INSERT INTO rsvps (user_id, event_uid, participation, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, event_uid, participation, timestamp)
    )
    conn.commit()

def get_rsvp_counts(event_uid):
    """Return counts of 'In' and 'Out' RSVPs for a given event."""
    c.execute("SELECT COUNT(*) FROM rsvps WHERE event_uid = ? AND participation = 'In'", (event_uid,))
    in_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM rsvps WHERE event_uid = ? AND participation = 'Out'", (event_uid,))
    out_count = c.fetchone()[0]
    return in_count, out_count

def get_all_rsvps():
    """Return all RSVP records joined with user names."""
    c.execute("""
        SELECT rsvps.id, users.name, rsvps.event_uid, rsvps.participation, rsvps.timestamp 
        FROM rsvps 
        JOIN users ON rsvps.user_id = users.id
    """)
    return c.fetchall()

def delete_rsvp(rsvp_id):
    """Delete a specific RSVP by its id."""
    c.execute("DELETE FROM rsvps WHERE id = ?", (rsvp_id,))
    conn.commit()

def get_user_rsvp_for_event(user_name, event_uid):
    """Get a user's RSVP status for a specific event."""
    c.execute("""
        SELECT rsvps.id, rsvps.participation
        FROM rsvps 
        JOIN users ON rsvps.user_id = users.id
        WHERE LOWER(users.name) = LOWER(?) AND rsvps.event_uid = ?
    """, (user_name, event_uid))
    result = c.fetchone()
    return result if result else None

def get_rsvp_list(event_uid):
    """Get list of users who RSVP'd for an event."""
    c.execute("""
        SELECT users.name, rsvps.participation
        FROM rsvps 
        JOIN users ON rsvps.user_id = users.id
        WHERE rsvps.event_uid = ?
        ORDER BY rsvps.timestamp
    """, (event_uid,))
    return c.fetchall()

# --- SETUP CALENDAR VIEW ---
today = date.today()
current_week_start = today - timedelta(days=today.weekday())  # Monday
current_week_end = current_week_start + timedelta(days=6)

# Improved event sorting
now = datetime.now(timezone.utc)
current_week_events = [e for e in events if current_week_start <= e.begin.date() <= current_week_end]
future_events = [e for e in events if e.begin.date() > current_week_end]
past_events = [e for e in events if e.begin.datetime < now]

# Sort all event lists
current_week_events.sort(key=lambda e: e.begin.datetime)
future_events.sort(key=lambda e: e.begin.datetime)
past_events.sort(key=lambda e: e.begin.datetime, reverse=True)  # Most recent first

def display_attendance_status(in_count):
    """Display attendance status with clear thresholds and alerts"""
    cols = st.columns([3, 1])
    
    with cols[0]:
        if in_count < 8:
            st.error(f"🚨 EMERGENCY: Only {in_count}/8 players!")
            progress = in_count / 8
            st.markdown(f"**Need {8 - in_count} more players to start the game!**")
        elif in_count < 12:
            st.warning(f"⚠️ Have {in_count}/12 players")
            progress = (in_count - 8) / (12 - 8)  # Progress from 8 to 12
            st.markdown(f"**Need {12 - in_count} more players for ideal subs**")
        else:
            st.success(f"✅ Perfect! {in_count} players (including subs)")
            progress = 1.0
    
    with cols[1]:
        if in_count < 8:
            st.markdown("🏃 Progress to minimum:")
        elif in_count < 12:
            st.markdown("🔄 Progress to ideal:")
        else:
            st.markdown("🌟 Full roster!")
        
    # Show progress bar with custom styling
    st.markdown(
        f"""
        <style>
        .stProgress > div > div > div > div {{
            {'background-color: #ff4b4b' if in_count < 8 else 'background-color: #faa' if in_count < 12 else 'background-color: #4bb543'} 
        }}
        </style>
        """,
        unsafe_allow_html=True
    )
    st.progress(progress)
    
    # Add spacing after the progress bar
    st.markdown("---")

def handle_rsvp_buttons(event_uid, user_name, btn_key_prefix=""):
    """Handle RSVP button interactions with toggle functionality"""
    user_rsvp = get_user_rsvp_for_event(user_name, event_uid)
    current_status = user_rsvp[1] if user_rsvp else None
    
    cols = st.columns(2)
    
    # "In" button - primary when active, secondary when inactive
    in_type = "primary" if current_status == "In" else "secondary"
    in_text = "✅ In" if current_status == "In" else "In"
    
    # "Out" button - primary when active, secondary when inactive
    out_type = "primary" if current_status == "Out" else "secondary"
    out_text = "❌ Out" if current_status == "Out" else "Out"
    
    # Show the buttons side by side
    if cols[0].button(in_text, key=f"{btn_key_prefix}in_{event_uid}", type=in_type):
        if current_status == "In":
            # If already "In", remove the RSVP
            delete_rsvp(user_rsvp[0])
        else:
            # Set status to "In"
            user_id = get_or_create_user(user_name)
            if current_status:  # If there's an existing RSVP
                delete_rsvp(user_rsvp[0])
            add_rsvp(user_id, event_uid, "In", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        st.rerun()
        
    if cols[1].button(out_text, key=f"{btn_key_prefix}out_{event_uid}", type=out_type):
        if current_status == "Out":
            # If already "Out", remove the RSVP
            delete_rsvp(user_rsvp[0])
        else:
            # Set status to "Out"
            user_id = get_or_create_user(user_name)
            if current_status:  # If there's an existing RSVP
                delete_rsvp(user_rsvp[0])
            add_rsvp(user_id, event_uid, "Out", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        st.rerun()
        
    if current_status:
        st.caption(f"Click same button again to un-RSVP")

def display_week_calendar(start_date, events):
    """Display the current week as a grid calendar with interactive RSVPs."""
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    week_dates = [start_date + timedelta(days=i) for i in range(7)]
    
    header_cols = st.columns(7)
    for col, day_name, dt in zip(header_cols, weekday_names, week_dates):
        col.markdown(f"**{day_name} {dt.day}**")
    
    day_cols = st.columns(7)
    for idx, dt in enumerate(week_dates):
        with day_cols[idx]:
            day_events = [e for e in events if e.begin.date() == dt]
            for event in day_events:
                event_time = event.begin.format("HH:mm")
                st.write(f"**{event.name}**")
                st.write(f"*{event_time}*")
                
                # Get attendance counts
                in_count, out_count = get_rsvp_counts(event.uid)
                
                # Display attendance status with alerts
                display_attendance_status(in_count)
                
                # Show detailed counts
                cols = st.columns(2)
                with cols[0]:
                    st.write("👍 In:", in_count)
                with cols[1]:
                    st.write("👎 Out:", out_count)
                
                # Show RSVP buttons if user is logged in
                if st.session_state.user_name:
                    handle_rsvp_buttons(event.uid, st.session_state.user_name)
                
                # Show who's in/out
                with st.expander("See who's playing"):
                    rsvps = get_rsvp_list(event.uid)
                    if rsvps:
                        st.write("✅ In:")
                        in_players = [name for name, status in rsvps if status == "In"]
                        if in_players:
                            st.write(", ".join(in_players))
                        else:
                            st.write("No one yet")
                            
                        st.write("❌ Out:")
                        out_players = [name for name, status in rsvps if status == "Out"]
                        if out_players:
                            st.write(", ".join(out_players))
                        else:
                            st.write("No one yet")
                    else:
                        st.write("No RSVPs yet")
                
                st.markdown("---")

def display_future_events(events):
    """Display future events in an interactive list format."""
    if not events:
        st.write("No future events.")
        return
        
    events_sorted = sorted(events, key=lambda e: e.begin.date())
    for event in events_sorted:
        with st.expander(f"{event.begin.date()} {event.begin.format('HH:mm')} - {event.name}"):
            in_count, out_count = get_rsvp_counts(event.uid)
            
            # Display attendance status with progress bar
            display_attendance_status(in_count)
            
            # Show detailed counts
            cols = st.columns(2)
            with cols[0]:
                st.write("👍 In:", in_count)
            with cols[1]:
                st.write("👎 Out:", out_count)
            
            # Show RSVP buttons if user is logged in
            if st.session_state.user_name:
                handle_rsvp_buttons(event.uid, st.session_state.user_name, "future_")
            
            # Show who's in/out
            rsvps = get_rsvp_list(event.uid)
            if rsvps:
                st.write("✅ In:")
                in_players = [name for name, status in rsvps if status == "In"]
                if in_players:
                    st.write(", ".join(in_players))
                else:
                    st.write("No one yet")
                    
                st.write("❌ Out:")
                out_players = [name for name, status in rsvps if status == "Out"]
                if out_players:
                    st.write(", ".join(out_players))
                else:
                    st.write("No one yet")
            else:
                st.write("No RSVPs yet")

def parse_game_result(event_name):
    """Parse the game result from the event name if available"""
    if "L" in event_name and "vs" in event_name:
        try:
            # Extract score like "L 3-5"
            result_part = event_name.split("vs")[0]
            if "L" in result_part:
                score = result_part.split("L")[1].strip()
                return f"Loss {score}"
        except:
            pass
    elif "W" in event_name and "vs" in event_name:
        try:
            # Extract score like "W 3-5"
            result_part = event_name.split("vs")[0]
            if "W" in result_part:
                score = result_part.split("W")[1].strip()
                return f"Win {score}"
        except:
            pass
    return None

# --- STREAMLIT APP LAYOUT ---

# Add logo and title in a row with better proportions
col1, col2 = st.columns([1, 6])  # Adjusted ratio for better spacing
with col1:
    # Use a container for consistent padding and alignment
    with st.container():
        st.image("logo.png", width=68, use_container_width=False)  # Set fixed dimensions
with col2:
    st.title("STL City 3 Game Participation")

# Show login form in main content area for mobile users if not logged in
if not st.session_state.user_name:
    st.info("👋 Welcome! Please login to RSVP for games")
    
    # Create a centered container for login
    with st.container():
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            st.subheader("🔑 Login")
            name = st.text_input("Enter your name:", placeholder="Your name here")
            if name:
                st.session_state.user_name = name
                st.rerun()
    
    # Early return if not logged in
    st.warning("⚠️ You must login to view games and RSVP")
    st.stop()

# Show active user status in main area for mobile
st.success(f"👤 Logged in as: {st.session_state.user_name}")

# Add logout button in main content
if st.button("📱 Logout", type="secondary"):
    st.session_state.user_name = None
    st.rerun()

# Remove duplicate login from sidebar since it's now in main content
with st.sidebar:
    if st.session_state.user_name:
        st.success(f"Logged in as: {st.session_state.user_name}")

# Main tabs for different views
tab1, tab2, tab3, tab4 = st.tabs(["This Week", "Future Games", "Past Games", "My RSVPs"])

with tab1:
    st.header("Current Week Calendar")
    display_week_calendar(current_week_start, current_week_events)
    
    if current_week_events:
        st.subheader("Week Overview")
        stats = []
        for event in current_week_events:
            in_count, out_count = get_rsvp_counts(event.uid)
            stats.append({
                "Game": f"{event.name} ({event.begin.format('YYYY-MM-DD')})",
                "In": in_count,
                "Out": out_count
            })
        if stats:
            df_stats = pd.DataFrame(stats).set_index("Game")
            st.bar_chart(df_stats)

with tab2:
    st.header("Future Games")
    if future_events:
        st.info(f"Showing all {len(future_events)} upcoming games")
        display_future_events(future_events)
    else:
        st.warning("No future games scheduled yet")

with tab3:
    st.header("Past Games")
    if past_events:
        st.info(f"Showing all {len(past_events)} past games")
        for event in past_events:  # Show all past games
            with st.expander(f"{event.begin.date()} {event.begin.format('HH:mm')} - {event.name}"):
                # Parse and display game result if available
                result = parse_game_result(event.name)
                if result:
                    if "Loss" in result:
                        st.error(f"📊 Result: {result}")
                    else:
                        st.success(f"📊 Result: {result}")
                
                # Get attendance counts
                in_count, out_count = get_rsvp_counts(event.uid)
                
                # Show attendance summary
                cols = st.columns(2)
                with cols[0]:
                    st.write("👥 **Final Attendance**:", in_count)
                with cols[1]:
                    if out_count > 0:
                        st.write("🚫 **Declined**:", out_count)
                
                # Show who played
                rsvps = get_rsvp_list(event.uid)
                if rsvps:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write("✅ **Played:**")
                        in_players = [name for name, status in rsvps if status == "In"]
                        if in_players:
                            st.write(", ".join(sorted(in_players)))
                        else:
                            st.write("No recorded attendance")
                    
                    with col2:
                        st.write("❌ **Declined:**")
                        out_players = [name for name, status in rsvps if status == "Out"]
                        if out_players:
                            st.write(", ".join(sorted(out_players)))
                        else:
                            st.write("None")
                
                # Show the opponent and location
                game_details = st.columns(2)
                with game_details[0]:
                    if "vs" in event.name:
                        opponent = event.name.split("vs")[1].strip()
                        st.write(f"🆚 **Opponent**: {opponent}")
                
                with game_details[1]:
                    if event.location:
                        st.write(f"📍 **Location**: {event.location}")
    else:
        st.warning("No past games found")

with tab4:
    st.header("My RSVPs")
    user_rsvps = [rsvp for rsvp in get_all_rsvps() if rsvp[1].lower() == st.session_state.user_name.lower()]
    
    if user_rsvps:
        upcoming_rsvps = []
        past_rsvps = []
        now = datetime.now(timezone.utc)
        
        for rsvp in user_rsvps:
            rsvp_id, user_name, event_uid, participation, timestamp = rsvp
            event = next((e for e in events if e.uid == event_uid), None)
            if event:
                if event.begin.datetime > now:
                    upcoming_rsvps.append((event, rsvp))
                else:
                    past_rsvps.append((event, rsvp))
        
        if upcoming_rsvps:
            st.subheader("Upcoming Games")
            for event, rsvp in sorted(upcoming_rsvps, key=lambda x: x[0].begin.datetime):
                with st.expander(f"{event.begin.date()} {event.begin.format('HH:mm')} - {event.name}"):
                    st.write(f"RSVP'd on: {rsvp[4]}")
                    handle_rsvp_buttons(event.uid, st.session_state.user_name, "my_")
        
        if past_rsvps:
            st.subheader("Past Games")
            for event, rsvp in sorted(past_rsvps, key=lambda x: x[0].begin.datetime, reverse=True)[:5]:
                _, _, _, participation, timestamp = rsvp
                st.write(f"🎮 {event.begin.date()} - {event.name}: {participation}")
    else:
        st.write("You haven't RSVP'd for any games yet.")
        
    st.markdown("---")
    if st.button("Clear all my RSVPs", type="secondary"):
        user_id = get_or_create_user(st.session_state.user_name)
        c.execute("DELETE FROM rsvps WHERE user_id = ?", (user_id,))
        conn.commit()
        st.success("All your RSVPs have been cleared!")
        st.rerun()
