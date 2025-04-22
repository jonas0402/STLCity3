import streamlit as st
from supabase import create_client
from dotenv import load_dotenv
import os
import requests
from ics import Calendar
from datetime import datetime, timezone, date, timedelta
import pandas as pd
import json
import time
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

# Must be the first Streamlit command
st.set_page_config(
    page_title="STL City 3 Game Participation",
    page_icon="⚽",
    layout="wide"
)

# --- SUPABASE CONFIGURATION ---
try:
    # Try to get credentials from Streamlit secrets
    supabase = create_client(
        supabase_url=st.secrets["supabase"]["url"],
        supabase_key=st.secrets["supabase"]["key"]
    )
except Exception as e:
    st.error("⚠️ Supabase connection failed. Please check your credentials in Streamlit secrets.")
    st.stop()

# Initialize database tables if they don't exist
def init_supabase():
    # Create users table
    supabase.table("users").execute()
    
    # Create rsvps table
    supabase.table("rsvps").execute()

try:
    init_supabase()
except Exception as e:
    st.error(f"Database initialization error: {str(e)}")

# --- CALENDAR CACHE SETTINGS ---
CACHE_FILE = "calendar_cache.json"
CACHE_DURATION = 12 * 3600  # 12 hours in seconds

# --- CALENDAR FETCH SETTINGS ---
FETCH_TIMEOUT = 30
RETRY_STRATEGY = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=RETRY_STRATEGY)
http = requests.Session()
http.mount("https://", adapter)
http.mount("http://", adapter)

# Disable insecure request warnings
urllib3.disable_warnings()

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

# --- DATABASE HELPER FUNCTIONS ---
def get_or_create_user(name):
    """Get user id for given name; if not found, create the user."""
    try:
        # Try to find existing user
        response = supabase.table("users").select("id").eq("name", name.lower()).execute()
        if response.data:
            return response.data[0]['id']
        
        # Create new user if not found
        response = supabase.table("users").insert({"name": name.lower()}).execute()
        return response.data[0]['id']
    except Exception as e:
        st.error(f"Error in get_or_create_user: {str(e)}")
        return None

def add_rsvp(user_id, event_uid, participation, timestamp):
    """Insert a new RSVP record."""
    try:
        supabase.table("rsvps").insert({
            "user_id": user_id,
            "event_uid": event_uid,
            "participation": participation,
            "timestamp": timestamp
        }).execute()
    except Exception as e:
        st.error(f"Error adding RSVP: {str(e)}")

def get_rsvp_counts(event_uid):
    """Return counts of 'In' and 'Out' RSVPs for a given event."""
    try:
        in_response = supabase.table("rsvps").select("id").eq("event_uid", event_uid).eq("participation", "In").execute()
        out_response = supabase.table("rsvps").select("id").eq("event_uid", event_uid).eq("participation", "Out").execute()
        return len(in_response.data), len(out_response.data)
    except Exception as e:
        st.error(f"Error getting RSVP counts: {str(e)}")
        return 0, 0

def get_all_rsvps():
    """Return all RSVP records joined with user names."""
    try:
        response = supabase.table("rsvps").select("rsvps.id, users.name, rsvps.event_uid, rsvps.participation, rsvps.timestamp").join("users", "rsvps.user_id=users.id").execute()
        return response.data
    except Exception as e:
        st.error(f"Error getting all RSVPs: {str(e)}")
        return []

def delete_rsvp(rsvp_id):
    """Delete a specific RSVP by its id."""
    try:
        supabase.table("rsvps").delete().eq("id", rsvp_id).execute()
    except Exception as e:
        st.error(f"Error deleting RSVP: {str(e)}")

def get_user_rsvp_for_event(user_name, event_uid):
    """Get a user's RSVP status for a specific event."""
    try:
        response = supabase.table("rsvps").select("rsvps.id, rsvps.participation").join("users", "rsvps.user_id=users.id").eq("users.name", user_name.lower()).eq("rsvps.event_uid", event_uid).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        st.error(f"Error getting user RSVP: {str(e)}")
        return None

def get_rsvp_list(event_uid):
    """Get list of users who RSVP'd for an event."""
    try:
        response = supabase.table("rsvps").select("users.name, rsvps.participation").join("users", "rsvps.user_id=users.id").eq("event_uid", event_uid).order("rsvps.timestamp").execute()
        return response.data
    except Exception as e:
        st.error(f"Error getting RSVP list: {str(e)}")
        return []

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
    # Display week calendar logic here...

with tab2:
    st.header("Future Games")
    # Display future games logic here...

with tab3:
    st.header("Past Games")
    # Display past games logic here...

with tab4:
    st.header("My RSVPs")
    # Display user RSVPs logic here...
