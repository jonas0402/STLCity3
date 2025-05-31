import streamlit as st
from supabase import create_client
import os
import requests
from ics import Calendar
from datetime import datetime, timezone, date, timedelta
import pandas as pd
import json
import re
import time
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
import urllib.parse
import base64

# Weather API configuration
WEATHER_API_KEY = st.secrets.get("OPENWEATHER_API_KEY", "")
WEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/forecast"
STL_LAT = 38.6270
STL_LON = -90.1994

def get_weather_for_time(game_time):
    """Get weather forecast for a specific game time."""
    if not WEATHER_API_KEY:
        return None
        
    try:
        # Convert game time to unix timestamp
        timestamp = int(game_time.timestamp())
        
        # Make API request
        params = {
            'lat': STL_LAT,
            'lon': STL_LON,
            'appid': WEATHER_API_KEY,
            'units': 'imperial'  # For Fahrenheit
        }
        
        response = requests.get(WEATHER_BASE_URL, params=params)
        response.raise_for_status()
        
        weather_data = response.json()
        
        # Find the closest forecast time
        forecasts = weather_data['list']
        closest_forecast = min(forecasts, 
                             key=lambda x: abs(x['dt'] - timestamp))
        
        return {
            'temp': round(closest_forecast['main']['temp']),
            'description': closest_forecast['weather'][0]['description'],
            'icon': closest_forecast['weather'][0]['icon']
        }
    except Exception as e:
        st.warning(f"Could not fetch weather data: {str(e)}")
        return None

# --- ANNOUNCEMENTS ---
def show_temporary_announcement():
    """Show a temporary announcement that expires after a set date"""
    expiration_date = date(2025, 4, 28)  # One week from April 21, 2025
    if date.today() <= expiration_date:
        st.warning("""
        🔄 **Database Update Notice** 🔄
        
        We've recently fixed a database issue that was affecting game RSVPs. The system is now using a persistent database.
        
        ⚠️ **Action Required**: If you RSVP'd (In/Out) for any games last week, please RSVP again.
        
        Thank you for your understanding!
        """)

# Must be the first Streamlit command
st.set_page_config(
    page_title="STL City 3 Game Participation",
    page_icon="⚽",
    layout="wide"
)

# Show announcement before login (moved here)
show_temporary_announcement()

# Add logo and title in a row with better proportions
col1, col2 = st.columns([1, 6])  # Adjusted ratio for better spacing
with col1:
    # Use a container for consistent padding and alignment
    with st.container():
        st.image("logo.png", width=68, use_container_width=False)  # Set fixed dimensions
with col2:
    st.title("STL City 3 Game Participation")

# --- USER AUTHENTICATION ---
def get_cookie(key):
    """Get cookie value"""
    try:
        value = st.query_params[key]
        return urllib.parse.unquote_plus(value)  # ✅ decode it back
    except (KeyError, IndexError):
        return None

def set_cookie(key, value):
    """Set cookie value"""
    current_params = st.query_params
    encoded_value = urllib.parse.quote_plus(value)  # ✅ encode spaces and full names
    current_params[key] = [encoded_value]
    st.query_params = current_params

# Initialize authentication
username = get_cookie('username')
if username:
    st.session_state['user_name'] = username
    st.session_state['authentication_status'] = True
elif 'authentication_status' not in st.session_state:
    st.session_state['authentication_status'] = False
    st.session_state['user_name'] = None

if not st.session_state['authentication_status']:
    st.info("👋 Welcome! Please login to RSVP for games")
    
    with st.container():
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            st.subheader("🔑 Login")
            name = st.text_input("Enter your name:", placeholder="Your name here")
            if name:
                st.session_state['user_name'] = name
                st.session_state['authentication_status'] = True
                set_cookie('username', name)
                st.rerun()
    
    st.warning("⚠️ You must login to view games and RSVP")
    st.stop()

# Show active user status
st.success(f"👤 Logged in as: {st.session_state.user_name}")

# Ensure ?username=... is in the URL if user is logged in
current_params = st.query_params
if urllib.parse.unquote_plus(current_params.get("username", [None])[0] or "") != st.session_state["user_name"]:
    current_params["username"] = [urllib.parse.quote_plus(st.session_state["user_name"])]
    st.query_params = current_params

# Logout button
if st.button("📱 Logout", type="secondary"):
    st.session_state['user_name'] = None
    st.session_state['authentication_status'] = False
    set_cookie('username', '')
    st.rerun()

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

# --- DATABASE FUNCTIONS ---
def save_or_update_game(event):
    """Save or update game information in the database"""
    try:
        # Extract game details
        game_data = {
            "event_uid": event.uid,
            "name": event.name,
            "start_time": event.begin.datetime.isoformat(),
            "location": event.location if event.location else "",
            "opponent": event.name.split("vs")[1].strip() if "vs" in event.name else "",
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        
        # Check if game exists
        response = supabase.table("games").select("event_uid").eq("event_uid", event.uid).execute()
        
        if not response.data:
            # New game, insert it
            supabase.table("games").insert(game_data).execute()
        else:
            # Existing game, update it
            supabase.table("games").update(game_data).eq("event_uid", event.uid).execute()
            
    except Exception as e:
        st.error(f"Error saving game: {str(e)}")

def update_game_result(event_uid, result_type, score):
    """Update game result in the database"""
    try:
        game_data = {
            "result": result_type,  # "W" or "L"
            "score": score,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        supabase.table("games").update(game_data).eq("event_uid", event_uid).execute()
    except Exception as e:
        st.error(f"Error updating game result: {str(e)}")

def save_game_to_database(event):
    """Save or update a single game and its result in the database"""
    try:
        # Save basic game info
        save_or_update_game(event)
        
        # Check for and save game result if available
        result = parse_game_result(event.name)
        if result:
            result_type = "W" if "Win" in result else "L"
            score = result.split(" ")[1] if len(result.split(" ")) > 1 else ""
            update_game_result(event.uid, result_type, score)
            
        return True
    except Exception as e:
        st.error(f"Error saving game {event.name} to database: {str(e)}")
        return False

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

def clean_game_name(name):
    """Remove 'Soccerdome (Webster Groves) on ' and return cleaned name."""
    prefix = "Soccerdome (Webster Groves) on "
    if name.startswith(prefix):
        return name[len(prefix):]  # Cut the prefix
    return name

def clean_location(location):
    """Smart clean: separate field and address properly."""
    prefix = "Soccerdome (Webster Groves) on "
    if location.startswith(prefix):
        location = location[len(prefix):]

    # Try to find where 'Soccer Park Rd' starts
    split_keyword = "Soccer Park Rd"
    idx = location.find(split_keyword)
    
    if idx != -1:
        field = location[:idx].strip("- ").strip()
        # Remove trailing "1" after field letter (e.g., "A 1" -> "A")
        field = re.sub(r'([A-Z])\s*1$', r'\1', field)
        address = location[idx-2:].strip()  # take two characters before for "1 " in "1 Soccer Park Rd"
        return field, address
    else:
        # fallback: no keyword found
        return location.strip(), None

# Define parse_game_result locally to avoid import issues
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
    """Fetch calendar events and save to database"""
    try:
        # Try to fetch new data
        calendar_data = fetch_calendar_sync(url)
        if calendar_data:
            # Save to cache file for backup
            save_calendar_cache(calendar_data)
            events = parse_calendar_events(calendar_data)
            
            # Save all events to database
            for event in events:
                save_game_to_database(event)
            
            return events
    except Exception as e:
        st.error(f"Failed to fetch fresh calendar data: {str(e)}")
        
        # Try to load from cache
        cached_data, _ = load_calendar_cache()
        if cached_data:
            st.warning("Using cached data while server is unavailable")
            events = parse_calendar_events(cached_data)
            # Even with cached data, ensure games are saved to database
            for event in events:
                save_game_to_database(event)
            return events
        
        # If everything fails, return empty list
        return []

def get_calendar_events_no_cache(url):
    """Non-cached version to initialize the calendar data"""
    try:
        calendar_data = fetch_calendar_sync(url)
        if calendar_data:
            save_calendar_cache(calendar_data)
            events = parse_calendar_events(calendar_data)
            
            # Save all events to database
            for event in events:
                save_game_to_database(event)
            
            return events
    except Exception as e:
        st.error(f"Failed to fetch fresh calendar data: {str(e)}")
        cached_data, _ = load_calendar_cache()
        if cached_data:
            st.warning("Using cached data while server is unavailable")
            events = parse_calendar_events(cached_data)
            # Even with cached data, ensure games are saved to database
            for event in events:
                save_game_to_database(event)
            return events
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

# --- DATABASE VERIFICATION ---
def verify_database_setup():
    """Verify that the required tables exist"""
    try:
        # Check if tables exist by trying to select from them
        supabase.table("users").select("id").limit(1).execute()
        supabase.table("rsvps").select("id").limit(1).execute()
        
        # Create games table if it doesn't exist
        supabase.table("games").select("event_uid").limit(1).execute()
        
        return True
    except Exception as e:
        st.error(f"Database verification failed: {str(e)}")
        st.error("Please make sure all required tables are created in Supabase")
        return False

# Verify database setup
if not verify_database_setup():
    st.stop()

# Now fetch calendar events after database is ready
ical_url = "https://sportsix.sports-it.com/ical/?cid=vetta&id=530739&k=eb6b76bb92bc6e66bdb4cac8357cc495"
events = get_calendar_events(ical_url)  # ✅ Cached version!

# --- HELPER FUNCTIONS ---

# --- DATABASE HELPER FUNCTIONS ---
def get_all_games():
    """Get all games from the database"""
    try:
        response = supabase.table("games").select("*").order("start_time").execute()
        return response.data
    except Exception as e:
        st.error(f"Error getting games: {str(e)}")
        return []

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
        # First, delete any existing RSVP for this user and event
        supabase.table("rsvps").delete().eq("user_id", user_id).eq("event_uid", event_uid).execute()
        
        # Then add the new RSVP
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
        # Use foreign key expansion with proper Supabase syntax
        response = supabase.table("rsvps").select(
            "id, event_uid, participation, timestamp, users:user_id(name)"
        ).execute()
        
        # Transform the response to match the expected format
        transformed_data = []
        for item in response.data:
            transformed_data.append({
                'id': item['id'],
                'name': item['users']['name'],
                'event_uid': item['event_uid'],
                'participation': item['participation'],
                'timestamp': item['timestamp']
            })
        return transformed_data
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
        # First get the user ID
        user_response = supabase.table("users").select("id").eq("name", user_name.lower()).execute()
        if not user_response.data:
            return None
            
        user_id = user_response.data[0]['id']
        
        # Then get the RSVP
        response = supabase.table("rsvps").select("id, participation").eq("user_id", user_id).eq("event_uid", event_uid).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        st.error(f"Error getting user RSVP: {str(e)}")
        return None

def get_rsvp_list(event_uid):
    """Get list of users who RSVP'd for an event."""
    try:
        # Use foreign key expansion with proper Supabase syntax
        response = supabase.table("rsvps").select(
            "users:user_id(name), participation"
        ).eq("event_uid", event_uid).order("timestamp").execute()
        
        # Transform the response to match the expected format
        transformed_data = []
        for item in response.data:
            transformed_data.append({
                'name': item['users']['name'],
                'participation': item['participation']
            })
        return transformed_data
    except Exception as e:
        st.error(f"Error getting RSVP list: {str(e)}")
        return []

# --- STATISTICS FUNCTIONS ---
def get_season_stats():
    """Get overall season statistics"""
    try:
        # Get all games with results
        response = supabase.table("games").select("*").not_.is_("result", "null").order("start_time").execute()
        games = response.data
        
        if not games:
            return None
            
        total_games = len(games)
        wins = len([g for g in games if g['result'] == 'W'])
        losses = len([g for g in games if g['result'] == 'L'])
        
        # Calculate win percentage
        win_pct = (wins / total_games) * 100 if total_games > 0 else 0
        
        # Parse scores to get goals for/against
        goals_for = 0
        goals_against = 0
        for game in games:
            if game['score']:
                try:
                    our_score, their_score = map(int, game['score'].split('-'))
                    goals_for += our_score
                    goals_against += their_score
                except:
                    continue
        
        return {
            'total_games': total_games,
            'wins': wins,
            'losses': losses,
            'win_pct': win_pct,
            'goals_for': goals_for,
            'goals_against': goals_against,
            'goal_diff': goals_for - goals_against,
            'games': games
        }
    except Exception as e:
        st.error(f"Error getting season stats: {str(e)}")
        return None

def get_opponent_stats():
    """Get statistics broken down by opponent"""
    try:
        # Get all games with results
        response = supabase.table("games").select("*").execute()
        games = [g for g in response.data if g['result'] and g['opponent']]
        
        opponent_stats = {}
        for game in games:
            opponent = game['opponent']
            if opponent not in opponent_stats:
                opponent_stats = {'games': 0, 'wins': 0, 'losses': 0, 'goals_for': 0, 'goals_against': 0}
            
            stats = opponent_stats
            stats['games'] += 1
            
            if game['result'] == 'W':
                stats['wins'] += 1
            elif game['result'] == 'L':
                stats['losses'] += 1
                
            if game['score']:
                try:
                    our_score, their_score = map(int, game['score'].split('-'))
                    stats['goals_for'] += our_score
                    stats['goals_against'] += their_score
                except:
                    continue
        
        return opponent_stats
    except Exception as e:
        st.error(f"Error getting opponent stats: {str(e)}")
        return None

def display_season_stats():
    """Display season statistics in a visually appealing way"""
    stats = get_season_stats()
    if not stats:
        st.warning("No game results available yet")
        return
        
    # Overall Record
    st.subheader("Season Record")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Games Played", stats['total_games'])
    with col2:
        st.metric("Wins", stats['wins'])
    with col3:
        st.metric("Losses", stats['losses'])
    with col4:
        st.metric("Win %", f"{stats['win_pct']:.1f}%")
    
    # Goals
    st.subheader("Scoring")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Goals For", stats['goals_for'])
    with col2:
        st.metric("Goals Against", stats['goals_against'])
    with col3:
        st.metric("Goal Difference", stats['goal_diff'], 
                 delta_color="normal" if stats['goal_diff'] >= 0 else "inverse")
    
    # Recent Form
    st.subheader("Recent Form")
    recent_games = stats['games'][-5:]  # Last 5 games
    if recent_games:
        form_cols = st.columns(min(5, len(recent_games)))
        for i, game in enumerate(recent_games):
            with form_cols[i]:
                if game['result'] == 'W':
                    st.success("W")
                else:
                    st.error("L")
                if game['score']:
                    st.caption(f"{game['score']}")
                if game['opponent']:
                    st.caption(f"vs {game['opponent']}")

    # Game History
    if stats['games']:
        st.subheader("Game History")
        game_records = []
        for game in stats['games']:
            game_records.append({
                'Date': game['start_time'].split('T')[0],
                'Opponent': game['opponent'],
                'Result': game['result'],
                'Score': game['score'] if game['score'] else '-'
            })
        
        if game_records:
            df = pd.DataFrame(game_records)
            st.dataframe(df.set_index('Date'), use_container_width=True)

# --- DISPLAY FUNCTIONS ---
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
    current_status = user_rsvp['participation'] if user_rsvp else None
    
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
            delete_rsvp(user_rsvp['id'])
        else:
            # Set status to "In"
            user_id = get_or_create_user(user_name)
            if current_status:  # If there's an existing RSVP
                delete_rsvp(user_rsvp['id'])
            add_rsvp(user_id, event_uid, "In", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        st.rerun()
        
    if cols[1].button(out_text, key=f"{btn_key_prefix}out_{event_uid}", type=out_type):
        if current_status == "Out":
            # If already "Out", remove the RSVP
            delete_rsvp(user_rsvp['id'])
        else:
            # Set status to "Out"
            user_id = get_or_create_user(user_name)
            if current_status:  # If there's an existing RSVP
                delete_rsvp(user_rsvp['id'])
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
                event_time = event.begin.format("h:mm A")
                st.write(f"**{clean_game_name(event.name)}**")
                st.write(f"*{event_time}*")

                # Add weather information
                weather = get_weather_for_time(event.begin.datetime)
                if weather:
                    st.write(f"🌡️ **Weather**: {weather['temp']}°F, {weather['description']}")

                if event.location:
                    field, address = clean_location(event.location)

                    if field:
                        st.write(f"🏟️ **Field**: {field}")

                    if address:
                        st.write(f"📍**Address**: {address}")
                        maps_query = address.replace(' ', '+')
                        google_maps_url = f"https://www.google.com/maps/search/?api=1&query={maps_query}"
                        apple_maps_url = f"https://maps.apple.com/?q={maps_query}"

                        st.markdown(f"""
                            <div style="display: flex; gap: 10px; margin-top: 5px; margin-bottom: 10px;">
                                <a href="{google_maps_url}" target="_blank">
                                    <button style="background-color: #4285F4; color: white; padding: 6px 12px; border: none; border-radius: 5px;">
                                        Google Maps
                                    </button>
                                </a>
                                <a href="{apple_maps_url}" target="_blank">
                                    <button style="background-color: #000000; color: white; padding: 6px 12px; border: none; border-radius: 5px;">
                                        Apple Maps
                                    </button>
                                </a>
                            </div>
                        """, unsafe_allow_html=True)

                        # Only show Fields Map for Soccer Park location
                        if "1 Soccer Park Rd Fenton MO 63026" in address:
                            # Initialize session state for this event's map visibility if not exists
                            map_key = f"show_map_{event.uid}"
                            if map_key not in st.session_state:
                                st.session_state[map_key] = False

                            # Button to toggle map visibility
                            if st.button("🗺️ See Fields Map" if not st.session_state[map_key] else "🗺️ Hide Fields Map", 
                                       key=f"map_button_{event.uid}"):
                                st.session_state[map_key] = not st.session_state[map_key]
                                st.rerun()
                                
                            # Show image if state is True
                            if st.session_state[map_key]:
                                st.image("wwt_map.png", use_container_width=True)

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
                        in_players = [rsvp['name'] for rsvp in rsvps if rsvp['participation'] == "In"]
                        if in_players:
                            st.write(", ".join(sorted(in_players)))
                        else:
                            st.write("No one yet")
                        
                        st.write("❌ Out:")
                        out_players = [rsvp['name'] for rsvp in rsvps if rsvp['participation'] == "Out"]
                        if out_players:
                            st.write(", ".join(sorted(out_players)))
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
        with st.expander(f"{event.begin.date()} {event.begin.format('h:mm A')} - {clean_game_name(event.name)}"):

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
                in_players = [rsvp['name'] for rsvp in rsvps if rsvp['participation'] == "In"]
                if in_players:
                    st.write(", ".join(sorted(in_players)))
                else:
                    st.write("No one yet")
                    
                st.write("❌ Out:")
                out_players = [rsvp['name'] for rsvp in rsvps if rsvp['participation'] == "Out"]
                if out_players:
                    st.write(", ".join(sorted(out_players)))
                else:
                    st.write("No one yet")
            else:
                st.write("No RSVPs yet")

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

# Main tabs for different views
tab1, tab2, tab3, tab4, tab5 = st.tabs(["This Week", "Future Games", "Past Games", "My RSVPs", "Statistics"])

with tab1:
    st.header("Current Week Calendar")
    display_week_calendar(current_week_start, current_week_events)
    
    if current_week_events:
        st.subheader("Week Overview - RSVPs")
        all_rsvps = []
        for event in current_week_events:
            # Get RSVPs for this event
            rsvps = get_rsvp_list(event.uid)
            rsvp_data = supabase.table("rsvps").select(
                "users:user_id(name), participation, timestamp"
            ).eq("event_uid", event.uid).execute()
            
            if rsvp_data.data:
                for rsvp in rsvp_data.data:
                    all_rsvps.append({
                        "Game": f"{event.name} ({event.begin.format('MM/DD')})",
                        "Player": rsvp['users']['name'].title(),
                        "Status": rsvp['participation'],
                        "RSVP Date": pd.to_datetime(rsvp['timestamp']).strftime("%m/%d")
                    })
        
        if all_rsvps:
            df_rsvps = pd.DataFrame(all_rsvps)
            st.dataframe(
                df_rsvps,
                column_config={
                    "Game": st.column_config.TextColumn("Game", width="medium"),
                    "Player": st.column_config.TextColumn("Player", width="small"),
                    "Status": st.column_config.TextColumn(
                        "Status",
                        width="small",
                        help="In or Out"
                    ),
                    "RSVP Date": st.column_config.TextColumn("RSVP Date", width="small")
                },
                use_container_width=True,
                hide_index=True
            )

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
            with st.expander(f"{event.begin.date()} {event.begin.format('h:mm A')} - {event.name}"):

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
                        in_players = [rsvp['name'] for rsvp in rsvps if rsvp['participation'] == "In"]
                        if in_players:
                            st.write(", ".join(sorted(in_players)))
                        else:
                            st.write("No recorded attendance")
                    
                    with col2:
                        st.write("❌ **Declined:**")
                        out_players = [rsvp['name'] for rsvp in rsvps if rsvp['participation'] == "Out"]
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
                        st.write(f"📍 **Location**: {clean_game_name(event.location)}")
    else:
        st.warning("No past games found")

with tab4:
    st.header("My RSVPs")
    user_rsvps = [rsvp for rsvp in get_all_rsvps() if rsvp['name'].lower() == st.session_state.user_name.lower()]
    
    if user_rsvps:
        upcoming_rsvps = []
        past_rsvps = []
        now = datetime.now(timezone.utc)
        
        for rsvp in user_rsvps:
            event = next((e for e in events if e.uid == rsvp['event_uid']), None)
            if event:
                if event.begin.datetime > now:
                    upcoming_rsvps.append((event, rsvp))
                else:
                    past_rsvps.append((event, rsvp))
        
        if upcoming_rsvps:
            st.subheader("Upcoming Games")
            for event, rsvp in sorted(upcoming_rsvps, key=lambda x: x[0].begin.datetime):
                with st.expander(f"{event.begin.date()} {event.begin.format('h:mm A')} - {event.name}"):

                    st.write(f"RSVP'd on: {rsvp['timestamp']}")
                    handle_rsvp_buttons(event.uid, st.session_state.user_name, "my_")
        
        if past_rsvps:
            st.subheader("Past Games")
            for event, rsvp in sorted(past_rsvps, key=lambda x: x[0].begin.datetime, reverse=True)[:5]:
                st.write(f"🎮 {event.begin.date()} - {event.name}: {rsvp['participation']}")
    else:
        st.write("You haven't RSVP'd for any games yet.")
        
    st.markdown("---")
    if st.button("Clear all my RSVPs", type="secondary"):
        user_id = get_or_create_user(st.session_state.user_name)
        if user_id:
            for rsvp in user_rsvps:
                delete_rsvp(rsvp['id'])
            st.success("All your RSVPs have been cleared!")
            st.rerun()

with tab5:
    st.header("Team Statistics")
    display_season_stats()
