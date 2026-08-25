"""
League of Legends Champion & Summoner Spell Static Catalog & DataDragon CDN Fetcher.

Provides full offline support with a built-in static catalog of all 173+ champions
(including Yunara, Mel, Ambessa, Aurora, Smolder, Hwei, Briar, etc.),
roles/lanes, square icon URLs, summoner spells, and game queue definitions.
Gracefully updates dynamically from Riot DataDragon CDN / CommunityDragon and
live LCU game-data endpoints when available.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("champ_data")

DDRAGON_VERSION = "16.16.1"
DDRAGON_BASE = f"https://ddragon.leagueoflegends.com/cdn/{DDRAGON_VERSION}"

# Static Summoner Spells catalog
STATIC_SUMMONER_SPELLS: List[Dict[str, Any]] = [
    {
        "id": 4,
        "key": "SummonerFlash",
        "name": "Flash",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerFlash.png",
        "description": "Teleports your champion a short distance toward your cursor's location.",
        "cooldown": 300,
        "modes": ["CLASSIC", "ARAM", "ARENA", "URF"],
    },
    {
        "id": 14,
        "key": "SummonerDot",
        "name": "Ignite",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerDot.png",
        "description": "Ignites target enemy champion, dealing true damage over 5 seconds and applying Grievous Wounds.",
        "cooldown": 180,
        "modes": ["CLASSIC", "ARAM", "ARENA", "URF"],
    },
    {
        "id": 12,
        "key": "SummonerTeleport",
        "name": "Teleport",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerTeleport.png",
        "description": "After channeling for 4 seconds, teleports your champion to target allied structure or minion/ward.",
        "cooldown": 360,
        "modes": ["CLASSIC"],
    },
    {
        "id": 11,
        "key": "SummonerSmite",
        "name": "Smite",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerSmite.png",
        "description": "Deals true damage to target monster or minion. Mandatory for junglers.",
        "cooldown": 15,
        "modes": ["CLASSIC"],
    },
    {
        "id": 7,
        "key": "SummonerHeal",
        "name": "Heal",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerHeal.png",
        "description": "Restores health and grants a 1-second 30% speed boost to you and target allied champion.",
        "cooldown": 240,
        "modes": ["CLASSIC", "ARAM", "ARENA", "URF"],
    },
    {
        "id": 6,
        "key": "SummonerHaste",
        "name": "Ghost",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerHaste.png",
        "description": "Gain increased Movement Speed and ability to move through units for 15 seconds.",
        "cooldown": 240,
        "modes": ["CLASSIC", "ARAM", "ARENA", "URF"],
    },
    {
        "id": 1,
        "key": "SummonerBoost",
        "name": "Cleanse",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerBoost.png",
        "description": "Removes all disables (excluding Suppression and Airborne) and summoner spell debuffs affecting your champion.",
        "cooldown": 210,
        "modes": ["CLASSIC", "ARAM", "ARENA", "URF"],
    },
    {
        "id": 21,
        "key": "SummonerBarrier",
        "name": "Barrier",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerBarrier.png",
        "description": "Shields your champion from damage for 2.5 seconds.",
        "cooldown": 180,
        "modes": ["CLASSIC", "ARAM", "ARENA", "URF"],
    },
    {
        "id": 3,
        "key": "SummonerExhaust",
        "name": "Exhaust",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerExhaust.png",
        "description": "Exhausts target enemy champion, reducing their Movement Speed by 35% and damage dealt by 35% for 3 seconds.",
        "cooldown": 210,
        "modes": ["CLASSIC", "ARAM", "ARENA", "URF"],
    },
    {
        "id": 32,
        "key": "SummonerSnowball",
        "name": "Mark (Snowball)",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerSnowball.png",
        "description": "Throw a snowball in a straight line at your enemies. If it hits, you can quickly travel to them.",
        "cooldown": 80,
        "modes": ["ARAM"],
    },
    {
        "id": 13,
        "key": "SummonerMana",
        "name": "Clarity",
        "icon": f"{DDRAGON_BASE}/img/spell/SummonerMana.png",
        "description": "Restores 50% of your maximum Mana and 25% of nearby allies' maximum Mana.",
        "cooldown": 240,
        "modes": ["ARAM"],
    },
]

# Static Queue definitions
STATIC_QUEUES: List[Dict[str, Any]] = [
    {
        "queueId": 420,
        "name": "Ranked Solo/Duo",
        "shortName": "Solo/Duo",
        "description": "5v5 Ranked Solo/Duo queue on Summoner's Rift",
        "map": "Summoner's Rift",
        "gameMode": "CLASSIC",
        "isRanked": True,
        "hasPositions": True,
        "category": "pvp",
        "maxTeamSize": 5,
    },
    {
        "queueId": 440,
        "name": "Ranked Flex",
        "shortName": "Flex 5v5",
        "description": "5v5 Ranked Flex queue on Summoner's Rift",
        "map": "Summoner's Rift",
        "gameMode": "CLASSIC",
        "isRanked": True,
        "hasPositions": True,
        "category": "pvp",
        "maxTeamSize": 5,
    },
    {
        "queueId": 400,
        "name": "Normal Draft",
        "shortName": "Draft Pick",
        "description": "5v5 Draft Pick on Summoner's Rift",
        "map": "Summoner's Rift",
        "gameMode": "CLASSIC",
        "isRanked": False,
        "hasPositions": True,
        "category": "pvp",
        "maxTeamSize": 5,
    },
    {
        "queueId": 430,
        "name": "Normal Blind",
        "shortName": "Blind Pick",
        "description": "5v5 Blind Pick on Summoner's Rift",
        "map": "Summoner's Rift",
        "gameMode": "CLASSIC",
        "isRanked": False,
        "hasPositions": False,
        "category": "pvp",
        "maxTeamSize": 5,
    },
    {
        "queueId": 450,
        "name": "ARAM",
        "shortName": "ARAM",
        "description": "5v5 All Random All Mid on Howling Abyss",
        "map": "Howling Abyss",
        "gameMode": "ARAM",
        "isRanked": False,
        "hasPositions": False,
        "category": "pvp",
        "maxTeamSize": 5,
    },
    {
        "queueId": 490,
        "name": "Quickplay",
        "shortName": "Quickplay",
        "description": "5v5 Quickplay on Summoner's Rift",
        "map": "Summoner's Rift",
        "gameMode": "CLASSIC",
        "isRanked": False,
        "hasPositions": True,
        "category": "pvp",
        "maxTeamSize": 5,
    },
    {
        "queueId": 1700,
        "name": "Arena (2v2v2v2)",
        "shortName": "Arena",
        "description": "2v2v2v2 Arena battles with Augments",
        "map": "Rings of Wrath",
        "gameMode": "CHERRY",
        "isRanked": True,
        "hasPositions": False,
        "category": "pvp",
        "maxTeamSize": 2,
    },
    {
        "queueId": 830,
        "name": "Co-op vs AI (Intro)",
        "shortName": "AI Intro",
        "description": "Co-op vs AI Intro Bots on Summoner's Rift",
        "map": "Summoner's Rift",
        "gameMode": "CLASSIC",
        "isRanked": False,
        "hasPositions": False,
        "category": "bot",
        "maxTeamSize": 5,
    },
    {
        "queueId": 840,
        "name": "Co-op vs AI (Beginner)",
        "shortName": "AI Beginner",
        "description": "Co-op vs AI Beginner Bots on Summoner's Rift",
        "map": "Summoner's Rift",
        "gameMode": "CLASSIC",
        "isRanked": False,
        "hasPositions": False,
        "category": "bot",
        "maxTeamSize": 5,
    },
    {
        "queueId": 850,
        "name": "Co-op vs AI (Intermediate)",
        "shortName": "AI Intermediate",
        "description": "Co-op vs AI Intermediate Bots on Summoner's Rift",
        "map": "Summoner's Rift",
        "gameMode": "CLASSIC",
        "isRanked": False,
        "hasPositions": False,
        "category": "bot",
        "maxTeamSize": 5,
    },
]

# Static Champions catalog with positions/roles
# role values: "top", "jungle", "mid", "bottom", "support"
STATIC_CHAMPIONS: List[Dict[str, Any]] = [
    {
        "id": 266,
        "key": "Aatrox",
        "name": "Aatrox",
        "title": "the Darkin Blade",
        "roles": [
            "top"
        ]
    },
    {
        "id": 103,
        "key": "Ahri",
        "name": "Ahri",
        "title": "the Nine-Tailed Fox",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 84,
        "key": "Akali",
        "name": "Akali",
        "title": "the Rogue Assassin",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 166,
        "key": "Akshan",
        "name": "Akshan",
        "title": "the Rogue Sentinel",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 12,
        "key": "Alistar",
        "name": "Alistar",
        "title": "the Minotaur",
        "roles": [
            "support"
        ]
    },
    {
        "id": 799,
        "key": "Ambessa",
        "name": "Ambessa",
        "title": "Matriarch of War",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 32,
        "key": "Amumu",
        "name": "Amumu",
        "title": "the Sad Mummy",
        "roles": [
            "jungle",
            "support"
        ]
    },
    {
        "id": 34,
        "key": "Anivia",
        "name": "Anivia",
        "title": "the Cryophoenix",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 1,
        "key": "Annie",
        "name": "Annie",
        "title": "the Dark Child",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 523,
        "key": "Aphelios",
        "name": "Aphelios",
        "title": "the Weapon of the Faithful",
        "roles": [
            "bottom"
        ]
    },
    {
        "id": 22,
        "key": "Ashe",
        "name": "Ashe",
        "title": "the Frost Archer",
        "roles": [
            "bottom",
            "support"
        ]
    },
    {
        "id": 136,
        "key": "AurelionSol",
        "name": "Aurelion Sol",
        "title": "The Star Forger",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 893,
        "key": "Aurora",
        "name": "Aurora",
        "title": "the Witch Between Worlds",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 268,
        "key": "Azir",
        "name": "Azir",
        "title": "the Emperor of the Sands",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 432,
        "key": "Bard",
        "name": "Bard",
        "title": "the Wandering Caretaker",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 200,
        "key": "Belveth",
        "name": "Bel'Veth",
        "title": "the Empress of the Void",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 53,
        "key": "Blitzcrank",
        "name": "Blitzcrank",
        "title": "the Great Steam Golem",
        "roles": [
            "support"
        ]
    },
    {
        "id": 63,
        "key": "Brand",
        "name": "Brand",
        "title": "the Burning Vengeance",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 201,
        "key": "Braum",
        "name": "Braum",
        "title": "the Heart of the Freljord",
        "roles": [
            "support"
        ]
    },
    {
        "id": 233,
        "key": "Briar",
        "name": "Briar",
        "title": "the Restrained Hunger",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 51,
        "key": "Caitlyn",
        "name": "Caitlyn",
        "title": "the Sheriff of Piltover",
        "roles": [
            "bottom"
        ]
    },
    {
        "id": 164,
        "key": "Camille",
        "name": "Camille",
        "title": "the Steel Shadow",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 69,
        "key": "Cassiopeia",
        "name": "Cassiopeia",
        "title": "the Serpent's Embrace",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 31,
        "key": "Chogath",
        "name": "Cho'Gath",
        "title": "the Terror of the Void",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 42,
        "key": "Corki",
        "name": "Corki",
        "title": "the Daring Bombardier",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 122,
        "key": "Darius",
        "name": "Darius",
        "title": "the Hand of Noxus",
        "roles": [
            "top"
        ]
    },
    {
        "id": 131,
        "key": "Diana",
        "name": "Diana",
        "title": "Scorn of the Moon",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 36,
        "key": "DrMundo",
        "name": "Dr. Mundo",
        "title": "the Madman of Zaun",
        "roles": [
            "top"
        ]
    },
    {
        "id": 119,
        "key": "Draven",
        "name": "Draven",
        "title": "the Glorious Executioner",
        "roles": [
            "bottom"
        ]
    },
    {
        "id": 245,
        "key": "Ekko",
        "name": "Ekko",
        "title": "the Boy Who Shattered Time",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 60,
        "key": "Elise",
        "name": "Elise",
        "title": "the Spider Queen",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 28,
        "key": "Evelynn",
        "name": "Evelynn",
        "title": "Agony's Embrace",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 81,
        "key": "Ezreal",
        "name": "Ezreal",
        "title": "the Prodigal Explorer",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 9,
        "key": "Fiddlesticks",
        "name": "Fiddlesticks",
        "title": "the Ancient Fear",
        "roles": [
            "jungle",
            "mid",
            "support"
        ]
    },
    {
        "id": 114,
        "key": "Fiora",
        "name": "Fiora",
        "title": "the Grand Duelist",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 105,
        "key": "Fizz",
        "name": "Fizz",
        "title": "the Tidal Trickster",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 3,
        "key": "Galio",
        "name": "Galio",
        "title": "the Colossus",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 41,
        "key": "Gangplank",
        "name": "Gangplank",
        "title": "the Saltwater Scourge",
        "roles": [
            "top"
        ]
    },
    {
        "id": 86,
        "key": "Garen",
        "name": "Garen",
        "title": "The Might of Demacia",
        "roles": [
            "top"
        ]
    },
    {
        "id": 150,
        "key": "Gnar",
        "name": "Gnar",
        "title": "the Missing Link",
        "roles": [
            "top"
        ]
    },
    {
        "id": 79,
        "key": "Gragas",
        "name": "Gragas",
        "title": "the Rabble Rouser",
        "roles": [
            "jungle",
            "mid",
            "top"
        ]
    },
    {
        "id": 104,
        "key": "Graves",
        "name": "Graves",
        "title": "the Outlaw",
        "roles": [
            "bottom",
            "jungle"
        ]
    },
    {
        "id": 887,
        "key": "Gwen",
        "name": "Gwen",
        "title": "The Hallowed Seamstress",
        "roles": [
            "top"
        ]
    },
    {
        "id": 120,
        "key": "Hecarim",
        "name": "Hecarim",
        "title": "the Shadow of War",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 74,
        "key": "Heimerdinger",
        "name": "Heimerdinger",
        "title": "the Revered Inventor",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 910,
        "key": "Hwei",
        "name": "Hwei",
        "title": "the Visionary",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 420,
        "key": "Illaoi",
        "name": "Illaoi",
        "title": "the Kraken Priestess",
        "roles": [
            "top"
        ]
    },
    {
        "id": 39,
        "key": "Irelia",
        "name": "Irelia",
        "title": "the Blade Dancer",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 427,
        "key": "Ivern",
        "name": "Ivern",
        "title": "the Green Father",
        "roles": [
            "jungle",
            "mid",
            "support"
        ]
    },
    {
        "id": 40,
        "key": "Janna",
        "name": "Janna",
        "title": "the Storm's Fury",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 59,
        "key": "JarvanIV",
        "name": "Jarvan IV",
        "title": "the Exemplar of Demacia",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 24,
        "key": "Jax",
        "name": "Jax",
        "title": "Grandmaster at Arms",
        "roles": [
            "top"
        ]
    },
    {
        "id": 126,
        "key": "Jayce",
        "name": "Jayce",
        "title": "the Defender of Tomorrow",
        "roles": [
            "bottom",
            "top"
        ]
    },
    {
        "id": 202,
        "key": "Jhin",
        "name": "Jhin",
        "title": "the Virtuoso",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 222,
        "key": "Jinx",
        "name": "Jinx",
        "title": "the Loose Cannon",
        "roles": [
            "bottom"
        ]
    },
    {
        "id": 897,
        "key": "KSante",
        "name": "K'Sante",
        "title": "the Pride of Nazumah",
        "roles": [
            "top"
        ]
    },
    {
        "id": 145,
        "key": "Kaisa",
        "name": "Kai'Sa",
        "title": "Daughter of the Void",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 429,
        "key": "Kalista",
        "name": "Kalista",
        "title": "the Spear of Vengeance",
        "roles": [
            "bottom"
        ]
    },
    {
        "id": 43,
        "key": "Karma",
        "name": "Karma",
        "title": "the Enlightened One",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 30,
        "key": "Karthus",
        "name": "Karthus",
        "title": "the Deathsinger",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 38,
        "key": "Kassadin",
        "name": "Kassadin",
        "title": "the Void Walker",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 55,
        "key": "Katarina",
        "name": "Katarina",
        "title": "the Sinister Blade",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 10,
        "key": "Kayle",
        "name": "Kayle",
        "title": "the Righteous",
        "roles": [
            "bottom",
            "mid",
            "top"
        ]
    },
    {
        "id": 141,
        "key": "Kayn",
        "name": "Kayn",
        "title": "the Shadow Reaper",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 85,
        "key": "Kennen",
        "name": "Kennen",
        "title": "the Heart of the Tempest",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 121,
        "key": "Khazix",
        "name": "Kha'Zix",
        "title": "the Voidreaver",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 203,
        "key": "Kindred",
        "name": "Kindred",
        "title": "The Eternal Hunters",
        "roles": [
            "bottom",
            "jungle"
        ]
    },
    {
        "id": 240,
        "key": "Kled",
        "name": "Kled",
        "title": "the Cantankerous Cavalier",
        "roles": [
            "top"
        ]
    },
    {
        "id": 96,
        "key": "KogMaw",
        "name": "Kog'Maw",
        "title": "the Mouth of the Abyss",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 7,
        "key": "Leblanc",
        "name": "LeBlanc",
        "title": "the Deceiver",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 64,
        "key": "LeeSin",
        "name": "Lee Sin",
        "title": "the Blind Monk",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 89,
        "key": "Leona",
        "name": "Leona",
        "title": "the Radiant Dawn",
        "roles": [
            "support"
        ]
    },
    {
        "id": 876,
        "key": "Lillia",
        "name": "Lillia",
        "title": "the Bashful Bloom",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 127,
        "key": "Lissandra",
        "name": "Lissandra",
        "title": "the Ice Witch",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 805,
        "key": "Locke",
        "name": "Locke",
        "title": "the Ashen Exorcist",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 236,
        "key": "Lucian",
        "name": "Lucian",
        "title": "the Purifier",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 117,
        "key": "Lulu",
        "name": "Lulu",
        "title": "the Fae Sorceress",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 99,
        "key": "Lux",
        "name": "Lux",
        "title": "the Lady of Luminosity",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 54,
        "key": "Malphite",
        "name": "Malphite",
        "title": "Shard of the Monolith",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 90,
        "key": "Malzahar",
        "name": "Malzahar",
        "title": "the Prophet of the Void",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 57,
        "key": "Maokai",
        "name": "Maokai",
        "title": "the Twisted Treant",
        "roles": [
            "support"
        ]
    },
    {
        "id": 11,
        "key": "MasterYi",
        "name": "Master Yi",
        "title": "the Wuju Bladesman",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 800,
        "key": "Mel",
        "name": "Mel",
        "title": "the Soul's Reflection",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 902,
        "key": "Milio",
        "name": "Milio",
        "title": "The Gentle Flame",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 21,
        "key": "MissFortune",
        "name": "Miss Fortune",
        "title": "the Bounty Hunter",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 82,
        "key": "Mordekaiser",
        "name": "Mordekaiser",
        "title": "the Iron Revenant",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 25,
        "key": "Morgana",
        "name": "Morgana",
        "title": "the Fallen",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 950,
        "key": "Naafiri",
        "name": "Naafiri",
        "title": "the Hound of a Hundred Bites",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 267,
        "key": "Nami",
        "name": "Nami",
        "title": "the Tidecaller",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 75,
        "key": "Nasus",
        "name": "Nasus",
        "title": "the Curator of the Sands",
        "roles": [
            "top"
        ]
    },
    {
        "id": 111,
        "key": "Nautilus",
        "name": "Nautilus",
        "title": "the Titan of the Depths",
        "roles": [
            "support"
        ]
    },
    {
        "id": 518,
        "key": "Neeko",
        "name": "Neeko",
        "title": "the Curious Chameleon",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 76,
        "key": "Nidalee",
        "name": "Nidalee",
        "title": "the Bestial Huntress",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 895,
        "key": "Nilah",
        "name": "Nilah",
        "title": "the Joy Unbound",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 56,
        "key": "Nocturne",
        "name": "Nocturne",
        "title": "the Eternal Nightmare",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 20,
        "key": "Nunu",
        "name": "Nunu & Willump",
        "title": "the Boy and His Yeti",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 2,
        "key": "Olaf",
        "name": "Olaf",
        "title": "the Berserker",
        "roles": [
            "top"
        ]
    },
    {
        "id": 61,
        "key": "Orianna",
        "name": "Orianna",
        "title": "the Lady of Clockwork",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 516,
        "key": "Ornn",
        "name": "Ornn",
        "title": "The Fire below the Mountain",
        "roles": [
            "top"
        ]
    },
    {
        "id": 80,
        "key": "Pantheon",
        "name": "Pantheon",
        "title": "the Unbreakable Spear",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 78,
        "key": "Poppy",
        "name": "Poppy",
        "title": "Keeper of the Hammer",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 555,
        "key": "Pyke",
        "name": "Pyke",
        "title": "the Bloodharbor Ripper",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 246,
        "key": "Qiyana",
        "name": "Qiyana",
        "title": "Empress of the Elements",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 133,
        "key": "Quinn",
        "name": "Quinn",
        "title": "Demacia's Wings",
        "roles": [
            "bottom",
            "mid",
            "top"
        ]
    },
    {
        "id": 497,
        "key": "Rakan",
        "name": "Rakan",
        "title": "The Charmer",
        "roles": [
            "support"
        ]
    },
    {
        "id": 33,
        "key": "Rammus",
        "name": "Rammus",
        "title": "the Armordillo",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 421,
        "key": "RekSai",
        "name": "Rek'Sai",
        "title": "the Void Burrower",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 526,
        "key": "Rell",
        "name": "Rell",
        "title": "the Iron Maiden",
        "roles": [
            "support"
        ]
    },
    {
        "id": 888,
        "key": "Renata",
        "name": "Renata Glasc",
        "title": "the Chem-Baroness",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 58,
        "key": "Renekton",
        "name": "Renekton",
        "title": "the Butcher of the Sands",
        "roles": [
            "top"
        ]
    },
    {
        "id": 107,
        "key": "Rengar",
        "name": "Rengar",
        "title": "the Pridestalker",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 92,
        "key": "Riven",
        "name": "Riven",
        "title": "the Exile",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 68,
        "key": "Rumble",
        "name": "Rumble",
        "title": "the Mechanized Menace",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 13,
        "key": "Ryze",
        "name": "Ryze",
        "title": "the Rune Mage",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 360,
        "key": "Samira",
        "name": "Samira",
        "title": "the Desert Rose",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 113,
        "key": "Sejuani",
        "name": "Sejuani",
        "title": "Fury of the North",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 235,
        "key": "Senna",
        "name": "Senna",
        "title": "the Redeemer",
        "roles": [
            "bottom",
            "support"
        ]
    },
    {
        "id": 147,
        "key": "Seraphine",
        "name": "Seraphine",
        "title": "the Starry-Eyed Songstress",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 875,
        "key": "Sett",
        "name": "Sett",
        "title": "the Boss",
        "roles": [
            "top"
        ]
    },
    {
        "id": 35,
        "key": "Shaco",
        "name": "Shaco",
        "title": "the Demon Jester",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 98,
        "key": "Shen",
        "name": "Shen",
        "title": "the Eye of Twilight",
        "roles": [
            "top"
        ]
    },
    {
        "id": 102,
        "key": "Shyvana",
        "name": "Shyvana",
        "title": "the Half-Dragon",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 27,
        "key": "Singed",
        "name": "Singed",
        "title": "the Mad Chemist",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 14,
        "key": "Sion",
        "name": "Sion",
        "title": "The Undead Juggernaut",
        "roles": [
            "top"
        ]
    },
    {
        "id": 15,
        "key": "Sivir",
        "name": "Sivir",
        "title": "the Battle Mistress",
        "roles": [
            "bottom"
        ]
    },
    {
        "id": 72,
        "key": "Skarner",
        "name": "Skarner",
        "title": "the Primordial Sovereign",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 901,
        "key": "Smolder",
        "name": "Smolder",
        "title": "the Fiery Fledgling",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 37,
        "key": "Sona",
        "name": "Sona",
        "title": "Maven of the Strings",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 16,
        "key": "Soraka",
        "name": "Soraka",
        "title": "the Starchild",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 50,
        "key": "Swain",
        "name": "Swain",
        "title": "the Noxian Grand General",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 517,
        "key": "Sylas",
        "name": "Sylas",
        "title": "the Unshackled",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 134,
        "key": "Syndra",
        "name": "Syndra",
        "title": "the Dark Sovereign",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 223,
        "key": "TahmKench",
        "name": "Tahm Kench",
        "title": "The River King",
        "roles": [
            "support",
            "top"
        ]
    },
    {
        "id": 163,
        "key": "Taliyah",
        "name": "Taliyah",
        "title": "the Stoneweaver",
        "roles": [
            "jungle",
            "mid",
            "support"
        ]
    },
    {
        "id": 91,
        "key": "Talon",
        "name": "Talon",
        "title": "the Blade's Shadow",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 44,
        "key": "Taric",
        "name": "Taric",
        "title": "the Shield of Valoran",
        "roles": [
            "support"
        ]
    },
    {
        "id": 17,
        "key": "Teemo",
        "name": "Teemo",
        "title": "the Swift Scout",
        "roles": [
            "bottom",
            "mid",
            "top"
        ]
    },
    {
        "id": 412,
        "key": "Thresh",
        "name": "Thresh",
        "title": "the Chain Warden",
        "roles": [
            "support"
        ]
    },
    {
        "id": 18,
        "key": "Tristana",
        "name": "Tristana",
        "title": "the Yordle Gunner",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 48,
        "key": "Trundle",
        "name": "Trundle",
        "title": "the Troll King",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 23,
        "key": "Tryndamere",
        "name": "Tryndamere",
        "title": "the Barbarian King",
        "roles": [
            "mid",
            "top"
        ]
    },
    {
        "id": 4,
        "key": "TwistedFate",
        "name": "Twisted Fate",
        "title": "the Card Master",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 29,
        "key": "Twitch",
        "name": "Twitch",
        "title": "the Plague Rat",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 77,
        "key": "Udyr",
        "name": "Udyr",
        "title": "the Spirit Walker",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 6,
        "key": "Urgot",
        "name": "Urgot",
        "title": "the Dreadnought",
        "roles": [
            "top"
        ]
    },
    {
        "id": 110,
        "key": "Varus",
        "name": "Varus",
        "title": "the Arrow of Retribution",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 67,
        "key": "Vayne",
        "name": "Vayne",
        "title": "the Night Hunter",
        "roles": [
            "bottom",
            "mid"
        ]
    },
    {
        "id": 45,
        "key": "Veigar",
        "name": "Veigar",
        "title": "the Tiny Master of Evil",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 161,
        "key": "Velkoz",
        "name": "Vel'Koz",
        "title": "the Eye of the Void",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 711,
        "key": "Vex",
        "name": "Vex",
        "title": "the Gloomist",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 254,
        "key": "Vi",
        "name": "Vi",
        "title": "the Piltover Enforcer",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 234,
        "key": "Viego",
        "name": "Viego",
        "title": "The Ruined King",
        "roles": [
            "jungle",
            "mid"
        ]
    },
    {
        "id": 112,
        "key": "Viktor",
        "name": "Viktor",
        "title": "the Herald of the Arcane",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 8,
        "key": "Vladimir",
        "name": "Vladimir",
        "title": "the Crimson Reaper",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 106,
        "key": "Volibear",
        "name": "Volibear",
        "title": "the Relentless Storm",
        "roles": [
            "jungle",
            "top"
        ]
    },
    {
        "id": 19,
        "key": "Warwick",
        "name": "Warwick",
        "title": "the Uncaged Wrath of Zaun",
        "roles": [
            "jungle",
            "top"
        ]
    },
    {
        "id": 62,
        "key": "MonkeyKing",
        "name": "Wukong",
        "title": "the Monkey King",
        "roles": [
            "top"
        ]
    },
    {
        "id": 498,
        "key": "Xayah",
        "name": "Xayah",
        "title": "the Rebel",
        "roles": [
            "bottom"
        ]
    },
    {
        "id": 101,
        "key": "Xerath",
        "name": "Xerath",
        "title": "the Magus Ascendant",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 5,
        "key": "XinZhao",
        "name": "Xin Zhao",
        "title": "the Seneschal of Demacia",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 157,
        "key": "Yasuo",
        "name": "Yasuo",
        "title": "the Unforgiven",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 777,
        "key": "Yone",
        "name": "Yone",
        "title": "the Unforgotten",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 83,
        "key": "Yorick",
        "name": "Yorick",
        "title": "Shepherd of Souls",
        "roles": [
            "top"
        ]
    },
    {
        "id": 804,
        "key": "Yunara",
        "name": "Yunara",
        "title": "the Unbroken Faith",
        "roles": [
            "bottom"
        ]
    },
    {
        "id": 350,
        "key": "Yuumi",
        "name": "Yuumi",
        "title": "the Magical Cat",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 904,
        "key": "Zaahen",
        "name": "Zaahen",
        "title": "The Unsundered",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 154,
        "key": "Zac",
        "name": "Zac",
        "title": "the Secret Weapon",
        "roles": [
            "jungle"
        ]
    },
    {
        "id": 238,
        "key": "Zed",
        "name": "Zed",
        "title": "the Master of Shadows",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 221,
        "key": "Zeri",
        "name": "Zeri",
        "title": "The Spark of Zaun",
        "roles": [
            "bottom"
        ]
    },
    {
        "id": 115,
        "key": "Ziggs",
        "name": "Ziggs",
        "title": "the Hexplosives Expert",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 26,
        "key": "Zilean",
        "name": "Zilean",
        "title": "the Chronokeeper",
        "roles": [
            "mid",
            "support"
        ]
    },
    {
        "id": 142,
        "key": "Zoe",
        "name": "Zoe",
        "title": "the Aspect of Twilight",
        "roles": [
            "mid"
        ]
    },
    {
        "id": 143,
        "key": "Zyra",
        "name": "Zyra",
        "title": "Rise of the Thorns",
        "roles": [
            "mid",
            "support"
        ]
    }
]


class ChampionCatalog:
    """In-memory champion, spell, and queue catalog manager."""

    def __init__(self, ddragon_version: str = DDRAGON_VERSION):
        self.ddragon_version = ddragon_version
        self.ddragon_base = f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}"
        self._champions: Dict[int, Dict[str, Any]] = {}
        self._champions_by_key: Dict[str, Dict[str, Any]] = {}
        self._spells: Dict[int, Dict[str, Any]] = {}
        self._queues: Dict[int, Dict[str, Any]] = {}
        self._initialized = False
        self._populate_static()

    def _format_champ_entry(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        key = raw.get("key", raw.get("id", ""))
        champ_id = int(raw["id"]) if isinstance(raw["id"], (int, str)) and str(raw["id"]).isdigit() else raw.get("key_id", 0)
        icon_url = f"{self.ddragon_base}/img/champion/{key}.png"
        splash_url = f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{key}_0.jpg"
        loading_url = f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{key}_0.jpg"
        return {
            "id": champ_id,
            "key": key,
            "name": raw.get("name", key),
            "title": raw.get("title", ""),
            "roles": raw.get("roles", ["mid"]),
            "icon": icon_url,
            "splash": splash_url,
            "loading": loading_url,
        }

    def _populate_static(self) -> None:
        """Loads default offline static catalogs."""
        self._champions.clear()
        self._champions_by_key.clear()
        for item in STATIC_CHAMPIONS:
            entry = self._format_champ_entry(item)
            self._champions[entry["id"]] = entry
            self._champions_by_key[entry["key"].lower()] = entry

        self._spells.clear()
        for spell in STATIC_SUMMONER_SPELLS:
            self._spells[spell["id"]] = spell

        self._queues.clear()
        for q in STATIC_QUEUES:
            self._queues[q["queueId"]] = q

        self._initialized = True

    async def update_from_ddragon(self, timeout: float = 5.0) -> bool:
        """
        Dynamically discovers the latest DataDragon version and updates champion catalog.
        Falls back seamlessly to offline catalog on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 1. Fetch latest version list
                try:
                    ver_resp = await client.get("https://ddragon.leagueoflegends.com/api/versions.json")
                    if ver_resp.status_code == 200:
                        versions = ver_resp.json()
                        if versions and isinstance(versions, list):
                            self.ddragon_version = versions[0]
                            self.ddragon_base = f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}"
                            logger.info("Using latest DataDragon version: %s", self.ddragon_version)
                except Exception as e:
                    logger.debug("Could not check latest versions.json: %s", e)

                # 2. Fetch champion.json
                url = f"{self.ddragon_base}/data/en_US/champion.json"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    champ_dict = data.get("data", {})
                    if champ_dict:
                        for key_name, champ_obj in champ_dict.items():
                            cid = int(champ_obj.get("key", 0))
                            if cid <= 0:
                                continue
                            tags = champ_obj.get("tags", [])
                            roles = []
                            for tag in tags:
                                t = tag.lower()
                                if t == "fighter" and "top" not in roles:
                                    roles.append("top")
                                elif t in ("mage", "assassin") and "mid" not in roles:
                                    roles.append("mid")
                                elif t == "marksman" and "bottom" not in roles:
                                    roles.append("bottom")
                                elif t in ("support", "tank") and "support" not in roles:
                                    roles.append("support")
                            if not roles:
                                roles = ["mid"]

                            entry = {
                                "id": cid,
                                "key": key_name,
                                "name": champ_obj.get("name", key_name),
                                "title": champ_obj.get("title", ""),
                                "roles": roles,
                                "icon": f"{self.ddragon_base}/img/champion/{key_name}.png",
                                "splash": f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{key_name}_0.jpg",
                                "loading": f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{key_name}_0.jpg",
                            }
                            self._champions[cid] = entry
                            self._champions_by_key[key_name.lower()] = entry

                        # Also refresh spells with updated version
                        for spell in STATIC_SUMMONER_SPELLS:
                            s_copy = dict(spell)
                            s_copy["icon"] = f"{self.ddragon_base}/img/spell/{spell['key']}.png"
                            self._spells[spell["id"]] = s_copy

                        logger.info("Updated champion catalog from DataDragon: %d champions available", len(self._champions))
                        return True
        except Exception as exc:
            logger.warning("DataDragon CDN fetch failed (using offline static catalog): %s", exc)
        return False

    async def update_from_lcu(self, lcu_client: Any) -> bool:
        """
        Fetches live champion definitions from the local LCU client game-data service.
        """
        try:
            champs = await lcu_client.get_champions_data()
            if champs and isinstance(champs, list):
                for c in champs:
                    cid = c.get("id", 0)
                    if cid > 0 and c.get("name"):
                        name = c.get("name")
                        alias = c.get("alias", name)
                        roles = c.get("roles", [])
                        entry = {
                            "id": cid,
                            "key": alias,
                            "name": name,
                            "title": c.get("title", ""),
                            "roles": [r.lower() for r in roles] if roles else ["mid"],
                            "icon": f"{self.ddragon_base}/img/champion/{alias}.png",
                            "splash": f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{alias}_0.jpg",
                            "loading": f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{alias}_0.jpg",
                        }
                        self._champions[cid] = entry
                        self._champions_by_key[alias.lower()] = entry
                logger.info("Updated champion catalog from live LCU: %d champions", len(self._champions))
                return True
        except Exception as e:
            logger.debug("LCU game-data champion fetch unavailable: %s", e)
        return False

    def get_all_champions(self, role_filter: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns sorted list of champions with optional role/name filtering."""
        result = list(self._champions.values())

        if role_filter:
            rf = role_filter.lower().strip()
            if rf not in ("all", "*", ""):
                result = [c for c in result if rf in [r.lower() for r in c.get("roles", [])]]

        if search:
            q = search.lower().strip()
            result = [
                c for c in result
                if q in c["name"].lower() or q in c["key"].lower() or q in c["title"].lower()
            ]

        result.sort(key=lambda x: x["name"])
        return result

    def get_champion_by_id(self, champ_id: int) -> Optional[Dict[str, Any]]:
        """Lookup champion by numeric ID."""
        return self._champions.get(int(champ_id))

    def get_champion_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        """Lookup champion by internal key string."""
        return self._champions_by_key.get(key.lower().strip())

    def get_all_spells(self) -> List[Dict[str, Any]]:
        """Returns all registered summoner spells."""
        return list(self._spells.values())

    def get_spell_by_id(self, spell_id: int) -> Optional[Dict[str, Any]]:
        """Lookup summoner spell by numeric ID."""
        return self._spells.get(int(spell_id))

    def get_all_queues(self) -> List[Dict[str, Any]]:
        """Returns all registered game queue definitions."""
        return list(self._queues.values())

    def get_queue_by_id(self, queue_id: int) -> Optional[Dict[str, Any]]:
        """Lookup game queue by numeric queue ID."""
        return self._queues.get(queue_id)


# Global singleton instance

def get_all_champions(role_filter: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
    return catalog.get_all_champions(role_filter=role_filter, search=search)

def get_champion_by_id(champ_id: int) -> Optional[Dict[str, Any]]:
    return catalog.get_champion_by_id(champ_id)

def get_champion_by_key(key: str) -> Optional[Dict[str, Any]]:
    return catalog.get_champion_by_key(key)

def get_all_spells() -> List[Dict[str, Any]]:
    return catalog.get_all_spells()

def get_spell_by_id(spell_id: int) -> Optional[Dict[str, Any]]:
    return catalog.get_spell_by_id(spell_id)

def get_all_queues() -> List[Dict[str, Any]]:
    return catalog.get_all_queues()

def get_queue_by_id(queue_id: int) -> Optional[Dict[str, Any]]:
    return catalog.get_queue_by_id(queue_id)

async def init_champ_data(ddragon_version: Optional[str] = None) -> ChampionCatalog:
    if ddragon_version:
        catalog.ddragon_version = ddragon_version
        catalog.ddragon_base = f"https://ddragon.leagueoflegends.com/cdn/{ddragon_version}"
    await catalog.update_from_ddragon()
    return catalog
catalog = ChampionCatalog()
