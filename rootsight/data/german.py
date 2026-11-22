"""Hand-made English-German shopping vocabulary for the demo's German store (DE).

The DE market shows German queries on the English (US) catalogue: a query is translated word by word, and the DE
search analyzer maps German words back to English before matching. This is demo data, not a real German dataset.
"""

from __future__ import annotations

import re

from unidecode import unidecode

WORD = re.compile(r"\w+")

PAIRS = """
headphones=kopfhörer earbuds=ohrhörer wireless=kabellos bluetooth=bluetooth speaker=lautsprecher speakers=lautsprecherset
phone=handy case=hülle charger=ladegerät cable=kabel laptop=laptop tablet=tablet keyboard=tastatur mouse=maus monitor=monitor
camera=kamera watch=uhr smart=smart tv=fernseher stand=ständer holder=halter light=licht lights=lichter lamp=lampe led=led
desk=schreibtisch chair=stuhl chairs=stühle table=tisch bed=bett pillow=kissen pillows=kissenset blanket=decke sheets=laken
mattress=matratze curtains=vorhänge rug=teppich shelf=regal shelves=regale storage=aufbewahrung box=box bag=tasche bags=taschen
backpack=rucksack wallet=geldbörse shoes=schuhe boots=stiefel sneakers=turnschuhe sandals=sandalen slippers=hausschuhe socks=socken
shirt=hemd shirts=hemden dress=kleid dresses=kleider pants=hose jacket=jacke coat=mantel hat=hut gloves=handschuhe scarf=schal
belt=gürtel sunglasses=sonnenbrille glasses=brille ring=ring necklace=halskette earrings=ohrringe bracelet=armband
women=damen men=herren kids=kinder girls=mädchen boys=jungen baby=baby toddler=kleinkind toy=spielzeug toys=spielzeuge
game=spiel games=spiele puzzle=puzzle doll=puppe book=buch books=bücher pen=stift pens=stifte paper=papier notebook=notizbuch
kitchen=küche knife=messer pan=pfanne pot=topf cup=tasse cups=tassen mug=becher bottle=flasche bottles=flaschen water=wasser
glass=glas plate=teller bowl=schüssel bowls=schüsseln spoon=löffel fork=gabel coffee=kaffee tea=tee maker=maschine
blender=mixer oven=ofen grill=grill fridge=kühlschrank vacuum=staubsauger cleaner=reiniger brush=bürste towel=handtuch
towels=handtücher soap=seife shampoo=shampoo cream=creme oil=öl hair=haar face=gesicht skin=haut mask=maske makeup=makeup
nail=nagel perfume=parfüm dog=hund cat=katze pet=haustier food=lebensmittel bird=vogel fish=fisch car=auto bike=fahrrad
helmet=helm seat=sitz cover=abdeckung mat=matte yoga=yoga fitness=fitness ball=ball tent=zelt garden=garten plant=pflanze
plants=pflanzen flower=blume flowers=blumen tree=baum christmas=weihnachten halloween=halloween party=party gift=geschenk
gifts=geschenke birthday=geburtstag wedding=hochzeit decor=deko decorations=dekorationen wall=wand door=tür window=fenster
mirror=spiegel clock=wanduhr frame=rahmen picture=bild candle=kerze candles=kerzen black=schwarz white=weiß red=rot blue=blau
green=grün yellow=gelb pink=rosa purple=lila brown=braun gray=grau gold=gold silver=silber small=klein large=groß mini=mini
long=lang short=kurz new=neu set=set pack=packung kit=kit for=für with=mit and=und without=ohne outdoor=outdoor
portable=tragbar waterproof=wasserdicht electric=elektrisch wood=holz metal=metall plastic=plastik leather=leder
cotton=baumwolle steel=stahl winter=winter summer=sommer travel=reise office=büro home=haus bathroom=badezimmer
bedroom=schlafzimmer room=zimmer organizer=organizer rack=gestell hook=haken tool=werkzeug tools=werkzeuge drill=bohrer
tape=klebeband glue=kleber battery=batterie batteries=batterien usb=usb hdmi=hdmi adapter=adapter power=strom printer=drucker
ink=tinte gaming=gaming controller=controller headset=headset microphone=mikrofon guitar=gitarre piano=klavier music=musik
drone=drohne scooter=roller stroller=kinderwagen diapers=windeln wipes=feuchttücher vitamins=vitamine protein=protein
powder=pulver snacks=snacks chocolate=schokolade candy=süßigkeiten umbrella=regenschirm luggage=gepäck suitcase=koffer
pool=pool swimsuit=badeanzug bikini=bikini pajamas=pyjama underwear=unterwäsche leggings=leggings jeans=jeans shorts=shorts
hoodie=hoodie sweater=pullover costume=kostüm fan=ventilator heater=heizung air=luft filter=filter humidifier=luftbefeuchter
thermometer=thermometer scale=waage razor=rasierer trimmer=trimmer toothbrush=zahnbürste toothpaste=zahnpasta
"""

EN_DE: dict[str, str] = dict(pair.split("=") for pair in PAIRS.split())
DE_EN: dict[str, str] = {unidecode(de): en for en, de in EN_DE.items()}
# German words that are also common English words; they never count as "the wrong language".
ALSO_ENGLISH = frozenset(
    ["hose", "tee", "rot", "mantel", "regal", "hut", "lang", "bild", "decke", "fur", "braun", "mixer", "roller",
     "pullover", "kinder", "puppe"]
)  # fmt: skip
ENGLISH_ONLY = frozenset(EN_DE) - frozenset(DE_EN)
GERMAN_ONLY = frozenset(DE_EN) - frozenset(EN_DE) - ALSO_ENGLISH


def wrong_language(query: str, market: str) -> bool:
    """Is the query typed in the other language of the store (English in DE, German in US)?"""
    words = set(WORD.findall(unidecode(query.lower())))
    foreign = {"DE": ENGLISH_ONLY, "US": GERMAN_ONLY}.get(market, frozenset())
    return bool(words & foreign)


def to_english(query: str) -> str:
    """English version of a German query (word by word)."""
    return " ".join(to_english_words(query))


def understand_german(query: str) -> str:
    """How the US store reads a query: German-only words become English, everything else stays as typed."""
    words = WORD.findall(unidecode(query.lower()))
    if not any(w in GERMAN_ONLY for w in words):
        return query
    return " ".join(DE_EN[w] if w in GERMAN_ONLY else w for w in words)


def translatable(query: str) -> bool:
    """Can every word of this English query be written in German with our vocabulary (numbers pass through)?"""
    words = WORD.findall(query.lower())
    return bool(words) and all(w in EN_DE or w.isdigit() for w in words) and any(w in EN_DE for w in words)


def to_german(query: str) -> str:
    """Word-by-word German version of an English query."""
    return " ".join(EN_DE.get(w, w) for w in WORD.findall(query.lower()))


def to_english_words(text: str) -> list[str]:
    """German words of a search text mapped back to English (unknown words stay as they are)."""
    return [DE_EN.get(w, w) for w in WORD.findall(unidecode(text.lower()))]
