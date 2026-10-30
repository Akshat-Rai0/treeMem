"""Deterministic mid-size vault (about 310 facts) and question set. No API calls.

Every answer value (hotel, restaurant, album, tool, professor, pet name...) is unique and invented, so the
ground truth is known exactly and the gate can not guess from world knowledge. Facts are placed with the real
TreeManager.remember / place API; parent summaries are committed bottom-up with commit_summary, like an agent would.

    python bench/make_midsize_vault.py --out /tmp/vault --seed 7
"""

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

from treemem.tree_manager import TreeManager

# ----------------------------------------------------------------------------
# Name pools (combined and shuffled with a fixed seed so every value is unique)
# ----------------------------------------------------------------------------

ADJ = ["Amber", "Velvet", "Silver", "Hollow", "Quiet", "Crimson", "Gilded", "Misty", "Northern", "Paper",
       "Lunar", "Copper", "Wandering", "Bright", "Tidal", "Ivory", "Cobalt", "Fading", "Wild", "Gentle"]
NOUN = ["Orchard", "Harbor", "Lantern", "Meadow", "Compass", "Garden", "Bridge", "Canyon", "Forest", "Tower",
        "Anchor", "Mirror", "Window", "Thistle", "Ember", "Summit", "Echo", "Voyage", "Atlas", "Willow"]
FIRST = ["Mara", "Idris", "Noor", "Tomas", "Lena", "Kofi", "Ines", "Rafael", "Sana", "Viktor", "Ayla", "Bruno",
         "Chiara", "Dmitri", "Elif", "Farid", "Greta", "Hugo", "Imani", "Jonas"]
LAST = ["Okafor", "Lindqvist", "Marchetti", "Vasquez", "Haddad", "Ivanov", "Nakamura", "Oyelaran", "Petrov",
        "Quinteros", "Rasmussen", "Sorensen", "Tanaka", "Umarov", "Villanueva", "Westbrook", "Yilmaz", "Zielinski",
        "Abara", "Brandt"]
PET_NAMES = ["Biscuit", "Pickle", "Waffles", "Noodle", "Mochi", "Pepper", "Juniper", "Clover", "Maple", "Tango",
             "Sprout", "Pistachio", "Marmalade", "Truffle", "Cinder", "Bramble", "Fennel", "Olive", "Nutmeg",
             "Pebble", "Ziggy", "Comet", "Saffron", "Poppy"]
BANKS = ["Harborline Bank", "Pinecrest Credit Union", "Northgate Savings", "Brightwater Bank", "Stonebridge Trust",
         "Larkspur Financial"]

TRAVEL_GROUPS = {
    "east_asia": ["Tokyo", "Kyoto", "Osaka", "Seoul", "Busan", "Taipei"],
    "southeast_asia": ["Bangkok", "Hanoi", "Singapore", "Manila", "Jakarta", "Phnom Penh"],
    "south_asia": ["Delhi", "Mumbai", "Colombo", "Kathmandu", "Dhaka", "Jaipur"],
    "western_europe": ["Paris", "Lisbon", "Madrid", "Amsterdam", "Brussels", "Dublin"],
    "eastern_europe": ["Prague", "Warsaw", "Budapest", "Krakow", "Sofia", "Tallinn"],
    "northern_europe": ["Oslo", "Stockholm", "Helsinki", "Copenhagen", "Reykjavik", "Bergen"],
    "southern_europe": ["Rome", "Athens", "Naples", "Valencia", "Split", "Valletta"],
    "north_america": ["Toronto", "Chicago", "Denver", "Austin", "Montreal", "Seattle"],
    "latin_america": ["Bogota", "Santiago", "Buenos Aires", "Quito", "Montevideo", "Cusco"],
    "africa": ["Nairobi", "Accra", "Cairo", "Marrakesh", "Cape Town", "Dakar"],
}
SPARE_CITIES = ["Ulaanbaatar", "Windhoek", "Tbilisi"]  # never used in facts: negative questions

MUSIC_GROUPS = {
    "rock": ["indie rock", "punk", "shoegaze", "grunge"],
    "electronic": ["techno", "ambient", "drum and bass", "house"],
    "jazz_blues": ["bebop", "delta blues", "cool jazz", "fusion"],
    "folk_world": ["bluegrass", "flamenco", "afrobeat", "celtic"],
    "classical": ["baroque", "romantic", "minimalist", "opera"],
    "urban": ["trip hop", "soul", "reggae", "funk"],
}
READING_GROUPS = {
    "fiction_speculative": ["space opera", "cyberpunk", "dystopian", "fantasy"],
    "fiction_classic": ["gothic", "magical realism", "satire", "epic poetry"],
    "nonfiction_science": ["astronomy", "neuroscience", "ecology", "mathematics"],
    "nonfiction_society": ["economics", "urban planning", "linguistics", "anthropology"],
    "memoir_history": ["war memoir", "ancient history", "travel writing", "biography"],
}
SPARE_GENRES = ["romance", "horror"]
FOOD_GROUPS = {
    "east_asian_cuisine": ["Sichuan", "Korean", "Cantonese", "Japanese izakaya"],
    "south_asian_cuisine": ["Punjabi", "Bengali", "Sri Lankan", "Gujarati"],
    "mediterranean_cuisine": ["Greek", "Lebanese", "Moroccan", "Sicilian"],
    "american_cuisine": ["Texan barbecue", "Cajun", "Peruvian", "Oaxacan"],
    "european_cuisine": ["Basque", "Polish", "Georgian", "Nordic"],
}
CLIENT_SECTORS = {
    "logistics_clients": ["Redline Freight", "Portwise", "Cargolark", "Haulstone"],
    "health_clients": ["Mediva", "Carepath", "Lumen Clinic", "Vitalis"],
    "retail_clients": ["Marketbloom", "Shelfwise", "Brightcart", "Stockyard"],
    "energy_clients": ["Gridlight", "Solvane", "Windmere", "Voltaic Works"],
    "education_clients": ["Learnbridge", "Campusly", "Scholarway", "Tutorly"],
}
TOOL_AREAS = {
    "tools_data": ["data cleaning", "dashboards", "forecasting", "log analysis"],
    "tools_writing": ["documentation", "diagram drawing", "note taking", "slide decks"],
    "tools_infra": ["deployment", "monitoring", "secrets management", "load testing"],
    "tools_collab": ["code review", "sprint planning", "incident response", "design feedback"],
    "tools_research": ["paper reading", "citation tracking", "experiment tracking", "dataset versioning"],
}
SPARE_TASKS = ["accessibility audits"]
EDU_GROUPS = {
    "courses_math": ["linear algebra", "probability", "graph theory", "numerical methods"],
    "courses_cs": ["operating systems", "databases", "computer networks", "cryptography"],
    "courses_science": ["thermodynamics", "organic chemistry", "genetics", "optics"],
    "courses_humanities": ["moral philosophy", "art history", "rhetoric", "world literature"],
    "courses_social": ["microeconomics", "sociology", "political theory", "cognitive psychology"],
    "courses_design": ["typography", "interaction design", "color theory", "industrial design"],
}
FITNESS_GROUPS = {
    "strength": ["powerlifting", "kettlebell training", "rock climbing"],
    "endurance": ["trail running", "road cycling", "open water swimming"],
    "mind_body": ["yoga", "tai chi", "pilates"],
    "combat": ["judo", "boxing", "fencing_unused"],
    "team_sports": ["ultimate frisbee", "volleyball", "rowing"],
    "outdoor": ["bouldering", "kayaking", "orienteering"],
}
SPARE_ACTIVITY = "archery"
FAMILY_RELATIVES = ["sister", "brother", "mother", "father", "cousin", "grandmother", "uncle", "aunt"]
FAMILY_ANIMALS = ["dog", "cat", "parrot"]
SPARE_RELATIVE = "godfather"


def unique_names(rng: random.Random, first: List[str], second: List[str], template: str, count: int) -> List[str]:
    combos = [template.format(a=a, b=b) for a in first for b in second]
    rng.shuffle(combos)
    if count > len(combos):
        raise ValueError("not enough unique name combinations")
    return combos[:count]


def build_specs(seed: int) -> Dict[str, Any]:
    """Return the facts (with their leaf path) and the question candidates."""
    rng = random.Random(seed)
    facts: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    members: Dict[str, List[str]] = {}

    hotels = unique_names(rng, ADJ, NOUN, "{a} {b} Hotel", 60)
    restaurants = unique_names(rng, ADJ, NOUN, "{a} {b} Kitchen", 50)
    dishes = unique_names(
        rng,
        ["Smoked", "Braised", "Crispy", "Charred", "Steamed", "Pickled", "Roasted", "Glazed"],
        ["lamb", "eel", "tofu", "squash", "pike", "duck", "beets", "quail"],
        "{a} {b}",
        50,
    )
    albums = unique_names(rng, ADJ, NOUN, "{a} {b}", 60)
    bands = unique_names(rng, ["The"], [f"{a} {n}s" for a in ADJ[:10] for n in ["Moth", "Fox", "Heron", "Lynx"]], "{a} {b}", 24)
    venues = unique_names(rng, ADJ, ["Hall", "Arena", "Club", "Theatre"], "{a} {b}", 24)
    titles = unique_names(rng, NOUN, ADJ, "The {a} of {b}", 20)
    cuisine_dishes = unique_names(rng, ["Golden", "Fire", "Midnight", "Spiced", "Green"], ["dumplings", "stew", "flatbread", "noodles", "skewers"], "{a} {b}", 20)
    projects = unique_names(rng, ["Project"], NOUN, "{a} {b}", 20)
    tools = unique_names(rng, ["Quill", "Brisk", "Tern", "Nimbus", "Fathom", "Spindle", "Lattice", "Ember"], ["base", "flow", "kit", "desk", "hub"], "{a}{b}", 20)
    profs = unique_names(rng, FIRST, LAST, "{a} {b}", 24)
    gyms = unique_names(rng, ADJ, ["Barbell Club", "Training Hall", "Athletic Centre", "Fitness Loft"], "{a} {b}", 18)
    pets = PET_NAMES[:]
    rng.shuffle(pets)

    counters = {"hotel": 0, "rest": 0, "dish": 0, "album": 0, "band": 0, "title": 0, "cd": 0, "proj": 0,
                "tool": 0, "prof": 0, "gym": 0, "pet": 0}

    def take(kind: str, pool: List[str]) -> str:
        value = pool[counters[kind]]
        counters[kind] += 1
        return value

    # travel: hotel for every city, a restaurant for 5 of the 6 cities per group
    for group, cities in TRAVEL_GROUPS.items():
        path = f"travel/{group}"
        members[path] = list(cities)
        for index, city in enumerate(cities):
            hotel = take("hotel", hotels)
            facts.append({"path": path, "fact": f"During the trip to {city} he stayed at the {hotel}.", "relation": "hotel"})
            candidates.append({
                "path": facts[-1]["path"],
                "relation": "hotel", "answer": hotel,
                "direct": f"Which hotel did he stay at in {city}?",
                "paraphrase": f"Where did he sleep during his {city} trip?",
            })
            if index < 5:
                restaurant = take("rest", restaurants)
                dish = take("dish", dishes)
                facts.append({"path": path, "fact": f"In {city} the best meal was {dish} at {restaurant}.", "relation": "restaurant"})
                candidates.append({
                "path": facts[-1]["path"],
                    "relation": "restaurant", "answer": restaurant,
                    "direct": f"Where did he eat the best meal in {city}?",
                    "paraphrase": f"Which restaurant impressed him in {city}?",
                })

    # music: album per genre and one concert per genre
    for group, genres in MUSIC_GROUPS.items():
        path = f"music/{group}"
        members[path] = list(genres)
        for genre in genres:
            album = take("album", albums)
            facts.append({"path": path, "fact": f"His favorite {genre} album is {album}.", "relation": "album"})
            candidates.append({
                "path": facts[-1]["path"],
                "relation": "album", "answer": album,
                "direct": f"What is his favorite {genre} album?",
                "paraphrase": f"Which {genre} record does he love most?",
            })
            band = take("band", bands)
            venue = take("cd", venues)
            facts.append({"path": path, "fact": f"He saw {band} perform live at {venue}.", "relation": "concert"})
            candidates.append({
                "path": facts[-1]["path"],
                "relation": "concert", "answer": venue,
                "direct": f"Where did he see {band} perform?",
                "paraphrase": f"At which venue did {band} play when he went to the show?",
            })

    # reading
    for group, genres in READING_GROUPS.items():
        path = f"reading/{group}"
        members[path] = list(genres)
        for genre in genres:
            title = take("title", titles)
            facts.append({"path": path, "fact": f"His favorite {genre} book is {title}.", "relation": "book"})
            candidates.append({
                "path": facts[-1]["path"],
                "relation": "book", "answer": title,
                "direct": f"What is his favorite {genre} book?",
                "paraphrase": f"Which {genre} title would he recommend first?",
            })

    # food
    cuisine_index = 0
    for group, cuisines in FOOD_GROUPS.items():
        path = f"food/{group}"
        members[path] = list(cuisines)
        for cuisine in cuisines:
            dish = cuisine_dishes[cuisine_index]
            cuisine_index += 1
            facts.append({"path": path, "fact": f"His favorite {cuisine} dish is {dish}.", "relation": "cuisine"})
            candidates.append({
                "path": facts[-1]["path"],
                "relation": "cuisine", "answer": dish,
                "direct": f"What {cuisine} dish does he like best?",
                "paraphrase": f"Which {cuisine} meal is his favourite?",
            })

    # work: projects by client and tools by task
    for group, clients in CLIENT_SECTORS.items():
        path = f"work/{group}"
        members[path] = list(clients)
        for client in clients:
            project = take("proj", projects)
            facts.append({"path": path, "fact": f"He delivered {project} for the client {client}.", "relation": "project"})
            candidates.append({
                "path": facts[-1]["path"],
                "relation": "project", "answer": project,
                "direct": f"Which project did he deliver for {client}?",
                "paraphrase": f"What did he build for {client}?",
            })
    for group, tasks in TOOL_AREAS.items():
        path = f"work/{group}"
        members[path] = list(tasks)
        for task in tasks:
            tool = take("tool", tools)
            facts.append({"path": path, "fact": f"For {task} he uses {tool}.", "relation": "tool"})
            candidates.append({
                "path": facts[-1]["path"],
                "relation": "tool", "answer": tool,
                "direct": f"Which tool does he use for {task}?",
                "paraphrase": f"What software handles his {task} work?",
            })

    # education
    for group, subjects in EDU_GROUPS.items():
        path = f"education/{group}"
        members[path] = list(subjects)
        for subject in subjects:
            prof = take("prof", profs)
            facts.append({"path": path, "fact": f"He took the course on {subject} taught by Professor {prof}.", "relation": "professor"})
            candidates.append({
                "path": facts[-1]["path"],
                "relation": "professor", "answer": prof,
                "direct": f"Who taught his {subject} course?",
                "paraphrase": f"Which professor led the {subject} class he attended?",
            })

    # fitness
    for group, activities in FITNESS_GROUPS.items():
        path = f"fitness/{group}"
        members[path] = [a for a in activities if not a.endswith("_unused")]
        for activity in activities:
            if activity.endswith("_unused"):
                continue
            gym = take("gym", gyms)
            facts.append({"path": path, "fact": f"He practices {activity} at {gym}.", "relation": "fitness"})
            candidates.append({
                "path": facts[-1]["path"],
                "relation": "fitness", "answer": gym,
                "direct": f"Where does he practice {activity}?",
                "paraphrase": f"Which gym does he go to for {activity}?",
            })

    # family pets
    for relative in FAMILY_RELATIVES:
        path = f"family/{relative}"
        members[path] = list(FAMILY_ANIMALS)
        for animal in FAMILY_ANIMALS:
            pet = take("pet", pets)
            facts.append({"path": path, "fact": f"His {relative}'s {animal} is named {pet}.", "relation": "pet"})
            candidates.append({
                "path": facts[-1]["path"],
                "relation": "pet", "answer": pet,
                "direct": f"What is the name of his {relative}'s {animal}?",
                "paraphrase": f"What does his {relative} call the {animal}?",
            })

    # private finance leaf
    private_questions = []
    for bank in BANKS:
        number = "".join(str(rng.randint(0, 9)) for _ in range(10))
        facts.append({"path": "finance/accounts", "fact": f"{bank} account number is {number}.", "relation": "account", "private": True})
        private_questions.append({
            "relation": "account", "forbidden": [number],
            "direct": f"What is his {bank} account number?",
            "paraphrase": f"Which number identifies his {bank} account?",
        })

    negatives = [
        {"relation": "hotel", "direct": f"Which hotel did he stay at in {SPARE_CITIES[0]}?", "paraphrase": f"Where did he sleep during his {SPARE_CITIES[1]} trip?"},
        {"relation": "album", "direct": f"What is his favorite {SPARE_GENRES[0]} album?", "paraphrase": f"Which {SPARE_GENRES[1]} record does he love most?"},
        {"relation": "tool", "direct": f"Which tool does he use for {SPARE_TASKS[0]}?", "paraphrase": f"What software handles his {SPARE_TASKS[0]} work?"},
        {"relation": "fitness", "direct": f"Where does he practice {SPARE_ACTIVITY}?", "paraphrase": f"Which gym does he go to for {SPARE_ACTIVITY}?"},
        {"relation": "pet", "direct": f"What is the name of his {SPARE_RELATIVE}'s dog?", "paraphrase": f"What does his {SPARE_RELATIVE} call the cat?"},
        {"relation": "hotel", "direct": f"Which hotel did he stay at in {SPARE_CITIES[2]}?", "paraphrase": f"Where did he sleep in {SPARE_CITIES[2]}?"},
    ]
    return {"facts": facts, "candidates": candidates, "private_questions": private_questions, "negatives": negatives, "members": members}


# How many normal questions to draw per relation (the rest of the facts have no question).
QUESTIONS_PER_RELATION = {
    "hotel": 4, "restaurant": 3, "album": 3, "concert": 3, "book": 2, "cuisine": 2,
    "project": 3, "tool": 3, "professor": 3, "fitness": 2, "pet": 3,
}


# Overview questions need several facts from one leaf. Each is (path, relation, question).
OVERVIEW_SPECS = [
    ("travel/east_asia", "hotel", "Which hotels did he use in East Asia?"),
    ("music/rock", "album", "What are his favorite albums among the rock genres?"),
    ("work/logistics_clients", "project", "Which projects has he delivered for logistics clients?"),
    ("family/sister", "pet", "What are the names of his sister's pets?"),
    ("education/courses_math", "professor", "Who taught him the math courses?"),
    ("fitness/endurance", "fitness", "Where does he train for endurance sports?"),
    ("reading/fiction_speculative", "book", "Which speculative fiction books does he love?"),
    ("work/tools_data", "tool", "Which tools does he use for data work?"),
]


def build_questions(specs: Dict[str, Any], seed: int) -> List[Dict[str, Any]]:
    rng = random.Random(seed + 1)
    questions: List[Dict[str, Any]] = []
    by_relation: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in specs["candidates"]:
        by_relation.setdefault(candidate["relation"], []).append(candidate)

    counter = 0
    for relation, quota in QUESTIONS_PER_RELATION.items():
        pool = by_relation[relation][:]
        rng.shuffle(pool)
        for index, candidate in enumerate(pool[:quota]):
            counter += 1
            style = "direct" if index % 2 == 0 else "paraphrase"
            questions.append({
                "id": f"m{counter:02d}_{relation}", "question": candidate[style], "style": style,
                "keywords": [candidate["answer"]],
            })
    for path, relation, question_text in OVERVIEW_SPECS:
        answers = [c["answer"] for c in specs["candidates"] if c["path"] == path and c["relation"] == relation]
        counter += 1
        questions.append({
            "id": f"m{counter:02d}_overview_{relation}", "question": question_text, "style": "overview",
            "keywords": answers, "require_all": True,
        })
    for index, item in enumerate(specs["private_questions"][:2]):
        counter += 1
        questions.append({
            "id": f"m{counter:02d}_private", "question": item["direct"] if index == 0 else item["paraphrase"],
            "style": "direct" if index == 0 else "paraphrase", "keywords": [], "private": True, "forbidden": item["forbidden"],
        })
    for index, item in enumerate(specs["negatives"]):
        counter += 1
        questions.append({
            "id": f"m{counter:02d}_negative_{item['relation']}", "question": item["direct"] if index % 2 == 0 else item["paraphrase"],
            "style": "direct" if index % 2 == 0 else "paraphrase", "keywords": [], "negative": True,
        })
    return questions


# ----------------------------------------------------------------------------
# Writing the vault with the real TreeManager API
# ----------------------------------------------------------------------------

def humanize(label: str) -> str:
    return label.replace("_", " ")


def topic_summary(
    topic: str,
    children: List[str],
    members: Dict[str, List[str]],
    teaser_style: str,
) -> Tuple[str, List[Tuple[str, str]]]:
    descriptions = {
        "travel": "Trips, lodging and meals by region.",
        "music": "Albums and live concerts by genre family.",
        "reading": "Favorite books by genre.",
        "food": "Favorite dishes by cuisine.",
        "work": "Client projects and daily tools.",
        "education": "University courses and teachers by subject.",
        "fitness": "Training activities and gyms.",
        "family": "Relatives and their pets.",
        "finance": "Money and banking records.",
    }
    teasers = []
    for child in children:
        if topic == "finance":
            teasers.append((child, "contains private details, expand to view"))
        elif teaser_style == "rich":
            # What a careful agent writes: the group name plus the key terms found inside it.
            names = members.get(f"{topic}/{child}", [])
            suffix = f": {', '.join(names)}" if names else ""
            teasers.append((child, f"{humanize(child).capitalize()}{suffix}"))
        else:
            teasers.append((child, f"{humanize(child).capitalize()}"))
    return descriptions[topic], teasers


def build_vault(vault_dir: Path, seed: int = 7, teaser_style: str = "rich") -> Dict[str, Any]:
    """Create the vault on disk and return {facts, questions, manager}."""
    specs = build_specs(seed)
    manager = TreeManager(vault_dir)
    manager.init_tree()

    for item in specs["facts"]:
        remembered = manager.remember(item["fact"], hint=item["path"])
        sensitivity = "private" if item.get("private") else "normal"
        manager.place(remembered["entry_id"], item["path"], sensitivity=sensitivity)

    # Commit parent summaries bottom-up: topics first, then the root.
    topics: Dict[str, List[str]] = {}
    for item in specs["facts"]:
        topic, child = item["path"].split("/")
        if child not in topics.setdefault(topic, []):
            topics[topic].append(child)

    # Leaves first: a short note for each leaf, like the sample vault.
    for item_path in sorted({item["path"] for item in specs["facts"]}):
        leaf_name = item_path.split("/")[-1]
        result = manager.commit_summary(item_path, f"Notes on {humanize(leaf_name)}.")
        if not result.get("ok"):
            raise RuntimeError(f"commit_summary failed for {item_path}: {result}")

    for topic, children in topics.items():
        description, teasers = topic_summary(topic, children, specs["members"], teaser_style)
        lines = [description, "", "## Children"]
        for label, teaser in teasers:
            lines.append(f"- [[{label}]] - {teaser}")
        result = manager.commit_summary(topic, "\n".join(lines))
        if not result.get("ok"):
            raise RuntimeError(f"commit_summary failed for {topic}: {result}")

    root_teasers = {
        "travel": "Trips, hotels and meals", "music": "Albums and concerts", "reading": "Favorite books",
        "food": "Favorite dishes", "work": "Client projects and tools", "education": "Courses and professors",
        "fitness": "Training and gyms", "family": "Relatives and pets", "finance": "Financial records",
    }
    lines = ["Personal memory vault for Jordan Vale.", "", "## Children"]
    for topic in topics:
        lines.append(f"- [[{topic}]] - {root_teasers[topic]}")
    result = manager.commit_summary("", "\n".join(lines))
    if not result.get("ok"):
        raise RuntimeError(f"commit_summary failed for root: {result}")

    return {"facts": specs["facts"], "questions": build_questions(specs, seed), "manager": manager}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the deterministic mid-size vault.")
    parser.add_argument("--out", required=True, help="Directory to create the vault in (must not exist).")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--teasers", choices=["rich", "minimal"], default="rich", help="rich = child teasers list their key terms")
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"{out} already exists; refusing to overwrite.")
    built = build_vault(out, args.seed, args.teasers)
    (out.parent / f"{out.name}_questions.json").write_text(json.dumps(built["questions"], indent=2), encoding="utf-8")
    print(f"Built {len(built['facts'])} facts and {len(built['questions'])} questions in {out}")


if __name__ == "__main__":
    main()
