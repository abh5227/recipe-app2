"""The stoplist and the form-word list used by the FULL ingredient-match pass.

STOP filters the LEFTOVER words only. It never filters the matched phrase: a matched
n-gram is an index key, so every word in it counts as matched content. That is what
makes 'half-and-half' score 0.75 instead of 0.00.
"""
STOP=set("""
a an the of to for for's with without and or plus into in on at from by as
is are be if it its this that then than so such but not no nor about around over under up
down out off per each any some all both more most less least other others another same
approx approximately about your you can will do does don t doesn even also known
one two three four five six seven eight nine ten eleven twelve dozen half quarter third
cup cups cupful tsp tsps teaspoon teaspoons tbsp tbs tbsps tablespoon tablespoons
oz ounce ounces lb lbs pound pounds g gr gram grams kg kilo kilos kilogram kilograms
ml millilitre millilitres milliliter milliliters l litre litres liter liters
pint pints quart quarts gallon gallons inch inches cm mm qt qts stick sticks
chopped diced sliced minced grated shredded crushed peeled trimmed drained rinsed washed
cut cubed halved quartered julienned crumbled beaten whisked melted softened chilled
cooled warmed toasted roasted seeded deseeded stemmed destemmed cored pitted juiced
squeezed torn shaved smashed pounded sifted packed leveled spooned firmly loosely mashed
pureed shelled husked split soaked simmered boiled fried removed reserved excluding
finely coarsely thinly thickly roughly freshly lightly well very just slightly tightly
fresh dried frozen canned tinned jarred raw cooked uncooked whole large small medium
big little tiny huge good quality best fine coarse room temperature cold hot warm
lukewarm boiling ice icy ripe unripe semi mixed neutral flavored flavoured preferred
crunchy soft firm hard thin thick long short flat leaf leaves loose instant several
mid sized size baby light dark unwaxed organic homemade store bought imported
plus extra additional optional optionally divided needed desired taste serving serve
served garnish garnishing garnished top topping decoration decorate finish
preferably ideally generous scant heaping level enough cover make note see substitute
""".split())

# 1-word matches on these are downgraded to LOW. They are index keys that name a shape,
# a portion or a preparation rather than a foodstuff, and at length 1 they are the
# classic wrong pick: 'small skin-on boneless snapper fillets' -> fillet.
FORM=set("""
pan pans cube cubes chip chips crumb crumbs fillet fillets wedge wedges piece pieces
bite zest filling mix spray part parts weight side bottom angle sharp shell shells
slurry wash granules flakes powder puree purée paste dough batter meat spice spices
stuffing bunch bundles bag bags can cans jar jars packet packets box boxes head heads
sprig sprigs stalk stalks strip strips slice slices dust dusting drizzle pinch dash
""".split())
