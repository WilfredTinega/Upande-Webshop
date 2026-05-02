import frappe


PACK_RATES = {
	"ever red":                 {"Zim": {40: 500, 50: 350, 60: 300, 70: 250}, "Standard": {50: 220, 60: 180, 70: 140}},
	"everred":                  {"Zim": {40: 500, 50: 350, 60: 300, 70: 250}, "Standard": {50: 220, 60: 180, 70: 140}},
	"proud":                    {"Zim": {40: 500, 50: 300, 60: 300, 70: 250}, "Standard": {50: 200, 60: 160, 70: 140}},
	"athena":                   {"Zim": {40: 500, 50: 350, 60: 300, 70: 250}, "Standard": {50: 220, 60: 180, 70: 140}},
	"revival":                  {"Zim": {40: 500, 50: 350, 60: 300, 70: 250}, "Standard": {50: 200, 60: 180, 70: 140}},
	"sweet revival":            {"Zim": {40: 500, 50: 350, 60: 300, 70: 250}, "Standard": {50: 200, 60: 180, 70: 140}},
	"confidential":             {"Zim": {40: 500, 50: 350, 60: 300, 70: 250}, "Standard": {50: 240, 60: 180, 70: 140}},
	"madam cerise":             {"Zim": {40: 500, 50: 350, 60: 300, 70: 250}, "Standard": {50: 240, 60: 180, 70: 140}},
	"paloma":                   {"Zim": {40: 400, 50: 300, 60: 250, 70: 200}, "Standard": {50: 200, 60: 160, 70: 140}},
	"gold finch":               {"Zim": {40: 500, 50: 350, 60: 300, 70: 250}, "Standard": {50: 200, 60: 160, 70: 140}},
	"goldfinch":                {"Zim": {40: 500, 50: 350, 60: 300, 70: 250}, "Standard": {50: 200, 60: 160, 70: 140}},
	"madam red":                {"Zim": {40: 500, 50: 350, 60: 300, 70: 250}, "Standard": {50: 220, 60: 180, 70: 140}},
	"mayfair":                  {"Standard": {50: 240, 60: 180, 70: 140}},
	"goodtimes":                {"Standard": {50: 220, 60: 180, 70: 140}},
	"everpink":                 {"Standard": {50: 220, 60: 180, 70: 140}},
	"ever pink":                {"Standard": {50: 220, 60: 180, 70: 140}},
	"deep purple":              {"Standard": {50: 220, 60: 180, 70: 140}},
	"eucalyptus parvifolia":    {"Zim": {40: 1000, 50: 800, 60: 600, 70: 400, 80: 200}},
	"eucalyptus silver dollar": {"Zim": {40: 1000, 50: 800, 60: 600, 70: 400, 80: 200}},
	"eucalyptus baby blue":     {"Zim": {40: 1000, 50: 800, 60: 600, 70: 400, 80: 200}},
	"spray roses":              {"Zim": {50: 300, 60: 220, 70: 180, 80: 150}},
	"fireworks":                {"Standard": {50: 200, 60: 180, 70: 120}},
	"snowflakes":               {"Standard": {50: 200, 60: 180, 70: 120}},
	"sweet sara":               {"Standard": {50: 200, 60: 180, 70: 120}},
	"dinara":                   {"Standard": {50: 180, 60: 160, 70: 120}},
	"mirabel":                  {"Standard": {50: 200, 60: 180, 70: 120}},
	"leila":                    {"Standard": {50: 200, 60: 180, 70: 120}},
	"reflex":                   {"Standard": {50: 200, 60: 180, 70: 120}},
	"tralala":                  {"Standard": {50: 180, 60: 160, 70: 120}},
	"odilia":                   {"Standard": {50: 200, 60: 180, 70: 120}},
	"salinero":                 {"Standard": {50: 200, 60: 180, 70: 120}},
	"alicia":                   {"Standard": {50: 200, 60: 180, 70: 120}},
}


def execute():
	if not frappe.db.exists("DocType", "Pack Rate"):
		return

	for variety, by_box in PACK_RATES.items():
		for box_group, by_length in by_box.items():
			for length_cm, stems in by_length.items():
				exists = frappe.db.exists(
					"Pack Rate",
					{"variety": variety, "box_group": box_group, "length_cm": length_cm},
				)
				if exists:
					continue
				doc = frappe.new_doc("Pack Rate")
				doc.variety = variety
				doc.box_group = box_group
				doc.length_cm = length_cm
				doc.stems_per_box = stems
				doc.insert(ignore_permissions=True)

	frappe.db.commit()
