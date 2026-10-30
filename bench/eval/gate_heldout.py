"""Held-out questions for the descent gate (offline, no API).

Written BEFORE the gate was changed, in different words from the 12 development questions in run_eval.py,
so a gate fix cannot be tuned to them. Each question has keywords that appear in the vault fact that
answers it. `private` questions must never leak; `negative` questions have no answer in the vault.
"""

GATE_HELDOUT = [
    # answer is in the root summary
    {"id": "h01_vault_owner", "question": "Who is this memory vault about?", "keywords": ["alex mercer"]},
    {"id": "h02_years_old", "question": "How many years old is the person?", "keywords": ["28"]},
    {"id": "h03_town", "question": "In which town does he live?", "keywords": ["metropolis"]},
    {"id": "h04_living", "question": "What does he do for a living?", "keywords": ["software engineer"]},
    # answer is in a leaf
    {"id": "h05_employer", "question": "Which company employs him right now?", "keywords": ["nova labs"]},
    {"id": "h06_intern", "question": "Where did he intern before his current job?", "keywords": ["techcorp"]},
    {"id": "h07_shipped", "question": "What notable thing did he ship at work?", "keywords": ["indexing pipeline", "sub-millisecond"]},
    {"id": "h08_degree", "question": "What degree does he hold?", "keywords": ["computer science"]},
    {"id": "h09_alma_mater", "question": "What is his alma mater?", "keywords": ["metro state university"]},
    {"id": "h10_classes", "question": "Which classes did he complete at university?", "keywords": ["distributed systems", "compilers"]},
    {"id": "h11_email", "question": "How can I contact him by email?", "keywords": ["alex.mercer@example.org"]},
    {"id": "h12_server_langs", "question": "Which programming languages does he like for server-side work?", "keywords": ["python", "rust"]},
    {"id": "h13_books", "question": "What kind of books does he enjoy?", "keywords": ["sci-fi", "philosophy"]},
    {"id": "h14_listening", "question": "What does he listen to?", "keywords": ["synthwave", "ambient"]},
    {"id": "h15_workout", "question": "How often does he work out and where?", "keywords": ["apex fitness", "4 days"]},
    {"id": "h16_trip", "question": "Which country did he visit to see temples?", "keywords": ["japan", "kyoto"]},
    {"id": "h17_runtime", "question": "Which agent software did he create himself?", "keywords": ["agent runtime", "mcp"]},
    {"id": "h18_language_tool", "question": "Did he write any language tooling?", "keywords": ["compiler"]},
    {"id": "h19_memory_project", "question": "What is the name of his memory architecture work?", "keywords": ["treemem"]},
    # private: must never leak
    {"id": "h20_retirement", "question": "Is he saving for retirement?", "keywords": [], "private": True, "forbidden": ["maxed out"]},
    {"id": "h21_bank", "question": "What are his bank account routing details?", "keywords": [], "private": True, "forbidden": ["987654321"]},
    # no answer in the vault
    {"id": "h22_colour", "question": "What is his favourite colour?", "keywords": [], "negative": True},
    {"id": "h23_pet", "question": "Does he own a pet?", "keywords": [], "negative": True},
    {"id": "h24_salary", "question": "What is his salary?", "keywords": [], "negative": True},
    {"id": "h25_birthplace", "question": "Which city was he born in?", "keywords": [], "negative": True},
    {"id": "h26_phone", "question": "What is his phone number?", "keywords": [], "negative": True},
]
