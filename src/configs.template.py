######################
# == User Configs == #
######################

# OPTIONAL: Web app (enter empty string to disable)
WEB_APP_URL = "" # (e.g. 12.34.567.890:1234)
PA_USERNAME, PA_PASSWORD = "", "" # only if using pythonanywhere to auto extend hosting

# OPTIONAL: Telegram notifications (enter empty string to disable)
TELEGRAM_BOT_TOKEN = "" # (e.g. 123456789:ABCdefGHIjkl-MNO_pqrSTUvwxYZ)

# OPTIONAL: Groq API key for faster/more accurate OCR (enter empty string to disable)
GROQ_API_KEY = ""

# Local OCR: auto uses native Apple Vision on macOS, EasyOCR elsewhere.
# Apple Vision failures fall back to EasyOCR. Groq, if configured, runs first.
LOCAL_OCR_BACKEND = "auto" # "auto", "apple_vision", or "easyocr"

# OPTIONAL: Typed Jev decisions via OpenRouter. Keep OPENROUTER_API_KEY in the
# process environment; never store it here or in a packaged desktop app.
JEV_MODE = "shadow" # "off", "shadow" (advice only), or "active"
JEV_MODEL = "typesafe/jev-1.13"
JEV_OBJECTIVE = "farm_and_upgrade" # or "trophies"
JEV_UPGRADES = True
JEV_BASE_SELECTION = False
JEV_DEPLOYMENT = False
# Attack features require a profile calibrated against real screenshots.
JEV_SCREEN_PROFILE_PATH = "" # absolute JSON path; see docs/jev.md
JEV_MIN_CONFIDENCE = 0.70 # distribution confidence, distinct from option probability
JEV_MIN_PROBABILITY = 0.80
JEV_MIN_QUALITY = 0.80
JEV_MAX_AGE_SECONDS = 5
JEV_CONNECT_TIMEOUT = 1
JEV_READ_TIMEOUT = 2
JEV_TOTAL_TIMEOUT = 3 # wall-clock API deadline, including response body
# Limits apply to this bot process (shared by its attacker and upgrader).
JEV_MAX_CALLS = 1000
JEV_MAX_COST_USD = 1.00
# Retained when a request's actual charge is unknown; not a server billing cap.
JEV_RESERVE_COST_USD = 0.01
JEV_MAX_REQUEST_BYTES = 32000
JEV_MAX_RESPONSE_BYTES = 128000
JEV_COOLDOWN_SECONDS = 60
JEV_MAX_SKIPS = 10
JEV_MAX_SEARCH_SECONDS = 25

# REQUIRED: Instance Settings
INSTANCE_IDS = ["BlueStacks Air"]
DEFAULT_INSTANCE_ID = "BlueStacks Air"

# REQUIRED: General Settings
LOCAL_GUI = True # web app not required
CHECK_INTERVAL = 5 # minutes

# REQUIRED: Upgrade settings
# Use the recognized Select Row action for walls; normal priorities still apply.
WALL_GROUP_UPGRADES = True
MAX_UPGRADES_PER_CHECK = 10 # applies to both home and builder base
START_FROM_MENU_TOP = True

#   Home base upgrade settings
OPEN_HOME_BUILDERS = 0 # number of home base builders to keep open (not upgrading), suggested to be 0 for maximum efficiency

UPGRADE_HEROES = True # can be overridden on desktop or web app
UPGRADE_HOME_BASE = True # can be overridden on desktop or web app
UPGRADE_HOME_LAB = True # can be overridden on desktop or web app
ASSIGN_LAB_ASSISTANT = True # can be overridden on desktop or web app
ASSIGN_BUILDER_APPRENTICE = True # can be overridden on desktop or web app

PRIORITY_HOME_BASE_UPGRADES = True # if false, will upgrade in random order regardless of priority settings (can be overridden on desktop or web app)
PRIORITY_HOME_LAB_UPGRADES = True # if false, will upgrade in random order regardless of priority settings (can be overridden on desktop or web app)

#   Every row is a priority level, with the first row being the highest priority
#   Within each row, upgrades are of equal priority and will be randomly chosen between
#   If no listed upgrades are available, will default to random upgrades
#   IMPORTANT: Capitalization and spacing must match exactly with in-game text
#   TIP: It is recommended to minimize the number of priority levels to keep check time reasonable (all upgrades in the same priority are checked in parallel)
HOME_BASE_UPGRADE_PRIORITY = [
    [
        "Laboratory",
        "Blacksmith",
        "Hero Hall",
        "Barbarian King",
        "Archer Queen",
        "Minion Prince",
        "Grand Warden",
        "Royal Champion",
        "Dragon Duke",
    ],
    [
        "Army Camp",
        "Barracks",
        "Dark Barracks",
        "Spell Factory",
        "Dark Spell Factory",
        "Workshop",
        "Clan Castle",
    ],
    [
        "Wall",
    ],
]
HOME_LAB_UPGRADE_PRIORITY = [
    [
        "Balloon",
        "Dragon",
        "Lightning Spell",
        "Rage Spell",
        "Freeze Spell",
        "Poison Spell",
        "Earthquake Spell",
    ],
]

#   Builder base upgrade settings
OPEN_BUILDER_BUILDERS = 0 # number of builder base builders to keep open (not upgrading), suggested to be 0 for maximum efficiency

UPGRADE_BUILDER_BASE = True # can be overridden on desktop or web app
UPGRADE_BUILDER_LAB = True # can be overridden on desktop or web app

PRIORITY_BUILDER_BASE_UPGRADES = True # if false, will upgrade in random order regardless of priority settings (can be overridden on desktop or web app)
PRIORITY_BUILDER_LAB_UPGRADES = True # if false, will upgrade in random order regardless of priority settings (can be overridden on desktop or web app)

#   Every row is a priority level, with the first row being the highest priority
#   Within each row, upgrades are of equal priority and will be randomly chosen between
#   If no listed upgrades are available, will default to random upgrades
#   IMPORTANT: Capitalization and spacing must match exactly with in-game text
#   TIP: It is recommended to minimize the number of priority levels to keep check time reasonable (all upgrades in the same priority are checked in parallel)
BUILDER_BASE_UPGRADE_PRIORITY = [
    [
        "Builder Hall",
        "Multi Mortar",
        "Archer Tower",
        "Double Cannon",
        "Builder Barracks",
        "Battle Machine",
        "Battle Copter",
        "Star Laboratory",
    ],
    [
        "Gold Storage",
        "Elixir Storage",
        "Double Cannon",
        "Archer Tower",
    ],
]
BUILDER_LAB_UPGRADE_PRIORITY = [
    [
        "Boxer Giant",
        "Night Witch",
    ],
    [
        "Baby Dragon",
        "Power P.E.K.K.A",
    ],
]

# REQUIRED: Attack Settings
TROOP_DEPLOY_TIME = 2 # seconds
ATTACK_SLOT_RANGE = (0, 100) # inclusive, first slot is index 0
EXCLUDE_CLAN_TROOPS = True
ATTACK_HOME_BASE = True # can be overridden on desktop or web app
ATTACK_BUILDER_BASE = True # can be overridden on desktop or web app

########################
# == System Configs == #
########################
DEBUG = False
DISABLE_DEVICE_SLEEP = True
EMULATOR_TYPE = "bluestacks" # "bluestacks" or "mumu"
AUTO_START_EMULATOR = True
WINDOW_DIMS = (1920, 1080) # width, height
ADB_ABS_DIR = "" # absolute path to dir with adb executable, leave empty to use system PATH
BLUESTACKS_BIN_PATH = "" # absolute path to Bluestacks executable, leave empty to use system defaults
MUMU_BIN_PATH = "" # absolute path to MuMuManager.exe, leave empty to use system defaults
