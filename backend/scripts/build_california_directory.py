#!/usr/bin/env python3
"""Emit california_food_trucks.json from the curated NorCal/Central CA list."""

from __future__ import annotations

import json
from pathlib import Path

# Handles come from public Instagram tags, tourism pages, or association
# pages that publish the same @handle. Do not slug-guess names.
#
# `areas` are cities/neighborhoods people type in search (Plumas Lake,
# Marysville, etc.). Every row also inherits REGION_AREAS[region].
REGION_AREAS = {
    "Sacramento": [
        "Sacramento", "Roseville", "Elk Grove", "Folsom", "Rancho Cordova",
        "Citrus Heights", "Natomas", "Midtown", "West Sacramento", "Davis",
        "Woodland", "Lincoln", "Rocklin", "South Sac", "Arden",
    ],
    "Yuba-Sutter": [
        "Plumas Lake", "Olivehurst", "Marysville", "Yuba City", "Wheatland",
        "Linda", "Live Oak", "Sutter", "Yuba County", "Sutter County",
        "Eufay", "Wheeler Ranch", "Hallwood",
    ],
    "Bay Area": [
        "San Francisco", "Oakland", "San Jose", "Berkeley", "Alameda",
        "Peninsula", "East Bay", "South Bay", "Marin", "Santa Clara",
        "Daly City", "Fremont", "Palo Alto", "Sunnyvale",
    ],
    "North State": [
        "Redding", "Chico", "Red Bluff", "Eureka", "Arcata", "Humboldt",
        "Shasta", "Oroville", "Paradise",
    ],
    "Sierra": [
        "Tahoe", "Truckee", "Reno", "Sparks", "South Lake Tahoe",
        "Incline Village", "Kings Beach",
    ],
    "Central Valley": [
        "Fresno", "Stockton", "Modesto", "Bakersfield", "Visalia", "Clovis",
        "Merced", "Turlock", "Madera", "Dinuba", "Hanford",
    ],
    "Central Coast": [
        "Santa Cruz", "Monterey", "Salinas", "Watsonville", "Capitola",
        "Carmel", "Pacific Grove", "Seaside",
    ],
}

TRUCKS = [
    # Sacramento
    ("Drewski's Hot Rod Kitchen", "American", "drewskis", "drewskisfoodtrucks", "drewskishotrod", "Sacramento"),
    ("Buckhorn BBQ Truck", "BBQ", "thebuckhornbbqtruck", "thebuckhornbbqtruck", "", "Sacramento"),
    ("SactoMoFo", "Events", "sactomofo", "sactomofo", "SactoMoFo", "Sacramento"),
    ("Krush Burger", "Burgers", "krushroseville", "krushroseville", "", "Sacramento"),
    ("Krush Burger", "Burgers", "krushburger", "", "", "Sacramento"),
    ("Potato Patoto", "Loaded Tots", "the_potato_truck", "the_potato_truck", "", "Sacramento"),
    ("Alameda Tacos Food Truck", "Mexican", "alamedatacossac", "alamedatacossac", "", "Sacramento"),
    ("Mucho Nachos Sacramento", "Mexican", "muchonachossacramento", "muchonachossacramento", "", "Sacramento"),
    ("The Pop Up Truck", "Grilled Cheese", "sactopopuptruck", "sactopopuptruck", "", "Sacramento"),
    ("SanTacos", "Mexican", "santacosmx", "santacosmx", "", "Sacramento"),
    ("Tacoa Sacramento", "Mexican", "tacoasac", "tacoasac", "", "Sacramento"),
    ("Tacos GTO", "Mexican", "tacos_gto_", "tacos_gto_", "", "Sacramento"),
    ("Tacomiendo Food Truck", "Mexican", "tacomiendofoodtruck", "tacomiendofoodtruck", "", "Sacramento"),
    ("Sac Tacos Foodtruck", "Mexican", "sactacosfoodtruck", "sactacosfoodtruck", "", "Sacramento"),
    ("The Lumpia Truck", "Filipino", "thelumpiatruck", "thelumpiatruck", "TheLumpiaTruck", "Sacramento"),
    ("Hefty Gyros", "Greek", "heftygyros", "", "", "Sacramento"),
    ("Chando's Tacos", "Mexican", "chandostacos", "", "", "Sacramento"),
    ("Local Kine Shave Ice", "Hawaiian", "localkineshaveice", "", "", "Sacramento"),
    ("West Coast Taco Bar", "Mexican", "westcoasttacobar", "", "", "Sacramento"),
    ("The Philly Foodtruck", "Sandwiches", "thephillyfoodtruck", "", "", "Sacramento"),
    ("Kado's Asian Grill", "Asian", "kadosasiangrill", "", "", "Sacramento"),
    ("Laopino Kitchen", "Lao", "laopinokitchen", "", "", "Sacramento"),
    ("PalBQ Smokehouse", "BBQ", "palbqsmokehouse", "", "", "Sacramento"),
    ("Smokinewe BBQ", "BBQ", "smokinewebbq", "", "", "Sacramento"),
    ("Birria Boys", "Mexican", "birriaboys", "", "", "Sacramento"),
    ("Authentic Street Taco", "Mexican", "authenticstreettaco", "", "", "Sacramento"),
    ("Gondo Fusion", "Fusion", "gondofusion", "", "", "Sacramento"),
    ("Gameday Grill", "Burgers", "gamedaygrill_", "", "", "Sacramento"),
    ("Island Fin Poke", "Hawaiian", "ifpcdeltashores", "", "", "Sacramento"),
    ("Bokhoking", "Vietnamese", "bokhoking", "", "", "Sacramento"),
    ("Delicious Dishez", "Soul Food", "delicious.dishez", "", "", "Sacramento"),
    ("Bangin' Bowls", "Latin Fusion", "labanginbowls", "Labanginbowls", "", "Sacramento"),
    ("The Fry Boys", "Burgers", "thefryboysnorcal", "TheFryBoysNorCal", "", "Sacramento"),
    ("Flores Munchies", "Dessert", "flores_munchies", "", "", "Sacramento"),
    ("Zazu Crepes & Coffee", "Coffee Trailer", "zazucrepes", "", "", "Sacramento"),
    ("Sama Coffee", "Coffee Cart", "samacoffeeco", "", "", "Sacramento"),
    ("Luna Cafe Sac", "Coffee Trailer", "lunacafesac", "", "", "Sacramento"),
    ("Sweet Treats by Jas", "Coffee Trailer", "sweet.treats.by_jas", "", "", "Sacramento"),
    ("Gyro Corner", "Greek", "gyrocorner_", "", "", "Sacramento"),
    # Yuba-Sutter — Plumas Lake, Olivehurst, Marysville, Yuba City, Wheatland
    # (Facebook group "Plumas Lake Food Trucks" + posted Instagram handles)
    ("Rosie's Sno Biz", "Shaved Ice", "rosies_snobiz", "", "", "Yuba-Sutter"),
    ("Copper Penny Carnivore Caravan", "Burgers", "pennycarnivore", "", "", "Yuba-Sutter"),
    ("Blue Tulip Coffee Company", "Coffee Trailer", "bluetulipcoffee", "", "", "Yuba-Sutter"),
    ("Lami Fusion", "Island Fusion", "lamifusion_", "lamifusion", "", "Yuba-Sutter"),
    ("Supreme Gyros", "Greek", "supremegyros", "SupremeGyros", "", "Yuba-Sutter"),
    ("Kiki's Chicken", "Fried Chicken", "kikischicken530", "", "", "Yuba-Sutter"),
    ("Quenchies & Munchies", "Dessert", "quenchiesmunchies", "", "", "Yuba-Sutter"),
    ("Kona Ice of Yuba City", "Shaved Ice", "konaiceyuba", "", "", "Yuba-Sutter"),
    # Bay Area — Off the Grid tagged handles + published IG
    ("Senor Sisig", "Filipino", "senorsisig", "", "", "Bay Area"),
    ("The Chairman Truck", "Taiwanese", "chairmantruck", "", "", "Bay Area"),
    ("Curry Up Now", "Indian Fusion", "curryupnow", "", "", "Bay Area"),
    ("KoJa Kitchen", "Korean Japanese", "koja_kitchen", "", "", "Bay Area"),
    ("Liba Falafel", "Middle Eastern", "libafalafel", "", "", "Bay Area"),
    ("Adobo Bite", "Filipino", "adobobite", "", "", "Bay Area"),
    ("Hons Wonton Pantry", "Chinese", "honswontonpantry", "", "", "Bay Area"),
    ("Kasa Indian", "Indian", "kasaindian", "", "", "Bay Area"),
    ("Cousins Maine Lobster", "Seafood", "cousinsmainelobster", "", "", "Bay Area"),
    ("Roli Roti", "Rotisserie", "roliroti", "", "", "Bay Area"),
    ("FroGo", "Dessert", "frogofoodtruck", "", "", "Bay Area"),
    ("Cochinita", "Yucatecan", "cochinita.sf", "", "", "Bay Area"),
    ("Da Poke Man", "Hawaiian", "da_poke_man", "", "", "Bay Area"),
    ("Meso Hungry", "Mexican", "mesohungrytoo", "", "", "Bay Area"),
    ("World Famous Corn Dogs", "American", "worldfamouscorndogs", "", "", "Bay Area"),
    ("La Churroteka", "Dessert", "lachurroteka", "", "", "Bay Area"),
    ("The Food Truck Mafia", "Events", "thefoodtruckmafia", "", "", "Bay Area"),
    ("The Guzz Co", "American", "theguzzco", "", "", "Bay Area"),
    ("Los Rockeros", "Mexican", "losrockeros_foodtruck", "", "", "Bay Area"),
    ("Crazy Empanadas", "Latin", "crazyempanadas", "", "", "Bay Area"),
    ("Charlie's Food Trailer", "American", "charliesfoodtrailer", "", "", "Bay Area"),
    ("Baby O's Donuts", "Dessert", "babyosdonuts", "", "", "Bay Area"),
    ("Bubble Hive", "Dessert", "bubblehives", "", "", "Bay Area"),
    ("El Gran Taco Loco", "Mexican", "elgrantacoloco", "", "", "Bay Area"),
    ("Bay Area Munchiez", "American", "bayarea_munchiez", "", "", "Bay Area"),
    ("Capelo's Barbecue", "BBQ", "capelosbarbecue", "", "", "Bay Area"),
    ("Wokitchen", "Asian", "wokitchen_truck", "", "", "Bay Area"),
    ("Southern Comfort Kitchen", "Cajun", "socokitchen", "", "", "Bay Area"),
    ("Korean Bobcha", "Korean", "bobchasf", "", "", "Bay Area"),
    ("Respectable Bird", "American", "respectablebird", "", "", "Bay Area"),
    ("Melina's Kitchen", "Latin", "melinaskitchen_llc", "", "", "Bay Area"),
    ("Dominic's Food Truck", "American", "dominicsfoodtruck", "", "", "Bay Area"),
    ("Golden Gate Gyro", "Greek", "goldengategyro", "", "", "Bay Area"),
    ("Curveball Sliders", "Burgers", "curveballmobile", "", "", "Bay Area"),
    ("Bombzies BBQ", "BBQ", "bombziesbbq", "", "", "Bay Area"),
    ("Global Catering Express", "Catering", "globalcateringexpress", "", "", "Bay Area"),
    ("Mozzeria", "Pizza", "mozzeriasf", "", "", "Bay Area"),
    ("Rosie's Mexican Food", "Mexican", "rosiesmexicanfood", "", "", "Bay Area"),
    ("Sam's ChowderMobile", "Seafood", "samschowdermobile", "", "", "Bay Area"),
    ("Fresh Catch Poke", "Hawaiian", "freshcatchpoke", "", "", "Bay Area"),
    ("Rincon del Cielo Taqueria", "Mexican", "rincon_del_cielo_taqueria", "", "", "Bay Area"),
    ("Jolly's Tea and Cream", "Dessert", "jollysteascream", "", "", "Bay Area"),
    ("El Gallo Giro", "Mexican", "elgallogirotruck", "", "", "Bay Area"),
    ("Adam's Grub Truck", "Burgers", "adamsgrubtruck", "", "", "Bay Area"),
    ("BunBao", "Taiwanese", "bunbaoofficial", "", "", "Bay Area"),
    ("Hula Truck", "Hawaiian", "hulatruck408", "", "", "Bay Area"),
    ("Jeepsilog", "Filipino", "jeepsilog", "", "", "Bay Area"),
    ("La Santa Torta", "Mexican", "santatortasf", "", "", "Bay Area"),
    ("Lobsta Truck SF", "Seafood", "lobstatrucksf", "", "", "Bay Area"),
    ("MOMOlicious", "Nepali", "momolicioussf", "", "", "Bay Area"),
    ("Sip n Slurp", "Asian", "sipnslurpfoodtruck", "", "", "Bay Area"),
    ("Cielito Lindo", "Mexican", "cielitolindomsk", "", "", "Bay Area"),
    ("Kabob Trolley", "Mediterranean", "kabobtrolley", "", "", "Bay Area"),
    ("Daisy's Desserts", "Dessert", "daisysdesserts", "", "", "Bay Area"),
    ("Smoothielicious", "Coffee Trailer", "smoothieliciousbayarea", "", "", "Bay Area"),
    ("The Last Drip", "Coffee Cart", "thelastdrip.coffee", "", "", "Bay Area"),
    # North State — Redding through Humboldt / Siskiyou to the Oregon border
    ("Big C's Food Coma", "BBQ", "bigcsfoodcoma", "", "", "North State"),
    ("Granny's Grill", "Filipino", "grannysgrillfilipinofoodtruck", "", "", "North State"),
    ("Dos Amigos Taqueria", "Mexican", "dosamigostaq", "", "", "North State"),
    # Sierra — Tahoe, Truckee, Reno–Sparks metro
    ("Get Rad Pizza", "Pizza", "getradpizza", "", "", "Sierra"),
    ("Reno Street Food", "Events", "foodtruckfridayreno", "", "", "Sierra"),
    ("Daddy's Tacos NV", "Mexican", "daddystacosnv", "", "", "Sierra"),
    ("Mr Yummy Yummy", "Japanese", "mryummyyummyreno", "", "", "Sierra"),
    # Central Valley
    ("Where's The Food", "Fusion", "wtfwheresthefoodfresno", "", "", "Central Valley"),
    ("Brickology Pizza", "Pizza", "brickologypizza", "", "", "Central Valley"),
    ("El Premio Mayor", "Mexican", "elpremiomayor", "", "", "Central Valley"),
    ("Tacos La Vaporera", "Mexican", "tacos_lavaporera", "", "", "Central Valley"),
    ("Sticky Rice on Wheels", "Lao", "stickyriceonwheels_fresno", "", "", "Central Valley"),
    ("Taco Pinto", "Mexican", "tacopinto1", "", "", "Central Valley"),
    ("Real Philly Cheesesteak", "Sandwiches", "fresno_cheesesteak", "", "", "Central Valley"),
    ("Get Baked 559", "Loaded Potatoes", "getbaked559", "", "", "Central Valley"),
    ("Sno Cafe", "Dessert", "snocafe", "", "", "Central Valley"),
    ("The Rolling Donut", "Dessert", "therollingdonutfresno", "", "", "Central Valley"),
    ("Tacos El Rey Azteca", "Mexican", "tacos_el_rey_azteca", "", "", "Central Valley"),
    ("Nikki's Create-A-Bowl", "Asian", "nikkiscreateabowl", "", "", "Central Valley"),
    ("Tacos La Palmita", "Mexican", "tacoslapalmita209", "", "", "Central Valley"),
    ("Tacos La Unica", "Mexican", "tacoslaunica", "", "", "Central Valley"),
    ("Birrieria Chito", "Mexican", "birrieria_chito", "", "", "Central Valley"),
    ("Tortas Ahogadas El Cejarin", "Mexican", "tortasahogadas_elcejarin", "", "", "Central Valley"),
    ("Food Fix", "American", "foodfixtruck", "", "", "Central Valley"),
    ("Jitters Coffee Truck", "Coffee Trailer", "jitterscoffeetruck", "", "", "Central Valley"),
    ("Sunflowers & Grace", "Coffee Trailer", "sunflowersandgracecoffee", "", "", "Central Valley"),
    ("Hora de Cafe", "Coffee Trailer", "_horadecafe", "", "", "Central Valley"),
    # Central Coast
    ("Funk's Franks", "American", "funksfranks", "", "", "Central Coast"),
    ("Happy Dog Hot Dogs", "American", "happydog_hotdogs", "", "", "Central Coast"),
    ("Hot Birds", "Fried Chicken", "hot_birds831", "", "", "Central Coast"),
    ("Sandwiches & Burgers", "American", "snb_foodtruck", "", "", "Central Coast"),
    ("2 Chx", "American", "two_chx", "", "", "Central Coast"),
    ("Adobo2Go", "Filipino", "adobo2go", "", "", "Central Coast"),
    ("Holopono Food Truck", "Hawaiian", "holoponosc", "", "", "Central Coast"),
    ("Masarap", "Filipino", "masarapthehomie", "", "", "Central Coast"),
    ("Yakitori Toriman", "Japanese", "yakitori_toriman", "", "", "Central Coast"),
    ("Mariposa Cuban Coffee", "Cuban", "mariposacubancoffee", "", "", "Central Coast"),
    ("Dos Hermanos Pupuseria", "Salvadoran", "dos_hermanos_pupuseria", "", "", "Central Coast"),
    ("El Rey Leon Mexican Food", "Mexican", "elreyleon_mexicanfood", "", "", "Central Coast"),
    ("La Perrona Mexican Food", "Mexican", "_laperrona", "", "", "Central Coast"),
    ("Miches & Ceviches", "Seafood", "michesandceviches", "", "", "Central Coast"),
    ("The Real Taco", "Mexican", "realtaco56", "", "", "Central Coast"),
    ("Tacos El Chuy", "Mexican", "tacoselchuy", "", "", "Central Coast"),
    ("Tacos El Jerry", "Mexican", "tacoseljerry", "", "", "Central Coast"),
    ("Taquizas Gabriel", "Mexican", "taquizasgabriel", "", "", "Central Coast"),
    ("Huda", "Mediterranean", "hudasantacruz", "", "", "Central Coast"),
    ("Mattia Pizza", "Pizza", "mattiapizza04", "", "", "Central Coast"),
]


def main() -> None:
    rows = []
    seen = set()
    for name, cuisine, instagram, facebook, x, region in TRUCKS:
        ig = instagram.strip().lstrip("@").lower()
        if not ig or ig in seen:
            continue
        seen.add(ig)
        row = {"name": name, "cuisine": cuisine, "instagram": ig, "region": region}
        if facebook:
            row["facebook"] = facebook
        if x:
            row["x"] = x
        areas = REGION_AREAS.get(region) or []
        if areas:
            row["areas"] = areas
        rows.append(row)

    payload = json.dumps(rows, indent=2) + "\n"
    backend = Path(__file__).resolve().parents[1] / "data" / "california_food_trucks.json"
    ios = Path(__file__).resolve().parents[2] / "IOS" / "RoachCoachRadar" / "california_food_trucks.json"
    swift = Path(__file__).resolve().parents[2] / "IOS" / "RoachCoachRadar" / "CaliforniaTruckDirectoryJSON.swift"
    backend.write_text(payload, encoding="utf-8")
    ios.write_text(payload, encoding="utf-8")
    indented = "\n".join(
        f"    {line}" if line else "    "
        for line in payload.rstrip().splitlines()
    )
    swift.write_text(
        "// Generated by backend/scripts/build_california_directory.py\n"
        "enum CaliforniaTruckDirectoryJSON {\n"
        "    static let raw = #\"\"\"\n"
        f"{indented}\n"
        "    \"\"\"#\n"
        "}\n",
        encoding="utf-8",
    )
    regions: dict[str, int] = {}
    for row in rows:
        regions[row["region"]] = regions.get(row["region"], 0) + 1
    print(f"wrote {len(rows)} trucks -> {backend}")
    print(f"wrote {len(rows)} trucks -> {ios}")
    print(regions)


if __name__ == "__main__":
    main()
