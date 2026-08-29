import re
STOP=set("""a an the of to for with without and or plus into in on at from by as
is are be if it its this that then than so such but not no nor about around over under up
down out off per each any some all both more most less least other others another same
about approx approximately roughly about
one two three four five six seven eight nine ten eleven twelve dozen half quarter third
cup cups cupful tsp tsps teaspoon teaspoons tbsp tbsps tablespoon tablespoons
oz ounce ounces lb lbs pound pounds g gr gram grams kg kilo kilos kilogram kilograms
ml millilitre millilitres milliliter milliliters l litre litres liter liters
pint pints quart quarts gallon gallons inch inches cm mm
chopped diced sliced minced grated shredded crushed peeled trimmed drained rinsed washed
cut cubed halved quartered julienned crumbled beaten whisked melted softened chilled
cooled warmed toasted roasted seeded deseeded stemmed destemmed cored pitted zested
juiced squeezed torn shaved smashed pounded sifted packed leveled spooned firmly loosely
finely coarsely thinly thickly roughly freshly lightly well very just about slightly
fresh dried frozen canned tinned jarred raw cooked uncooked whole large small medium
big little tiny huge good quality best fine coarse room temperature cold hot warm
lukewarm boiling ice icy
plus extra additional optional optionally divided reserved needed desired taste
garnish garnishing garnished serve serving served top topping decoration decorate
preferably ideally roughly generous scant heaping level
""".split())
