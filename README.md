# STL City 3 Game Participation App

A Streamlit web application for managing game participation and RSVPs for STL City 3 soccer team.

## Features

- View current week's games in calendar format
- RSVP for upcoming games with 'In' or 'Out' status
- Track player attendance and game results
- View past game history and attendance
- Player threshold alerts (minimum 8 players, ideal 12 players)
- Case-insensitive user management
- Automatic calendar sync with sports-it.com

## Setup

1. Create a Python virtual environment:
```bash
python -m venv stl
```

2. Activate the virtual environment:
- Windows: `.\stl\Scripts\activate`
- Unix/MacOS: `source stl/bin/activate`

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the application:
```bash
streamlit run app.py
```

## Usage

1. Enter your name in the sidebar to log in
2. View current week's games in the calendar view
3. RSVP for games by clicking "In" or "Out"
4. Monitor player counts and thresholds
5. View your RSVP history in "My RSVPs" tab

## Tech Stack

- Python
- Streamlit
- SQLite
- ics (iCalendar parser)
- Pandas (data analysis)