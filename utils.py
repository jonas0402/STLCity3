"""Utility functions for the STL City 3 Game Participation app"""

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