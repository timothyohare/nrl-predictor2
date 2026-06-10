from agent.tools.team_sheet import get_team_sheet
from agent.tools.recent_form import get_recent_form
from agent.tools.head_to_head import get_head_to_head
from agent.tools.ladder import get_ladder
from agent.tools.weather import get_weather
from agent.tools.injury_list import get_injury_list
from agent.tools.venue_profile import get_venue_profile
from agent.tools.coaching_matchup import get_coaching_matchup
from agent.tools.web_search import web_search
from agent.tools.trap_game import detect_trap_game
from agent.tools.spine_synergy import get_spine_synergy
from agent.tools.lessons import get_lessons

ALL_TOOLS = [
    get_team_sheet,
    get_recent_form,
    get_head_to_head,
    get_ladder,
    get_weather,
    get_injury_list,
    get_venue_profile,
    get_coaching_matchup,
    web_search,
    detect_trap_game,
    get_spine_synergy,
    get_lessons,
]
